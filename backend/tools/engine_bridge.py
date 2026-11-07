"""The one place the MCP server reaches D's deterministic engine.

The server calls exactly two engine functions. Both take the snapshot dict the
backend built (see docs/contract.md, "Agent snapshot"):

    find_feasible_schedule(snapshot, pins, preferred_overrides) -> {
        "ok": bool, "schedule": [ScheduleEntry] | None,
        "reasons": [str], "proven_impossible": bool }

    evaluate_schedule(snapshot, schedule) -> {
        "metrics": Metrics, "valid": bool, "findings": [str] }

`pins` maps task_id -> fixed start slot. `preferred_overrides` maps task_id ->
a new preferred start slot (a soft concession). `Metrics.per_home` is keyed by
home ID.

By default these come from `backend.simulation.engine_api` (D). Set
POWERSYNC_ENGINE_MODULE to point at another module with the same two
functions; the agent tests use `backend.agents.tests.fake_engine`.
"""

from __future__ import annotations

import importlib
import os
from types import ModuleType

DEFAULT_ENGINE_MODULE = "backend.simulation.engine_api"


def load_engine() -> ModuleType:
    name = os.getenv("POWERSYNC_ENGINE_MODULE", "").strip() or DEFAULT_ENGINE_MODULE
    mod = importlib.import_module(name)
    for fn in ("find_feasible_schedule", "evaluate_schedule"):
        if not callable(getattr(mod, fn, None)):
            raise ImportError(f"{name} has no {fn}()")
    return mod
