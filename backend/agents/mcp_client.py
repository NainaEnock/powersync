"""MCP client for the powersync-energy server over stdio.

One long-lived session per backend process (`get_energy_tools()`), reopened if
the subprocess dies. Every call is a real MCP request to the server
subprocess. The child process gets the parent's environment minus secrets.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

log = logging.getLogger("powersync.agents.mcp")

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_MODULE = "backend.tools.energy_server"
_SECRET_PREFIXES = ("OPENROUTER_API_KEY", "DEMO_")


class ToolUnavailable(Exception):
    """The MCP server could not be reached or the tool call failed."""


def _child_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(_SECRET_PREFIXES)}
    env["PYTHONPATH"] = str(REPO_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.setdefault("FASTMCP_LOG_LEVEL", "WARNING")
    return env


class EnergyTools:
    server_name = "powersync-energy"

    def __init__(self, call_timeout_s: float = 15.0):
        self.call_timeout_s = call_timeout_s
        self._client: Client | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            if self._client is not None and self._client.is_connected():
                return
            transport = StdioTransport(
                command=sys.executable,
                args=["-m", SERVER_MODULE],
                env=_child_env(),
                cwd=str(REPO_ROOT),
            )
            client = Client(transport, name="powersync-backend", timeout=self.call_timeout_s)
            try:
                await client.__aenter__()
            except Exception as exc:
                raise ToolUnavailable(f"could not start {self.server_name}: {exc}") from None
            self._client = client

    async def close(self) -> None:
        async with self._lock:
            client, self._client = self._client, None
        if client is not None:
            try:
                await client.__aexit__(None, None, None)
            except Exception:  # closing a dead subprocess is fine
                pass

    async def __aenter__(self) -> "EnergyTools":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def list_tools(self) -> list[dict[str, Any]]:
        await self.start()
        tools = await self._client.list_tools()
        # fastmcp 4.x / mcp 2.x: the field is `input_schema` (`inputSchema` is deprecated).
        return [{"name": t.name, "description": t.description or "", "input_schema": t.input_schema} for t in tools]

    async def call(self, name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any], float]:
        """Call a tool. Returns (structured result, latency in seconds)."""
        await self.start()
        t0 = time.monotonic()
        try:
            res = await self._client.call_tool(name, arguments, timeout=self.call_timeout_s)
        except Exception as exc:
            if self._client is None or not self._client.is_connected():
                await self.close()
            raise ToolUnavailable(f"{name} failed: {str(exc)[:300]}") from None
        data = res.structured_content if res.structured_content is not None else res.data
        if not isinstance(data, dict):
            raise ToolUnavailable(f"{name} returned no structured result")
        return data, time.monotonic() - t0


_shared: EnergyTools | None = None


def get_energy_tools() -> EnergyTools:
    """Process-wide client. D can `await get_energy_tools().start()` at startup
    and `await get_energy_tools().close()` on shutdown."""
    global _shared
    if _shared is None:
        _shared = EnergyTools()
    return _shared
