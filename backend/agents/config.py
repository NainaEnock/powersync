"""Agent limits and model settings, all read from the environment.

Read at call time (not import time) so tests and a restarted job pick up
changes. D's main.py loads `.env`; nothing here reads or prints secret values
beyond passing the key to the HTTP client.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _f(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _i(name: str, default: int) -> int:
    return int(_f(name, default))


@dataclass(frozen=True)
class AgentSettings:
    model: str
    api_key_present: bool
    call_timeout_s: float
    job_budget_s: float
    agent_timeout_s: float
    max_rounds: int
    max_model_calls: int
    max_tool_calls: int
    max_tool_rounds: int
    max_retries: int


def load_settings() -> AgentSettings:
    return AgentSettings(
        model=os.getenv("OPENROUTER_MODEL", "").strip(),
        api_key_present=bool(os.getenv("OPENROUTER_API_KEY", "").strip()),
        call_timeout_s=_f("OPENROUTER_TIMEOUT_SECONDS", 20.0),
        job_budget_s=_f("OPENROUTER_JOB_SECONDS", 45.0),
        agent_timeout_s=_f("POWERSYNC_AGENT_TIMEOUT_S", 25.0),
        max_rounds=max(1, _i("POWERSYNC_MAX_ROUNDS", 3)),
        max_model_calls=max(1, _i("POWERSYNC_MAX_MODEL_CALLS", 12)),
        max_tool_calls=max(1, _i("POWERSYNC_MAX_TOOL_CALLS", 24)),
        max_tool_rounds=max(0, _i("POWERSYNC_MAX_TOOL_ROUNDS", 2)),
        max_retries=max(0, min(1, _i("POWERSYNC_MAX_RETRIES", 1))),
    )
