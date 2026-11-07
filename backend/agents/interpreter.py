"""Interpret one resident request into proposed requirement edits.

The model only picks task, field, and a clock time. Code maps the time to a
slot, checks the edit belongs to this home, checks feasibility through MCP,
and writes the confirmation text. Nothing is applied here: D stores the
result as a PendingChange and applies it only after the resident confirms.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from pydantic import ValidationError

from .config import AgentSettings, load_settings
from .events import EmitFn, Emitter, JobStale
from .mcp_client import EnergyTools, ToolUnavailable, get_energy_tools
from .openrouter import Budget, BudgetExceeded, ModelClient, ModelUnavailable, default_model, structured_turn, with_timeout
from .prompts import INTERPRETER_SYSTEM, interpret_user
from .schemas import InterpretOutput
from .stub_model import RuleStubModel
from .timefmt import clock_to_slot, duration_text, slot_to_clock, slot_to_time
from .toolcalls import Planner
from .wording import clean_model_text, clip, home_name, label, tasks_by_id

log = logging.getLogger("powersync.agents.interpret")

FIELD_WORDS = {
    "deadline_slot": "finish time",
    "earliest_slot": "earliest start time",
    "preferred_start_slot": "preferred start time",
}


async def interpret_request(
    snapshot: dict[str, Any],
    home_id: str,
    text: str,
    emit: EmitFn,
    *,
    job_id: str,
    model: ModelClient | None = None,
    tools: EnergyTools | None = None,
    settings: AgentSettings | None = None,
) -> dict[str, Any]:
    """Returns {outcome, message, proposed_edits, explanation, feasible,
    infeasible_reasons, source, usage}. outcome is one of proposed_change,
    infeasible, needs_clarification, no_change, error.

    Emits only the activity stage and MCP tool events: D writes the reply to
    the resident from this result (contract §5)."""
    try:
        return await _interpret(snapshot, home_id, text, emit, job_id=job_id, model=model, tools=tools, settings=settings)
    except JobStale:
        return {"outcome": "error", "message": "RESET: job is no longer current", "proposed_edits": {"edits": []},
                "explanation": "", "feasible": False, "infeasible_reasons": [], "source": "live", "usage": {}}


async def _interpret(snapshot, home_id, text, emit, *, job_id, model, tools, settings) -> dict[str, Any]:
    s = settings or load_settings()
    model = model or default_model(s) or RuleStubModel()
    em = Emitter(emit, job_id=job_id, impl=model.impl)
    budget = Budget.from_settings(s)
    planner = Planner(tools or get_energy_tools(), em, budget, snapshot)
    agent = f"agent_{home_id}"
    name = home_name(snapshot, home_id)
    own = [t for t in snapshot["tasks"] if t["home_id"] == home_id]
    if not own:
        return _result("error", f"UNKNOWN_HOME: {home_id}", model, budget)

    await em.stage(f"{name}'s agent is reading the request")
    task_info = [
        {
            "id": t["id"],
            "label": label(t),
            "duration_text": duration_text(t["duration_slots"]),
            "deadline_time": slot_to_time(t["deadline_slot"]),
            "deadline_hhmm": slot_to_clock(t["deadline_slot"]),
            "preferred_time": slot_to_time(t["preferred_start_slot"]),
        }
        for t in own
    ]
    own_ids = {t["id"] for t in own}

    def check(out: InterpretOutput) -> None:
        bad = [e.task_id for e in out.edits if e.task_id not in own_ids]
        if bad:
            raise ValueError(f"these appliances are not {name}'s: {bad}. Only edit: {sorted(own_ids)}")
        for e in out.edits:
            clock_to_slot(e.new_time, kind="start")  # raises ValueError on a bad time

    messages = [
        {"role": "system", "content": INTERPRETER_SYSTEM},
        {"role": "user", "content": interpret_user(name, text, task_info, home_id)},
    ]
    try:
        out: InterpretOutput = await with_timeout(
            structured_turn(model, messages, InterpretOutput, budget, settings=s, check=check),
            min(s.agent_timeout_s, budget.remaining_s()),
        )
    except (ModelUnavailable, BudgetExceeded, ValidationError, ValueError) as exc:
        log.warning("interpret failed: %s", exc)
        await em.stage(None)
        return _result("error", f"AI_UNAVAILABLE: {exc}", model, budget)

    if not out.understood or not out.edits:
        q = clean_model_text(out.question or "", snapshot, set()) or "Could you say which appliance and what time you mean?"
        await em.stage(None)
        return _result("needs_clarification", q, model, budget)

    tasks = tasks_by_id(snapshot)
    edits = []
    for e in out.edits:
        t = tasks[e.task_id]
        kind = "deadline" if e.field == "deadline_slot" else "start"
        new = clock_to_slot(e.new_time, kind=kind)
        old = t[e.field]
        if new == old:
            continue
        edits.append({
            "task_id": t["id"], "field": e.field, "old_value": old, "new_value": new,
            "old_time": slot_to_time(old), "new_time": slot_to_time(new),
        })
    if not edits:
        msg = "That's already how your plan is set up, so nothing needs to change."
        await em.stage(None)
        return _result("no_change", msg, model, budget)

    reasons = _window_problems(snapshot, edits)
    if not reasons:
        edited = apply_edits(snapshot, edits)
        try:
            res = await planner.call(
                "find_feasible_schedule", {}, sender=agent, snapshot=edited,
                text=f"Checking whether the street can still fit everything with {name}'s change.",
            )
            if not res.get("ok"):
                reasons = [
                    "With that change, the street can't fit every appliance under its limit in time"
                    + (f": {res['reasons'][0]}" if res.get("reasons") else ".")
                ]
        except (ToolUnavailable, BudgetExceeded) as exc:
            await em.stage(None)
            return _result("error", f"PLANNER_UNAVAILABLE: {exc}", model, budget)

    change_words = "; ".join(
        f"the {FIELD_WORDS[e['field']]} for your {label(tasks[e['task_id']])} from {e['old_time']} to {e['new_time']}"
        for e in edits
    )
    if reasons:
        msg = f"I can't change {change_words}. " + " ".join(reasons)
        await em.stage(None)
        res = _result("infeasible", clip(msg), model, budget)
        res.update(proposed_edits={"edits": edits}, feasible=False, infeasible_reasons=reasons, explanation=clip(msg))
        return res

    msg = f"Change {change_words}?"  # D appends "Confirm on your phone to replan with the neighbors."
    await em.stage(None)
    res = _result("proposed_change", clip(msg), model, budget)
    res.update(proposed_edits={"edits": edits}, feasible=True, infeasible_reasons=[], explanation=clip(msg))
    return res


def apply_edits(snapshot: dict[str, Any], edits: list[dict[str, Any]]) -> dict[str, Any]:
    snap = copy.deepcopy(snapshot)
    by_id = {t["id"]: t for t in snap["tasks"]}
    for e in edits:
        by_id[e["task_id"]][e["field"]] = e["new_value"]
    return snap


def _window_problems(snapshot: dict[str, Any], edits: list[dict[str, Any]]) -> list[str]:
    snap = apply_edits(snapshot, edits)
    out = []
    for e in edits:
        t = next(x for x in snap["tasks"] if x["id"] == e["task_id"])
        need = t["earliest_slot"] + t["duration_slots"]
        if t["deadline_slot"] > 96:
            out.append(f"Planning only covers until {slot_to_time(96)} tomorrow.")
        elif need > t["deadline_slot"]:
            out.append(
                f"Your {label(t)} takes {duration_text(t['duration_slots'], noun=True)}, "
                f"so the earliest it can finish is {slot_to_time(need)}, since it can't start before "
                f"{slot_to_time(t['earliest_slot'])}."
            )
    return out


def _result(outcome: str, message: str, model: ModelClient, budget: Budget) -> dict[str, Any]:
    return {
        "outcome": outcome,
        "message": message,
        "proposed_edits": {"edits": []},
        "explanation": message,
        "feasible": outcome == "proposed_change",
        "infeasible_reasons": [],
        "source": model.impl,
        "model": model.model,
        "usage": budget.usage(),
    }
