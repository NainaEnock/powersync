"""The seam between D's backend and C's agents (see docs/contract.md, "Agent seam").

C exports interpret_request, coordinate_neighborhood, and (optionally) announce_commit from
backend.agents (signatures in the "C's interface" section below). The backend wraps them into
the internal InterpretFn / CoordinateFn forms; if they are missing it uses the labeled stubs below.
POWERSYNC_AGENT_IMPL=stub forces the stubs (tests always do this, to protect the quota).

The stubs never invent agent traffic: they emit only code-written (system_template) events
and say plainly that the household agents aren't connected.
"""

from __future__ import annotations

import inspect
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
    outcome: Literal["edits", "no_change", "infeasible", "needs_clarification"]
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
    trigger_change: Optional[dict[str, Any]] = None  # {home_id, task_id, field, old_value, new_value, old_time, new_time}


class CoordinateResult(BaseModel):
    schedule: list[dict[str, Any]]             # [{task_id, start_slot}]; backend re-validates and rebuilds
    proposal_id: str                           # e.g. "P-2", the plan being committed
    plan_name: str = ""                        # e.g. "Plan 2"
    pins: dict[str, int] = Field(default_factory=dict)
    explanation: str = ""                      # dashboard summary of why this plan
    home_explanations: dict[str, str] = Field(default_factory=dict)  # per-home summary for phones
    source: Literal["live", "stub", "deterministic_fallback"] = "live"
    rounds: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    raw: dict[str, Any] = Field(default_factory=dict)  # C's original result, passed back to announce_commit


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


# ------------------------------------------------------------------ C's interface (feat/agents-mcp)
#
# C exports from backend.agents (or backend.agents.orchestrator):
#   interpret_request(snapshot: dict, home_id, text, emit, job_id=...) -> dict
#       {outcome: proposed_change|infeasible|needs_clarification|no_change|error,
#        proposed_edits: {edits: [{task_id, field, new_value, ...}]}, explanation, message, infeasible_reasons}
#   coordinate_neighborhood(snapshot: dict, emit, job_id=..., trigger=None|requirement_change) -> dict
#       {schedule: [{task_id, start_slot, ...}], proposal_id, plan_name, source, explanation, home_views, ...}
#   announce_commit(snapshot: dict, result: dict, emit, job_id=...)   (optional; D's template otherwise)
# Each may be sync or async. The backend re-validates everything they return.

AnnounceFn = Callable[[Snapshot, CoordinateResult, Emit, str], Awaitable[None]]


async def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    out = fn(*args, **kwargs)
    if inspect.isawaitable(out):
        out = await out
    if hasattr(out, "model_dump"):
        out = out.model_dump()
    return out


def _snapshot_dict(snap: Snapshot) -> dict[str, Any]:
    from .engine_api import snapshot_dict
    return snapshot_dict(snap)


def adapt_interpret(fn: Callable[..., Any]) -> InterpretFn:
    async def interpret(ctx: InterpretContext, emit: Emit) -> InterpretResult:
        out = await _call(fn, _snapshot_dict(ctx.snapshot), ctx.home_id, ctx.text, emit, job_id=ctx.job_id)
        if not isinstance(out, dict):
            raise ValueError("interpret_request returned no result")
        outcome = out.get("outcome")
        if outcome == "error":
            raise RuntimeError(str(out.get("message") or out.get("error") or "interpreter error"))
        edits_raw = (out.get("proposed_edits") or {}).get("edits") or out.get("edits") or []
        edits = [EditRequest(task_id=e["task_id"], field=e["field"], new_value=int(e["new_value"])) for e in edits_raw]
        mapped = {"proposed_change": "edits", "infeasible": "infeasible",
                  "needs_clarification": "needs_clarification", "no_change": "no_change"}.get(outcome)
        if mapped is None:
            raise ValueError(f"unknown interpreter outcome {outcome!r}")
        if mapped == "infeasible" and edits:
            mapped = "edits"  # D's engine decides feasibility; the change card shows the reason
        return InterpretResult(
            outcome=mapped, edits=edits, explanation=str(out.get("explanation") or ""),
            message=str(out.get("message") or out.get("question") or ""),
            infeasible_reasons=[str(r) for r in out.get("infeasible_reasons") or []],
            source="stub" if out.get("source") in ("stub", "system_template") else "live",
        )
    return interpret


def adapt_coordinate(fn: Callable[..., Any]) -> CoordinateFn:
    async def coordinate(ctx: CoordinateContext, emit: Emit) -> CoordinateResult:
        trigger = None
        if ctx.trigger:
            trigger = dict(ctx.trigger_change or {}, kind="requirement_change", text=ctx.trigger,
                           home_id=ctx.trigger_home_id)
        snap = _snapshot_dict(ctx.snapshot)
        snap["next_plan_number"] = ctx.next_plan_number  # name the first proposal "Plan N", not "Plan 1" again
        out = await _call(fn, snap, emit, job_id=ctx.job_id, trigger=trigger)
        if not isinstance(out, dict) or not isinstance(out.get("schedule"), list):
            raise ValueError("coordinate_neighborhood returned no schedule")
        src = out.get("source")
        source = src if src in ("live", "stub", "deterministic_fallback") else "live"
        pid = str(out.get("proposal_id") or f"P-{ctx.next_plan_number}")
        name = str(out.get("plan_name") or ("Plan " + pid[2:] if pid.startswith("P-") else ""))
        views = out.get("home_explanations") or out.get("home_views") or {}
        return CoordinateResult(
            schedule=[e if isinstance(e, dict) else dict(e) for e in out["schedule"]],
            proposal_id=pid, plan_name=name, pins=out.get("pins") or {},
            explanation=str(out.get("explanation") or out.get("message") or ""),
            home_explanations={str(k): str(v) for k, v in dict(views).items()},
            source=source, rounds=int(out.get("rounds") or 0), model_calls=int(out.get("model_calls") or 0),
            tool_calls=int(out.get("tool_calls") or 0), raw=out,
        )
    return coordinate


def adapt_announce(fn: Callable[..., Any]) -> AnnounceFn:
    async def announce(snap: Snapshot, result: CoordinateResult, emit: Emit, job_id: str) -> None:
        await _call(fn, _snapshot_dict(snap), result.raw or result.model_dump(), emit, job_id=job_id)
    return announce


# ------------------------------------------------------------------ loader

def _find(name: str) -> Optional[Callable[..., Any]]:
    import importlib
    for mod in ("backend.agents", "backend.agents.orchestrator"):
        try:
            m = importlib.import_module(mod)
        except ModuleNotFoundError as e:
            if e.name not in (mod, "backend.agents"):  # the module exists but one of ITS imports is missing
                print(f"[powersync] {mod} import failed: {e}", file=sys.stderr)
            continue
        except Exception as e:  # noqa: BLE001  broken agents code: keep running on stubs, say why
            print(f"[powersync] {mod} import failed, using stubs: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        fn = getattr(m, name, None)
        if callable(fn):
            return fn
    return None


def load_agents() -> tuple[InterpretFn, CoordinateFn, dict[str, str], Optional[AnnounceFn]]:
    """Return (interpret, coordinate, agent_impl, announce_commit). Falls back to D's stubs per function.

    agent_impl reports "live" only when C's function is present AND an OpenRouter key is configured.
    """
    interpret: InterpretFn = stub_interpret
    coordinate: CoordinateFn = stub_coordinate
    impl = {"interpret": "stub", "coordinate": "stub"}
    if os.getenv("POWERSYNC_AGENT_IMPL", "auto").strip().lower() == "stub":
        return interpret, coordinate, impl, None
    keyed = bool(os.getenv("OPENROUTER_API_KEY", "").strip())
    if (fn := _find("interpret_request")) is not None:
        interpret, impl["interpret"] = adapt_interpret(fn), ("live" if keyed else "stub")
    if (fn := _find("coordinate_neighborhood")) is not None:
        coordinate, impl["coordinate"] = adapt_coordinate(fn), ("live" if keyed else "stub")
    announce = adapt_announce(fn) if (fn := _find("announce_commit")) is not None else None
    return interpret, coordinate, impl, announce
