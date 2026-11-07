"""The seam between D's backend and C's agents (see docs/contract.md, "Agent seam").

C implements, in backend/agents/orchestrator.py:

    async def interpret_request(ctx: InterpretContext, emit: Emit) -> InterpretResult
    async def coordinate_neighborhood(ctx: CoordinateContext, emit: Emit) -> CoordinateResult

The backend imports them if present; otherwise it uses the labeled stubs below.
POWERSYNC_AGENT_IMPL=stub forces the stubs (tests always do this, to protect the quota).

The stubs never invent agent traffic: they emit only code-written (system_template) events
and say plainly that the household agents aren't connected.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any, Awaitable, Callable, Literal, Optional

from pydantic import BaseModel, Field

from .engine import find_feasible_schedule, preferred_schedule
from .schema import EditableField, ScheduleEntry, Snapshot
from .timefmt import clock_to_slot
from .wording import plan_announcement

# emit(event_dict) -> stored event id ("" if the job is stale and the event was dropped).
# emit({"stage": "Home B is reviewing Plan 1"}) sets state.activity and job.stage instead.
Emit = Callable[[dict[str, Any]], str]


class InterpretContext(BaseModel):
    job_id: str
    home_id: str
    text: str
    request_id: str
    request_event_id: str  # the stored resident request; reply with reply_to_event_id
    snapshot: Snapshot     # full snapshot: use engine.home_context(snapshot, home_id) for the agent
    scenario_date: str = "2026-07-15"
    planning_starts: str = "6:00 PM"


class EditRequest(BaseModel):
    task_id: str
    field: EditableField
    new_value: int


class InterpretResult(BaseModel):
    outcome: Literal["edits", "no_change", "infeasible"]
    edits: list[EditRequest] = Field(default_factory=list)
    explanation: str = ""          # shown on the confirmation card, plain English, 12-hour times
    message: str = ""              # reply to the resident when there's nothing to confirm
    infeasible_reasons: list[str] = Field(default_factory=list)
    source: Literal["live", "stub"] = "live"


class CoordinateContext(BaseModel):
    job_id: str
    snapshot: Snapshot                         # requirements already include any confirmed edit
    trigger: Optional[str] = None              # third person, e.g. "Home A's resident changed ..."
    trigger_home_id: Optional[str] = None
    previous_schedule: Optional[list[ScheduleEntry]] = None  # last committed plan, if any
    next_plan_number: int = 1                  # name proposals "Plan N", "Plan N+1", ...


class CoordinateResult(BaseModel):
    schedule: list[dict[str, Any]]             # [{task_id, start_slot}]; backend re-validates and rebuilds
    proposal_id: str                           # e.g. "P-2", the plan being committed
    plan_name: str = ""                        # e.g. "Plan 2"
    pins: dict[str, int] = Field(default_factory=dict)
    explanation: str = ""                      # dashboard summary of why this plan
    home_explanations: dict[str, str] = Field(default_factory=dict)  # per-home summary for phones
    source: Literal["live", "stub"] = "live"
    rounds: int = 0
    model_calls: int = 0
    tool_calls: int = 0


InterpretFn = Callable[[InterpretContext, Emit], Awaitable[InterpretResult]]
CoordinateFn = Callable[[CoordinateContext, Emit], Awaitable[CoordinateResult]]


# ------------------------------------------------------------------ stub interpreter

_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)", re.I)
_WORDS = {
    "ev": ("car", "ev", "charg", "vehicle"),
    "dryer": ("dryer", "laundry", "clothes"),
    "dish": ("dish",),
}


def _find_task(snap: Snapshot, home_id: str, text: str) -> Optional[str]:
    low = text.lower()
    own = [t for t in snap.tasks if t.home_id == home_id]
    for key, words in _WORDS.items():
        if any(w in low for w in words):
            for t in own:
                if t.id.endswith(key):
                    return t.id
    return None


async def stub_interpret(ctx: InterpretContext, emit: Emit) -> InterpretResult:
    """Keyword parser: '<appliance> ... by/before <time>' -> a deadline edit. Labeled stub."""
    m = _TIME.search(ctx.text)
    tid = _find_task(ctx.snapshot, ctx.home_id, ctx.text)
    if not m or not tid:
        return InterpretResult(
            outcome="no_change", source="stub",
            message="The simple backup reader couldn't find an appliance and a finish time in that. "
                    "Try something like \"Have my car ready by 11 pm.\"",
        )
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if not 1 <= hour <= 12 or minute > 59:
        return InterpretResult(outcome="no_change", source="stub", message="That time doesn't look right.")
    pm = m.group(3).lower().startswith("p")
    h24 = (hour % 12) + (12 if pm else 0)
    slot = clock_to_slot(h24, minute, as_deadline=True)
    return InterpretResult(
        outcome="edits", source="stub",
        edits=[EditRequest(task_id=tid, field="deadline_slot", new_value=slot)],
        explanation="",  # the backend writes the confirmation text from the edit
    )


# ------------------------------------------------------------------ stub coordinator

async def stub_coordinate(ctx: CoordinateContext, emit: Emit) -> CoordinateResult:
    """Engine plan only, announced by code. No agent reviews happen in stub mode."""
    snap = ctx.snapshot
    emit({"stage": "Planning with the engine (agents not connected)"})
    res = find_feasible_schedule(snap)
    if not res.ok:
        raise RuntimeError("ENGINE_NO_PLAN: " + "; ".join(res.reasons))
    name = f"Plan {ctx.next_plan_number}"
    before = ctx.previous_schedule or preferred_schedule(snap)
    label = "the current plan" if ctx.previous_schedule else "everyone's preferred times"
    text, views = plan_announcement(snap, name, before, res.schedule, label)
    emit({"sender": "coordinator", "recipient": "all_agents", "type": "proposal", "text": text,
          "home_views": views, "round": 1, "proposal_id": f"P-{ctx.next_plan_number}",
          "source": "system_template"})
    emit({"sender": "backend", "recipient": "all_agents", "type": "info",
          "text": "Household agents aren't connected yet, so nobody reviewed this plan. Using the engine's plan.",
          "home_views": {h.id: "Your household agent isn't connected yet, so the neighborhood used the engine's plan."
                         for h in snap.homes},
          "round": 1, "proposal_id": f"P-{ctx.next_plan_number}", "source": "system_template"})
    return CoordinateResult(
        schedule=[{"task_id": e.task_id, "start_slot": e.start_slot} for e in res.schedule],
        proposal_id=f"P-{ctx.next_plan_number}", plan_name=name, source="stub",
        explanation="Engine plan (household agents not connected).",
    )


# ------------------------------------------------------------------ loader

def load_agents() -> tuple[InterpretFn, CoordinateFn, dict[str, str]]:
    """Return (interpret, coordinate, agent_impl). Falls back to stubs per function."""
    interpret: InterpretFn = stub_interpret
    coordinate: CoordinateFn = stub_coordinate
    impl = {"interpret": "stub", "coordinate": "stub"}
    if os.getenv("POWERSYNC_AGENT_IMPL", "auto").strip().lower() == "stub":
        return interpret, coordinate, impl
    try:
        from backend.agents import orchestrator  # type: ignore  # C's module
    except Exception as e:  # noqa: BLE001  (missing module or import error: keep running on stubs)
        if not isinstance(e, ModuleNotFoundError):
            print(f"[powersync] agents import failed, using stubs: {type(e).__name__}: {e}", file=sys.stderr)
        return interpret, coordinate, impl
    if callable(getattr(orchestrator, "interpret_request", None)):
        interpret, impl["interpret"] = orchestrator.interpret_request, "live"
    if callable(getattr(orchestrator, "coordinate_neighborhood", None)):
        coordinate, impl["coordinate"] = orchestrator.coordinate_neighborhood, "live"
    return interpret, coordinate, impl
