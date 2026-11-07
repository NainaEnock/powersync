"""Neighborhood coordination: Plan 1 from the engine, household reviews, real
peer requests and replies, and engine-built follow-up plans (PRD §13.3).

What code decides: every schedule (engine through MCP), every number, which
neighbor changes are possible ("options"), and that no deadline is relaxed.
What agents decide: whether to accept a plan, which checked option to ask a
neighbor for, whether to agree to a neighbor's request, and their own words.

This module never commits and never announces a commit. It returns the plan;
D validates it, emits the safety-check and commit messages, and commits.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from .config import AgentSettings, load_settings
from .events import EmitFn, Emitter, JobStale
from .mcp_client import EnergyTools, ToolUnavailable, get_energy_tools
from .openrouter import Budget, BudgetExceeded, ModelClient, ModelUnavailable, default_model, structured_turn, with_timeout
from .prompts import household_system, neighbor_ask_user, review_user
from .schemas import NeighborReply, ReviewOutput
from .timefmt import slot_range, slot_to_time, usd, usd_change
from .toolcalls import Planner
from .wording import (
    ask_views, cheap_hours_text, clean_model_text, clip, expensive_share, expensive_slots, is_change,
    home_ids, home_name, is_flat, label, option_ask_text, plan_announcement, possessive, reply_views,
    review_view, runs_text, starts, tasks_by_id, trigger_text,
)

log = logging.getLogger("powersync.agents.coordinate")

AGENT_FAILURES = (ModelUnavailable, BudgetExceeded, ValidationError, ValueError)


@dataclass
class Plan:
    proposal_id: str
    name: str
    schedule: list[dict[str, Any]]
    metrics: dict[str, Any]
    pins: dict[str, int] = field(default_factory=dict)
    summary: str = ""
    views: dict[str, str] = field(default_factory=dict)


@dataclass
class Review:
    home_id: str
    accept: bool
    option: dict[str, Any] | None
    event_id: str | None
    failed: bool = False
    text: str = ""


async def coordinate_neighborhood(
    snapshot: dict[str, Any],
    emit: EmitFn,
    *,
    job_id: str,
    trigger: dict[str, Any] | None = None,
    model: ModelClient | None = None,
    tools: EnergyTools | None = None,
    settings: AgentSettings | None = None,
) -> dict[str, Any]:
    """Run one bounded negotiation. `trigger` is None for the Coordinate
    button, or {"kind": "requirement_change", "home_id", "task_id", "field",
    "old_value", "new_value"} after a confirmed change.

    Returns {outcome, message, proposal_id, schedule, metrics, source,
    ai_mode, explanation, reasons, rounds, plans, usage, commit_reference}.
    outcome: plan_ready | no_plan | error. source: live | stub |
    deterministic_fallback.
    """
    s = settings or load_settings()
    if model is None:
        model = default_model(s)
    neg = _Negotiation(snapshot, emit, job_id, trigger, model, tools or get_energy_tools(), s)
    try:
        return await neg.run()
    except JobStale:
        log.info("job %s went stale (reset); stopping", job_id)
        return {"outcome": "error", "message": "RESET: job is no longer current", "schedule": None,
                "source": "live", "proposal_id": None}
    finally:
        try:
            await neg.em.stage(None)
        except Exception:
            pass


class _Negotiation:
    def __init__(self, snap, emit, job_id, trigger, model, tools, settings: AgentSettings):
        self.snap = snap
        self.trigger = trigger
        self.model: ModelClient | None = model
        self.s = settings
        impl = model.impl if model else "live"
        self.em = Emitter(emit, job_id=job_id, impl=impl)
        self.budget = Budget.from_settings(settings)
        self.planner = Planner(tools, self.em, self.budget, snap)
        self.tasks = tasks_by_id(snap)
        self.homes = home_ids(snap)
        self.flat = is_flat(snap)
        self.exp = expensive_slots(snap)
        self.history: dict[str, list[dict[str, Any]]] = {h: [] for h in self.homes}
        self.plans: list[Plan] = []
        self.context = ""
        self.rounds = 0
        self.tried: set[str] = set()
        self.notes: list[str] = []
        # D passes these on the snapshot (contract §6): plan numbers continue across the night,
        # and a replan is compared with the plan that's in force now.
        self.first_n = max(1, int(snap.get("next_plan_number") or 1))
        self.previous = snap.get("previous_schedule") or None

    # ----------------------------------------------------------------- run

    async def run(self) -> dict[str, Any]:
        text, views, self.context = trigger_text(self.snap, self.trigger)
        if not is_change(self.trigger):  # D already announced a confirmed change (contract §5)
            await self.em.send(sender="coordinator", recipient="all_agents", type="info", text=text, round=1,
                               home_views=views)
        await self.em.stage(f"Building {self._next_name()[1]}")
        try:
            plan1 = await self._first_plan()
        except (ToolUnavailable, BudgetExceeded) as exc:
            msg = "The planner couldn't be reached. Using the safe plan."
            await self.em.send(sender="coordinator", recipient="all_agents", type="error", text=msg, round=1,
                               home_views={h: msg for h in self.homes})
            return self._result("error", f"PLANNER_UNAVAILABLE: {exc}", None)
        if plan1 is None:
            return self._result("no_plan", self.notes[-1] if self.notes else "No plan fits every deadline.", None)

        if self.model is None:
            msg = f"The household agents are unavailable right now, so this uses the planner's safe {plan1.name} without negotiation."
            await self.em.send(sender="coordinator", recipient="all_agents", type="error", text=msg, round=1,
                               proposal_id=plan1.proposal_id, home_views={h: msg for h in self.homes})
            return self._result("plan_ready", msg, plan1, fallback=True)

        current = plan1
        for rnd in range(1, self.s.max_rounds + 1):
            self.rounds = rnd
            if self.budget.remaining_s() < 3:
                self.notes.append("Ran out of negotiation time.")
                break
            await self.em.stage(f"The homes are reviewing {current.name}")
            reviews = await asyncio.gather(*(self._review(h, current, rnd) for h in self.homes))
            asks = sorted((r for r in reviews if not r.accept and r.option),
                          key=lambda r: -r.option["own_saving"])
            if not asks:
                break
            if rnd == self.s.max_rounds:
                await self._info(f"That was the last negotiation round, so {current.name} stays.", rnd, current)
                break
            nxt = await self._settle(asks[0], current, rnd)
            if nxt is None:
                break
            current = nxt

        all_failed = self.budget.model_successes == 0 and self.budget.model_failures > 0
        if all_failed:
            current = plan1
            msg = f"The household agents didn't answer in time, so the street uses the planner's safe {plan1.name}."
            await self.em.send(sender="coordinator", recipient="all_agents", type="error", text=msg,
                               round=self.rounds, proposal_id=plan1.proposal_id, home_views={h: msg for h in self.homes})
            return self._result("plan_ready", msg, plan1, fallback=True)

        try:
            await self.planner.call(
                "evaluate_schedule", {"schedule": current.schedule}, sender="coordinator", round=self.rounds,
                proposal_id=current.proposal_id, text=f"Double-checking {current.name} before it goes to the final check.",
            )
        except (ToolUnavailable, BudgetExceeded):
            pass  # D's validator is the real gate
        msg = f"{current.name} goes to the final check before it becomes the neighborhood plan."
        await self._info(msg, self.rounds, current)
        return self._result("plan_ready", msg, current)

    # ------------------------------------------------------------ plans

    def _baseline(self) -> list[dict[str, Any]]:
        if self.snap.get("baseline_schedule"):
            return self.snap["baseline_schedule"]
        return [
            {"task_id": t["id"], "home_id": t["home_id"], "start_slot": t["preferred_start_slot"],
             "duration_slots": t["duration_slots"], "power_kw": t["power_kw"]}
            for t in self.snap["tasks"]
        ]

    def _next_name(self) -> tuple[str, str]:
        n = self.first_n + len(self.plans)
        return f"P-{n}", f"Plan {n}"

    async def _first_plan(self) -> Plan | None:
        pid, name = self._next_name()
        if self.previous:
            before, before_name = self.previous, "the current plan"
        else:
            before, before_name = self._baseline(), "everyone's preferred times"
        res = await self.planner.call(
            "find_feasible_schedule", {}, sender="coordinator", round=1, proposal_id=pid,
            text=f"Asking the planner for a plan that keeps the street under {self.snap['capacity_kw']:g} kW with every deadline met.",
        )
        if not res.get("ok"):
            why = " ".join(res.get("reasons") or []) or "The planner found no plan."
            msg = clip(f"No plan fits every deadline under the street limit. {why}")
            self.notes.append(msg)
            await self.em.send(sender="coordinator", recipient="all_agents", type="info", text=msg, round=1,
                               home_views={h: "No plan fits every deadline tonight. Your current plan stays." for h in self.homes})
            return None
        cmp = await self.planner.call(
            "compare_schedules", {"baseline": before, "candidate": res["schedule"]},
            sender="coordinator", round=1, proposal_id=pid,
            text=f"Comparing {name} with {before_name}.",
        )
        self.baseline_metrics, self.baseline_name = cmp["baseline_metrics"], before_name
        plan = Plan(pid, name, res["schedule"], cmp["candidate_metrics"], {})
        text, views = plan_announcement(
            self.snap, plan.proposal_id, plan.name, plan.schedule, plan.metrics,
            previous=before, previous_name=before_name, previous_metrics=self.baseline_metrics,
        )
        plan.summary, plan.views = text, views
        self.plans.append(plan)
        await self.em.send(sender="coordinator", recipient="all_agents", type="proposal", text=text, round=1,
                           proposal_id=plan.proposal_id, home_views=views)
        return plan

    async def _next_plan(self, current: Plan, pins: dict[str, int], rnd: int) -> Plan | None:
        pid, name = self._next_name()
        res = await self.planner.call(
            "find_feasible_schedule", {"pins": pins}, sender="coordinator", round=rnd, proposal_id=pid,
            text=f"Asking the planner to build {name} with the agreed change.",
        )
        if not res.get("ok"):
            await self._info(f"The planner couldn't fit the agreed change, so {current.name} stays.", rnd, current)
            return None
        cmp = await self.planner.call(
            "compare_schedules", {"baseline": current.schedule, "candidate": res["schedule"]},
            sender="coordinator", round=rnd, proposal_id=pid, text=f"Comparing {name} with {current.name}.",
        )
        if not cmp.get("candidate_valid"):
            await self._info(f"{name} didn't pass the checks, so {current.name} stays.", rnd, current)
            return None
        plan = Plan(pid, name, res["schedule"], cmp["candidate_metrics"], dict(pins))
        text, views = plan_announcement(
            self.snap, pid, name, plan.schedule, plan.metrics,
            previous=current.schedule, previous_name=current.name, previous_metrics=current.metrics,
        )
        plan.summary, plan.views = text, views
        self.plans.append(plan)
        await self.em.send(sender="coordinator", recipient="all_agents", type="proposal", text=text,
                           round=rnd + 1, proposal_id=pid, home_views=views)
        return plan

    # ---------------------------------------------------------- options

    async def _options(self, home: str, plan: Plan, rnd: int) -> list[dict[str, Any]]:
        """Neighbor changes the engine confirms would lower this home's cost."""
        if self.flat:
            return []
        cur = starts(plan.schedule)
        out: list[dict[str, Any]] = []
        own = sorted((t for t in self.snap["tasks"] if t["home_id"] == home), key=lambda t: -t["power_kw"])
        for t in own:
            s0 = cur[t["id"]]
            if expensive_share(t, s0, self.exp) == 0:
                continue
            last = min(t["deadline_slot"], 96) - t["duration_slots"]
            cheap = [s for s in range(t["earliest_slot"], last + 1)
                     if all(i not in self.exp for i in range(s, s + t["duration_slots"]))]
            cheap.sort(key=lambda s: (abs(s - s0), s))
            for s in cheap[:2]:
                key = f"{t['id']}@{s}"
                if key in self.tried:
                    continue
                pins = {**plan.pins, t["id"]: s}
                res = await self.planner.call(
                    "find_feasible_schedule", {"pins": pins}, sender=f"agent_{home}", round=rnd,
                    proposal_id=plan.proposal_id,
                    text=f"Checking whether {possessive(self.snap, home, t)} could run at {slot_to_time(s)} in cheaper hours.",
                )
                if not res.get("ok"):
                    continue
                cmp = await self.planner.call(
                    "compare_schedules", {"baseline": plan.schedule, "candidate": res["schedule"]},
                    sender=f"agent_{home}", round=rnd, proposal_id=plan.proposal_id,
                    text=f"Comparing that change with {plan.name}.",
                )
                own_delta = cmp["per_home"].get(home, {}).get("cost_delta_usd", 0.0)
                if own_delta > -0.005 or not cmp.get("candidate_valid"):
                    continue
                window = set(range(s, s + t["duration_slots"]))
                asks = []
                for mv in cmp["moved"]:
                    if mv["home_id"] == home:
                        continue
                    nt = self.tasks[mv["task_id"]]
                    old_run = set(range(mv["from_slot"], mv["from_slot"] + nt["duration_slots"]))
                    if old_run & window:
                        asks.append({**mv, "cost_delta_usd": cmp["per_home"].get(mv["home_id"], {}).get("cost_delta_usd", 0.0)})
                asks = asks[:1]  # one neighbor request per option keeps each exchange readable
                if asks:
                    a = asks[0]
                    nt = self.tasks[a["task_id"]]
                    desc = (
                        f"If {possessive(self.snap, a['home_id'], nt)} started at {slot_to_time(a['to_slot'])} instead of "
                        f"{slot_to_time(a['from_slot'])} ({home_name(self.snap, a['home_id'])} would still finish by "
                        f"{slot_to_time(a['to_slot'] + nt['duration_slots'])}, before its {slot_to_time(nt['deadline_slot'])} deadline), "
                        f"your {label(t)} could run {runs_text(t, s)} and your charge would drop by {usd(-own_delta)}."
                    )
                    ask_text = option_ask_text(self.snap, home, a, t, s)
                else:
                    desc = f"Your {label(t)} could simply run {runs_text(t, s)}, and your charge would drop by {usd(-own_delta)}."
                    ask_text = f"Could my {label(t)} run {runs_text(t, s)} instead? Nobody else has to move."
                out.append({
                    "option_id": f"{plan.proposal_id}-{home}-{len(out) + 1}",
                    "key": key, "task_id": t["id"], "start": s, "own_saving": -own_delta,
                    "asks": asks, "description": desc, "ask_text": ask_text,
                    "money": {usd(-own_delta)},
                })
                break
        return out

    # ---------------------------------------------------------- reviews

    async def _turn(self, home: str, user: str, schema, check=None, tools=True):
        sys_msg = {"role": "system", "content": household_system(home_name(self.snap, home))}
        msgs = [sys_msg, *self.history[home], {"role": "user", "content": user}]
        schemas, impls = (self._home_tools(home) if tools else (None, None))
        out = await with_timeout(
            structured_turn(self.model, msgs, schema, self.budget, settings=self.s,
                            tool_schemas=schemas, tool_impls=impls, check=check),
            min(self.s.agent_timeout_s, self.budget.remaining_s()),
        )
        self.history[home] += [{"role": "user", "content": user},
                               {"role": "assistant", "content": json.dumps(out.model_dump())}]
        return out

    def _home_tools(self, home: str):
        if self.s.max_tool_rounds <= 0:
            return None, None
        schema = [{
            "type": "function",
            "function": {
                "name": "get_my_home_context",
                "description": "Your home's appliances, deadlines, and today's prices from the energy planner.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        }]

        async def impl(_args):
            return await self.planner.call("get_home_context", {"home_id": home}, sender=f"agent_{home}",
                                           text=f"{home_name(self.snap, home)}'s agent is looking up its own appliances.")
        return schema, {"get_my_home_context": impl}

    async def _review(self, home: str, plan: Plan, rnd: int) -> Review:
        name = home_name(self.snap, home)
        await self.em.stage(f"{name} is reviewing {plan.name}")  # B's home cards key off "Home X"
        try:
            opts = await self._options(home, plan, rnd)
        except (ToolUnavailable, BudgetExceeded) as exc:
            log.warning("options for %s failed: %s", home, exc)
            opts = []
        cur = starts(plan.schedule)
        own = [t for t in self.snap["tasks"] if t["home_id"] == home]
        own_cost = plan.metrics["per_home"].get(home, {}).get("variable_cost_usd", 0.0)
        meta = {
            "kind": "review", "home_id": home, "proposal_id": plan.proposal_id, "proposal_name": plan.name,
            "context": self._context_for(home), "flat": self.flat, "prices": cheap_hours_text(self.snap),
            "own_tasks": [{
                "label": label(t), "runs": runs_text(t, cur[t["id"]]), "deadline": slot_to_time(t["deadline_slot"]),
                "share_in_expensive_hours": expensive_share(t, cur[t["id"]], self.exp),
            } for t in own],
            "own_cost": usd(own_cost), "street_peak_kw": round(plan.metrics["peak_kw"], 1),
            "capacity_kw": self.snap["capacity_kw"],
            "options": [{k: o[k] for k in ("option_id", "description", "ask_text")} for o in opts],
        }
        by_id = {o["option_id"]: o for o in opts}

        def check(out: ReviewOutput) -> None:
            if out.home_id.strip().upper().removeprefix("HOME ").strip() != home:
                raise ValueError(f"home_id must be {home!r}")
            if out.proposal_id != plan.proposal_id:
                raise ValueError(f"proposal_id must be {plan.proposal_id!r}")
            if out.request_option_id and out.request_option_id not in by_id:
                raise ValueError(f"request_option_id must be one of {sorted(by_id) or 'null'}")

        try:
            out: ReviewOutput = await self._turn(home, review_user(meta), ReviewOutput, check)
        except AGENT_FAILURES as exc:
            log.warning("review by %s failed: %s", home, exc)
            msg = f"{name} didn't answer in time. Treating {plan.name} as acceptable for now."
            await self.em.send(sender=f"agent_{home}", recipient="coordinator", type="error", text=msg, round=rnd,
                               proposal_id=plan.proposal_id, home_views={home: msg})
            return Review(home, True, None, None, failed=True)

        option = by_id.get(out.request_option_id or "") if not out.accept else None
        objecting = option is not None
        money = set().union(*(o["money"] for o in opts)) if opts else set()
        money |= {usd(own_cost)}
        text = clean_model_text(out.public_message, self.snap, money)
        written = text is not None
        if text is None:
            text = option["ask_text"] if objecting else (
                f"{plan.name} works for my home." if out.accept else f"{plan.name} isn't ideal for my home, but I can live with it.")
        pricey = [label(t) for t in own if expensive_share(t, cur[t["id"]], self.exp) > 0]
        view = review_view(self.snap, home, plan.name, out.accept, pricey, objecting)
        if objecting and option["asks"]:
            a = option["asks"][0]
            eid = await self.em.send(
                sender=f"agent_{home}", recipient=f"agent_{a['home_id']}", type="counteroffer", text=text,
                round=rnd, proposal_id=plan.proposal_id, model_written=written,
                home_views={**ask_views(self.snap, home, a), home: view},
                data={"stance": "object", "option_id": option["option_id"]},
            )
        else:
            stance = "accept" if out.accept else ("object" if objecting else "concern")
            eid = await self.em.send(
                sender=f"agent_{home}", recipient="coordinator", type="review", text=text, round=rnd,
                proposal_id=plan.proposal_id, model_written=written, home_views={home: view},
                data={"stance": stance, **({"option_id": option["option_id"]} if option else {})},
            )
        return Review(home, not objecting, option, eid, text=text)

    def _context_for(self, home: str) -> str:
        """Third-person trigger context; the triggering home hears it as 'your resident'."""
        t = self.trigger or {}
        if is_change(t) and t.get("home_id") == home:
            return "Your own resident just changed one of your requirements; the deadlines below include it."
        return self.context

    # ------------------------------------------------------ peer exchange

    async def _settle(self, req: Review, current: Plan, rnd: int) -> Plan | None:
        opt = req.option
        self.tried.add(opt["key"])
        pins = {**current.pins, opt["task_id"]: opt["start"]}
        for a in opt["asks"]:
            agreed = await self._ask(req, a, current, rnd)
            if not agreed:
                await self._info(f"No change was agreed, so {current.name} stays.", rnd, current)
                return None
            pins[a["task_id"]] = a["to_slot"]
        await self.em.stage(f"Building {self._next_name()[1]}")
        try:
            return await self._next_plan(current, pins, rnd)
        except (ToolUnavailable, BudgetExceeded) as exc:
            log.warning("next plan failed: %s", exc)
            await self._info(f"The planner couldn't build the next plan in time, so {current.name} stays.", rnd, current)
            return None

    async def _ask(self, req: Review, a: dict[str, Any], current: Plan, rnd: int) -> bool:
        responder, requester = a["home_id"], req.home_id
        t = self.tasks[a["task_id"]]
        on_time = a["to_slot"] + t["duration_slots"] <= t["deadline_slot"]
        delta = float(a.get("cost_delta_usd", 0.0))
        await self.em.stage(f"{home_name(self.snap, responder)} is answering {home_name(self.snap, requester)}")
        meta = {
            "kind": "neighbor_ask", "home_id": responder, "from_home": home_name(self.snap, requester),
            "message": req.text,
            "label": label(t), "old_start": slot_to_time(a["from_slot"]), "new_start": slot_to_time(a["to_slot"]),
            "new_finish": slot_to_time(a["to_slot"] + t["duration_slots"]), "deadline": slot_to_time(t["deadline_slot"]),
            "on_time": on_time, "cost_delta": round(delta, 4), "cost_change": usd_change(delta),
        }
        try:
            out: NeighborReply = await self._turn(responder, neighbor_ask_user(meta), NeighborReply, tools=False)
        except AGENT_FAILURES as exc:
            log.warning("reply by %s failed: %s", responder, exc)
            msg = f"{home_name(self.snap, responder)} didn't answer in time. Keeping {current.name}."
            await self.em.send(sender=f"agent_{responder}", recipient=f"agent_{requester}", type="error", text=msg,
                               round=rnd, proposal_id=current.proposal_id, reply_to_event_id=req.event_id,
                               home_views={responder: msg, requester: msg})
            return False
        agree = bool(out.agree) and on_time  # a deadline is never relaxed, whatever the model says
        money = {usd(abs(delta))} if abs(delta) >= 0.005 else set()
        text = clean_model_text(out.public_message, self.snap, money)
        written = text is not None
        if text is None:
            text = (f"Yes, my {label(t)} can start at {slot_to_time(a['to_slot'])} and still finish on time."
                    if agree else f"Sorry, I can't move my {label(t)} this time.")
        await self.em.send(
            sender=f"agent_{responder}", recipient=f"agent_{requester}", type="review", text=text, round=rnd,
            proposal_id=current.proposal_id, reply_to_event_id=req.event_id, model_written=written,
            home_views=reply_views(self.snap, requester, a, agree, delta),
            data={"stance": "agree" if agree else "decline", "cost_delta_usd": round(delta, 4)},
        )
        return agree

    # ------------------------------------------------------------ result

    async def _info(self, text: str, rnd: int, plan: Plan | None) -> None:
        self.notes.append(text)
        await self.em.send(sender="coordinator", recipient="all_agents", type="info", text=text, round=rnd,
                           proposal_id=plan.proposal_id if plan else None, home_views={h: text for h in self.homes})

    def _result(self, outcome: str, message: str, plan: Plan | None, *, fallback: bool = False) -> dict[str, Any]:
        if self.model is None or fallback:
            source, ai_mode = "deterministic_fallback", "unavailable"
        elif self.model.impl == "stub":
            source, ai_mode = "stub", "live"
        else:
            source, ai_mode = "live", "live"
        ref = None
        if plan is not None:
            if self.plans and plan.proposal_id != self.plans[0].proposal_id:
                ref = {"name": self.plans[0].name, "metrics": self.plans[0].metrics}
            else:
                ref = {"name": getattr(self, "baseline_name", "everyone's preferred times"),
                       "metrics": getattr(self, "baseline_metrics", plan.metrics)}
        return {
            "outcome": outcome,
            "message": message,
            "proposal_id": plan.proposal_id if plan else None,
            "plan_name": plan.name if plan else None,
            "pins": plan.pins if plan else {},
            "home_explanations": dict(plan.views) if plan else {},
            "model_calls": self.budget.model_calls,
            "tool_calls": self.budget.tool_calls,
            "schedule": plan.schedule if plan else None,
            "metrics": plan.metrics if plan else None,
            "source": source,
            "ai_mode": ai_mode,
            "explanation": plan.summary if plan else message,
            "reasons": list(self.notes),
            "rounds": self.rounds or 1,
            "plans": [{"proposal_id": p.proposal_id, "name": p.name, "summary": p.summary, "pins": p.pins}
                      for p in self.plans],
            "commit_reference": ref,
            "model": self.model.model if self.model else None,
            "usage": self.budget.usage(),
        }
