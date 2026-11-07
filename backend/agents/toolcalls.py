"""MCP calls made on behalf of an agent or the coordinator.

Each call counts against the job budget and emits a tool_call event before
and a tool_result event after (dashboard only; the household view drops tool
events). The snapshot always comes from the backend, never from the model.
"""

from __future__ import annotations

from typing import Any

from .events import Emitter
from .mcp_client import EnergyTools
from .openrouter import Budget

SERVER = "powersync-energy"


class Planner:
    def __init__(self, tools: EnergyTools, em: Emitter, budget: Budget, snapshot: dict[str, Any]):
        self.tools = tools
        self.em = em
        self.budget = budget
        self.snapshot = snapshot

    async def call(
        self,
        name: str,
        args: dict[str, Any],
        *,
        sender: str,
        text: str,
        round: int | None = None,
        proposal_id: str | None = None,
        snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.budget.take_tool()
        call_id = await self.em.send(
            sender=sender, recipient=SERVER, type="tool_call", text=text, round=round,
            proposal_id=proposal_id, data={"tool": name},
        )
        payload = {"snapshot": snapshot if snapshot is not None else self.snapshot, **args}
        result, latency = await self.tools.call(name, payload)
        await self.em.send(
            sender=SERVER, recipient=sender, type="tool_result", text=result.get("summary", "Done."),
            round=round, proposal_id=proposal_id, reply_to_event_id=call_id,
            data={"tool": name, "latency_ms": round_ms(latency),
                  "valid": result.get("valid", result.get("candidate_valid"))},
        )
        return result


def round_ms(seconds: float) -> int:
    return int(seconds * 1000)
