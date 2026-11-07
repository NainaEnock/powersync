"""OpenRouter chat-completions client, job budget, and the tool-calling loop.

Backend only. The key is read from the environment and sent as a bearer
header; it is never logged. Automated tests use `ScriptedModel` from
`backend.agents.stub_model` instead of this client.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

import httpx
from pydantic import BaseModel, ValidationError

from .config import AgentSettings, load_settings
from .events import JobStale

log = logging.getLogger("powersync.agents")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class ModelUnavailable(Exception):
    """The model could not answer (timeout, HTTP error, bad config)."""


class BudgetExceeded(Exception):
    """The job ran out of model calls, tool calls, or time."""


@dataclass
class ChatResult:
    content: str | None
    tool_calls: list[dict[str, Any]]
    usage: dict[str, int]
    latency_s: float
    model: str
    raw_message: dict[str, Any]


class ModelClient(Protocol):
    impl: str  # "live" or "stub"
    model: str

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        timeout_s: float,
    ) -> ChatResult: ...


@dataclass
class Budget:
    """Per-job limits. Every model and tool call goes through take_*()."""

    max_model_calls: int
    max_tool_calls: int
    seconds: float
    started: float = field(default_factory=time.monotonic)
    model_calls: int = 0
    tool_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model_latency_s: float = 0.0
    model_failures: int = 0
    model_successes: int = 0

    @classmethod
    def from_settings(cls, s: AgentSettings) -> "Budget":
        return cls(s.max_model_calls, s.max_tool_calls, s.job_budget_s)

    def remaining_s(self) -> float:
        return self.seconds - (time.monotonic() - self.started)

    def take_model(self) -> None:
        if self.model_calls >= self.max_model_calls:
            raise BudgetExceeded("model call budget used up")
        if self.remaining_s() <= 1.0:
            raise BudgetExceeded("job time budget used up")
        self.model_calls += 1

    def take_tool(self) -> None:
        if self.tool_calls >= self.max_tool_calls:
            raise BudgetExceeded("tool call budget used up")
        self.tool_calls += 1

    def record(self, r: ChatResult) -> None:
        self.prompt_tokens += int(r.usage.get("prompt_tokens", 0) or 0)
        self.completion_tokens += int(r.usage.get("completion_tokens", 0) or 0)
        self.model_latency_s += r.latency_s

    def usage(self) -> dict[str, Any]:
        return {
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "model_latency_s": round(self.model_latency_s, 2),
            "elapsed_s": round(self.seconds - self.remaining_s(), 2),
        }


class OpenRouterClient:
    impl = "live"

    def __init__(self, api_key: str, model: str, max_retries: int = 1):
        if not api_key or not model:
            raise ModelUnavailable("OPENROUTER_API_KEY or OPENROUTER_MODEL is not set")
        self._key = api_key
        self.model = model
        self.max_retries = max_retries

    async def chat(self, messages, *, tools=None, timeout_s: float) -> ChatResult:
        body: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": 0.2}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
            "X-Title": "PowerSync",
        }
        attempt = 0
        while True:
            t0 = time.monotonic()
            try:
                async with httpx.AsyncClient(timeout=timeout_s) as http:
                    resp = await http.post(OPENROUTER_URL, json=body, headers=headers)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise _Transient(f"HTTP {resp.status_code}")
                if resp.status_code >= 400:
                    raise ModelUnavailable(f"HTTP {resp.status_code}: {_error_text(resp)}")
                data = resp.json()
                if "error" in data and not data.get("choices"):
                    raise _Transient(f"provider error: {str(data['error'])[:200]}")
                msg = data["choices"][0]["message"]
                return ChatResult(
                    content=msg.get("content"),
                    tool_calls=msg.get("tool_calls") or [],
                    usage=data.get("usage") or {},
                    latency_s=time.monotonic() - t0,
                    model=data.get("model", self.model),
                    raw_message=msg,
                )
            except (httpx.TimeoutException, httpx.TransportError, _Transient) as exc:
                if attempt < self.max_retries and timeout_s > 5:
                    attempt += 1
                    log.warning("OpenRouter transient error, retrying once: %s", type(exc).__name__)
                    continue
                kind = "timed out" if isinstance(exc, httpx.TimeoutException) else str(exc)
                raise ModelUnavailable(f"model {kind}") from None
            except (KeyError, IndexError, ValueError) as exc:
                raise ModelUnavailable(f"unexpected response shape: {type(exc).__name__}") from None


class _Transient(Exception):
    pass


def _error_text(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error", {})
        return str(err.get("message", err))[:200]
    except Exception:
        return resp.text[:200]


def default_model(settings: AgentSettings | None = None) -> ModelClient | None:
    """The live client if configured, else None. Never live under pytest."""
    if os.getenv("PYTEST_CURRENT_TEST"):
        return None
    s = settings or load_settings()
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key or not s.model:
        return None
    return OpenRouterClient(key, s.model, s.max_retries)


# ---------------------------------------------------------------------------
# Tool loop and structured output
# ---------------------------------------------------------------------------

ToolImpl = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


async def run_turn(
    model: ModelClient,
    messages: list[dict[str, Any]],
    budget: Budget,
    *,
    tool_schemas: list[dict[str, Any]] | None = None,
    tool_impls: dict[str, ToolImpl] | None = None,
    max_tool_rounds: int,
    call_timeout_s: float,
) -> str:
    """Run one agent turn, executing model tool calls until it answers.

    Returns the final assistant text. Tool calls are dispatched only to the
    given implementations; unknown tool names get an error result.
    """
    msgs = list(messages)
    tool_impls = tool_impls or {}
    for tool_round in range(max_tool_rounds + 1):
        budget.take_model()
        timeout = max(2.0, min(call_timeout_s, budget.remaining_s() - 0.5))
        offer = tool_schemas if (tool_schemas and tool_round < max_tool_rounds) else None
        try:
            r = await model.chat(msgs, tools=offer, timeout_s=timeout)
        except ModelUnavailable:
            budget.model_failures += 1
            raise
        budget.record(r)
        budget.model_successes += 1
        if not r.tool_calls:
            return r.content or ""
        msgs.append({"role": "assistant", "content": r.content or "", "tool_calls": r.tool_calls})
        for call in r.tool_calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
                if not isinstance(args, dict):
                    raise ValueError("arguments must be an object")
            except ValueError as exc:
                result: dict[str, Any] = {"error": f"bad arguments: {exc}"}
            else:
                impl = tool_impls.get(name)
                if impl is None:
                    result = {"error": f"unknown tool {name!r}"}
                else:
                    try:
                        result = await impl(args)
                    except (BudgetExceeded, JobStale):
                        raise
                    except Exception as exc:  # tool errors go back to the model
                        result = {"error": str(exc)[:300]}
            msgs.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "content": json.dumps(result)[:6000],
                }
            )
    return ""


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(text: str) -> Any:
    text = (text or "").strip()
    m = _FENCE.search(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("no JSON object in reply")


async def structured_turn(
    model: ModelClient,
    messages: list[dict[str, Any]],
    schema: type[BaseModel],
    budget: Budget,
    *,
    settings: AgentSettings,
    tool_schemas: list[dict[str, Any]] | None = None,
    tool_impls: dict[str, ToolImpl] | None = None,
    check: Callable[[BaseModel], None] | None = None,
) -> BaseModel:
    """run_turn + Pydantic validation, with one format-repair attempt.

    `check` may raise ValueError for semantic problems (wrong home, unknown
    task); that also triggers the single repair.
    """
    text = await run_turn(
        model,
        messages,
        budget,
        tool_schemas=tool_schemas,
        tool_impls=tool_impls,
        max_tool_rounds=settings.max_tool_rounds,
        call_timeout_s=settings.call_timeout_s,
    )
    try:
        return _parse(text, schema, check)
    except (ValueError, ValidationError) as exc:
        problem = str(exc)[:400]
    repair = list(messages) + [
        {"role": "assistant", "content": text[:2000]},
        {
            "role": "user",
            "content": "Your reply could not be used: "
            + problem
            + "\nReply again with only one JSON object that matches the requested format.",
        },
    ]
    text = await run_turn(
        model, repair, budget, max_tool_rounds=0, call_timeout_s=settings.call_timeout_s
    )
    return _parse(text, schema, check)


def _parse(text: str, schema: type[BaseModel], check) -> BaseModel:
    obj = schema.model_validate(extract_json(text))
    if check:
        check(obj)
    return obj


async def with_timeout(coro: Awaitable[Any], seconds: float) -> Any:
    try:
        return await asyncio.wait_for(coro, timeout=max(1.0, seconds))
    except asyncio.TimeoutError:
        raise ModelUnavailable("agent turn timed out") from None
