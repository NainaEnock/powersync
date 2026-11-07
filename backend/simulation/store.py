"""Authoritative in-memory state: one process, one event loop, one state lock.

Owns revision/generation, events (emit), jobs, pending changes, commits, reset, and the
server-side privacy filter for ?home= views.
"""

from __future__ import annotations

import asyncio
import re
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .agent_seam import (
    AnnounceFn, CoordinateContext, CoordinateFn, CoordinateResult, InterpretContext, InterpretFn,
    InterpretResult, stub_interpret,
)
from .engine import (
    canonical_schedule, cheap_timer_schedule, compute_metrics, find_feasible_schedule,
    load_by_slot, preferred_schedule, validate_schedule, window_problem,
)
from .appliances import CATALOG, MAX_APPLIANCES_PER_HOME
from .scenario import build_snapshot, load_raw, scenario_tasks
from .schema import (
    EDITABLE_FIELDS, AgentEvent, Job, PendingChange, ProposedEdit, ProposedEdits, ScheduleEntry,
    Snapshot, Task,
)
from .timefmt import slot_to_time
from .wording import commit_text, home_name, noun, validation_text

MAX_EVENTS = 1000
PRIVATE_EVENT_TYPES = {"tool_call", "tool_result"}

FIELD_WORDS = {
    "deadline_slot": "finish time",
    "earliest_slot": "earliest start",
    "preferred_start_slot": "preferred start",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def env_float(name: str, default: float) -> float:
    try:
        v = os.getenv(name, "").strip()
        return float(v) if v else default
    except ValueError:
        return default


class StoreError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class Store:
    def __init__(self, interpret: InterpretFn, coordinate: CoordinateFn, agent_impl: dict[str, str],
                 openrouter_configured: bool = False, announce: Optional[AnnounceFn] = None):
        self.announce_fn = announce
        self.interpret_fn = interpret
        self.coordinate_fn = coordinate
        self.agent_impl = dict(agent_impl)
        self.openrouter_configured = openrouter_configured
        self.lock = asyncio.Lock()
        self.revision = 0
        self.generation = 0
        self.sequence = 0
        self._restore_scenario()

    # ------------------------------------------------------------ scenario & derived values

    def _restore_scenario(self) -> None:
        self.tasks: list[Task] = scenario_tasks()
        self.tariff_mode = "tou"
        self.requirements_version = 0
        self.coordinated: Optional[list[ScheduleEntry]] = None
        self.plan_counter = 0
        self.coordination: dict[str, Any] = {
            "status": "not_run", "explanation": None, "reasons": [], "job_id": None, "source": None,
            "proposal_id": None, "plan_name": None, "tariff_mode": None, "home_explanations": {},
        }
        self.events: list[AgentEvent] = []
        self.event_counter = 0
        self.pending: dict[str, PendingChange] = {}
        self.jobs: dict[str, Job] = {}
        self.job_tasks: dict[str, asyncio.Task] = {}
        self.request_index: dict[tuple[str, str], str] = {}
        self.activity: Optional[str] = None
        self.mutation_job_id: Optional[str] = None
        both_live = self.agent_impl.get("coordinate") == "live" and self.openrouter_configured
        self.ai_mode = "live" if both_live else "unavailable"
        self._recompute()

    def snapshot(self, tasks: Optional[list[Task]] = None, requirements_version: Optional[int] = None) -> Snapshot:
        return build_snapshot(
            tasks=tasks if tasks is not None else self.tasks, tariff_mode=self.tariff_mode,
            generation=self.generation,
            requirements_version=self.requirements_version if requirements_version is None else requirements_version,
            revision=self.revision,
        )

    def _recompute(self) -> None:
        snap = self.snapshot()
        flat = build_snapshot(tasks=self.tasks, tariff_mode="flat")
        self.baseline = preferred_schedule(snap)
        self.independent = cheap_timer_schedule(snap)
        scheds = {"baseline": self.baseline, "independent": self.independent, "coordinated": self.coordinated}
        self.metrics = {k: (compute_metrics(snap, v).model_dump() if v is not None else None) for k, v in scheds.items()}
        self.metrics_flat = {k: (compute_metrics(flat, v).model_dump() if v is not None else None) for k, v in scheds.items()}
        self.demand = {k: (load_by_slot(snap, v) if v is not None else None) for k, v in scheds.items()}

    # ------------------------------------------------------------ events

    def make_emit(self, job: Optional[Job], generation: int):
        def emit(ev: dict[str, Any]) -> str:
            if generation != self.generation:
                return ""  # late result from before a reset: drop it
            if "stage" in ev and "text" not in ev:
                self.activity = str(ev["stage"])[:200] if ev["stage"] else None
                if job is not None:
                    job.stage = self.activity
                    job.updated_at = now()
                return ""
            return self._store_event(ev, job.id if job else None)
        return emit

    def _store_event(self, ev: dict[str, Any], job_id: Optional[str]) -> str:
        self.event_counter += 1
        self.sequence += 1
        eid = f"evt-{self.generation}-{self.event_counter}"
        text = str(ev.get("text", ""))
        if len(text) > 800:
            text = text[:797] + "..."
        views = ev.get("home_views")
        if views is not None:
            views = {str(k): str(v)[:800] for k, v in dict(views).items()}
        data = ev.get("data")
        try:
            event = AgentEvent(
                id=eid, sequence=self.sequence, job_id=ev.get("job_id", job_id),
                sender=str(ev.get("sender", "backend")), recipient=str(ev.get("recipient", "all_agents")),
                type=ev.get("type", "info"), text=text, round=ev.get("round"),
                proposal_id=ev.get("proposal_id"), reply_to_event_id=ev.get("reply_to_event_id"),
                source=ev.get("source", "system_template"), home_views=views,
                data=dict(data) if isinstance(data, dict) else None,
                timestamp=now(), revision=self.revision,
            )
        except Exception as e:  # noqa: BLE001  bad event from an agent: record an error instead of crashing
            print(f"[powersync] rejected event: {e}", file=sys.stderr)
            event = AgentEvent(id=eid, sequence=self.sequence, job_id=job_id, sender="backend",
                               recipient="all_agents", type="error",
                               text="An agent sent a message the backend couldn't read.",
                               timestamp=now(), revision=self.revision)
        self.events.append(event)
        if len(self.events) > MAX_EVENTS:
            del self.events[: len(self.events) - MAX_EVENTS]
        return eid

    def emit_system(self, job: Optional[Job], **ev: Any) -> str:
        ev.setdefault("source", "system_template")
        return self._store_event(ev, job.id if job else None)

    # ------------------------------------------------------------ jobs

    def new_job(self, kind: str, home_id: Optional[str], request_id: Optional[str]) -> Job:
        t = now()
        job = Job(id=f"job-{self.generation}-{uuid.uuid4().hex[:8]}", kind=kind, home_id=home_id,
                  request_id=request_id, created_at=t, updated_at=t)
        self.jobs[job.id] = job
        if home_id and request_id:
            self.request_index[(home_id, request_id)] = job.id
        return job

    def finish(self, job: Job, status: str, outcome: str, message: str, error: Optional[str] = None, **extra: Any) -> None:
        job.status = status
        job.result = {"outcome": outcome, "message": message, **extra}
        job.error = error
        job.updated_at = now()

    def duplicate(self, home_id: str, request_id: str) -> Optional[Job]:
        jid = self.request_index.get((home_id, request_id))
        return self.jobs.get(jid) if jid else None

    def active_jobs(self) -> list[Job]:
        return [j for j in self.jobs.values() if j.status in ("queued", "running")]

    def _spawn(self, job: Job, coro) -> None:
        task = asyncio.create_task(self._guard(job, coro))
        self.job_tasks[job.id] = task

    async def _guard(self, job: Job, coro) -> None:
        gen = self.generation
        try:
            await coro
        except asyncio.CancelledError:
            self.finish(job, "failed", "cancelled", "The demo was reset.", error="RESET: The demo was reset.")
        except Exception as e:  # noqa: BLE001
            print(f"[powersync] job {job.id} crashed: {type(e).__name__}: {e}", file=sys.stderr)
            if gen == self.generation:
                self.finish(job, "failed", "error", "Something went wrong on the server.",
                            error=f"INTERNAL: {type(e).__name__}")
        finally:
            self.job_tasks.pop(job.id, None)
            if self.mutation_job_id == job.id:
                self.mutation_job_id = None
                if gen == self.generation:
                    self.activity = None

    # ------------------------------------------------------------ message (interpret)

    def submit_message(self, home_id: str, text: str, request_id: str) -> Job:
        job = self.new_job("message", home_id, request_id)
        self._spawn(job, self._run_message(job, home_id, text, request_id))
        return job

    async def _run_message(self, job: Job, home_id: str, text: str, request_id: str) -> None:
        gen = self.generation
        emit = self.make_emit(job, gen)
        job.status, job.stage, job.updated_at = "running", "Understanding your request", now()
        req_eid = self.emit_system(job, sender=f"resident_{home_id}", recipient=f"agent_{home_id}",
                                   type="request", text=text, data={"origin": "resident"})
        ctx = InterpretContext(job_id=job.id, home_id=home_id, text=text, request_id=request_id,
                               request_event_id=req_eid, snapshot=self.snapshot())
        timeout = env_float("POWERSYNC_AGENT_TIMEOUT_S", 30.0)
        result: Optional[InterpretResult] = None
        try:
            raw = await asyncio.wait_for(self.interpret_fn(ctx, emit), timeout=timeout)
            result = raw if isinstance(raw, InterpretResult) else InterpretResult.model_validate(raw)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001  timeout, bad output, model error -> backup reader
            if gen != self.generation:
                return
            reason = "didn't answer in time" if isinstance(e, asyncio.TimeoutError) else "ran into a problem"
            print(f"[powersync] interpret failed: {type(e).__name__}: {e}", file=sys.stderr)
            if self.interpret_fn is not stub_interpret:
                self.emit_system(job, sender="backend", recipient=f"resident_{home_id}", type="error",
                                 text=f"{home_name(ctx.snapshot, home_id)}'s agent {reason}, so the simple backup reader handled this request.",
                                 reply_to_event_id=req_eid)
            result = await stub_interpret(ctx, emit)
        if gen != self.generation:
            return
        self._finish_interpretation(job, home_id, request_id, req_eid, result)

    def _finish_interpretation(self, job: Job, home_id: str, request_id: str, req_eid: str,
                               result: InterpretResult) -> None:
        snap = self.snapshot()
        tasks = snap.task_map()
        agent_source = result.message_source

        def reply(text: str, typ: str = "info") -> None:
            self.emit_system(job, sender=f"agent_{home_id}", recipient=f"resident_{home_id}", type=typ,
                             text=text, reply_to_event_id=req_eid, source=agent_source if typ == "info" else "system_template")

        if result.outcome != "edits" or not result.edits:
            msg = result.message or ("That can't be done: " + " ".join(result.infeasible_reasons)
                                     if result.infeasible_reasons else "There's nothing to change in your plan.")
            reply(msg)
            outcome = result.outcome if result.outcome in ("infeasible", "needs_clarification") else "no_change"
            self.finish(job, "completed", outcome, msg, infeasible_reasons=result.infeasible_reasons)
            return

        # Validate model output against canonical tasks. Another home's task or unknown task -> reject.
        problems = []
        for e in result.edits:
            t = tasks.get(e.task_id)
            if t is None:
                problems.append(f"unknown appliance '{e.task_id}'")
            elif t.home_id != home_id:
                problems.append("an appliance that belongs to another home")
            elif e.field not in EDITABLE_FIELDS:
                problems.append(f"a field that can't be changed ({e.field})")
            elif not 0 <= e.new_value <= snap.slots:
                problems.append("a time outside tonight's planning window")
        if problems:
            msg = "Your request couldn't be applied safely: it referred to " + "; ".join(sorted(set(problems))) + "."
            self.emit_system(job, sender="validator", recipient=f"resident_{home_id}", type="error", text=msg,
                             reply_to_event_id=req_eid)
            self.finish(job, "failed", "error", msg, error="BAD_MODEL_OUTPUT: " + "; ".join(problems))
            return

        edits = []
        new_tasks = {t.id: t for t in self.tasks}
        for e in result.edits:
            t = new_tasks[e.task_id]
            old = getattr(t, e.field)
            edits.append(ProposedEdit(task_id=t.id, field=e.field, old_value=old, new_value=e.new_value,
                                      old_time=slot_to_time(old), new_time=slot_to_time(e.new_value)))
            new_tasks[t.id] = t.model_copy(update={e.field: e.new_value})
        edits = [x for x in edits if x.old_value != x.new_value]
        if not edits:
            msg = "Your plan already works that way, so nothing needs to change."
            reply(msg)
            self.finish(job, "completed", "no_change", msg)
            return

        edited_snap = self.snapshot(tasks=list(new_tasks.values()))
        reasons = [r for x in edits if (r := window_problem(new_tasks[x.task_id], edited_snap))]
        if not reasons:
            plan = find_feasible_schedule(edited_snap)
            if not plan.ok:
                reasons = plan.reasons
        feasible = not reasons

        def edit_phrase(x: ProposedEdit) -> str:
            return f"your {noun(tasks[x.task_id])}'s {FIELD_WORDS[x.field]} from {x.old_time} to {x.new_time}"
        # The engine's verdict decides the wording. The interpreter's text is used only when it agrees,
        # so a resident never sees "I can't ..." next to a Confirm button (or "Change ...?" on a no).
        agrees = result.claimed_feasible is None or result.claimed_feasible == feasible
        explanation = (result.explanation.strip() if agrees else "") or (
            "Change " + " and ".join(edit_phrase(x) for x in edits) + "?" if feasible
            else "That change can't work. " + " ".join(reasons))
        for p in self.pending.values():  # one open change per home: a new one supersedes the old
            if p.home_id == home_id and p.status == "pending":
                p.status = "stale"
        pc = PendingChange(
            id=f"pc-{self.generation}-{uuid.uuid4().hex[:8]}", home_id=home_id,
            proposed_edits=ProposedEdits(edits=edits), explanation=explanation[:800],
            prepared_revision=self.revision, request_id=request_id, job_id=job.id, feasible=feasible,
            infeasible_reasons=reasons, status="pending", created_at=now(),
        )
        self.pending[pc.id] = pc
        if feasible:
            reply(explanation if "confirm" in explanation.lower()
                  else f"{explanation} Confirm on your phone to replan with the neighbors.")
            job.status, job.stage = "awaiting_confirmation", "Waiting for you to confirm"
            job.result = {"outcome": "proposed_change", "message": explanation, "pending_change_id": pc.id}
            job.updated_at = now()
        else:
            reply(explanation)
            self.finish(job, "completed", "infeasible", explanation, pending_change_id=pc.id,
                        infeasible_reasons=reasons)

    # ------------------------------------------------------------ actions

    def reject_change(self, pc: PendingChange, request_id: str) -> Job:
        job = self.new_job("action", pc.home_id, request_id)
        pc.status = "rejected"
        self.revision += 1
        self._close_message_job(pc, "rejected")
        self.finish(job, "completed", "rejected", "Change dismissed. Your plan is unchanged.",
                    pending_change_id=pc.id, revision=self.revision)
        return job

    def _close_message_job(self, pc: PendingChange, outcome: str) -> None:
        j = self.jobs.get(pc.job_id)
        if j and j.status == "awaiting_confirmation":
            self.finish(j, "completed", outcome, f"Change {outcome}.", pending_change_id=pc.id)

    def check_confirmable(self, pc: PendingChange) -> None:
        if pc.status != "pending":
            raise StoreError(409, "STALE_REVISION", "That change is no longer waiting for confirmation.")
        if not pc.feasible:
            raise StoreError(400, "BAD_REQUEST", "That change can't be applied. Dismiss it instead.")
        current = {t.id: t for t in self.tasks}
        for e in pc.proposed_edits.edits:
            if getattr(current[e.task_id], e.field) != e.old_value:
                pc.status = "stale"
                raise StoreError(409, "STALE_REVISION", "Your plan changed since this was prepared. Please send the request again.")

    def submit_confirm(self, pc: PendingChange, request_id: str) -> Job:
        job = self.new_job("action", pc.home_id, request_id)
        self.mutation_job_id = job.id
        self._spawn(job, self._run_replan(job, pc))
        return job

    def submit_coordinate(self, request_id: Optional[str]) -> Job:
        job = self.new_job("coordinate", None, None)
        job.request_id = request_id
        self.mutation_job_id = job.id
        self._spawn(job, self._run_replan(job, None))
        return job

    # ------------------------------------------------------------ replan + commit (one job, one revision bump)

    async def _run_replan(self, job: Job, pc: Optional[PendingChange]) -> None:
        gen = self.generation
        emit = self.make_emit(job, gen)
        job.status, job.updated_at = "running", now()
        emit({"stage": "Planning the neighborhood"})

        new_tasks = list(self.tasks)
        rv = self.requirements_version
        trigger = None
        trigger_change = None
        if pc is not None:
            by_id = {t.id: t for t in new_tasks}
            for e in pc.proposed_edits.edits:
                by_id[e.task_id] = by_id[e.task_id].model_copy(update={e.field: e.new_value})
            new_tasks = [by_id[t.id] for t in self.tasks]
            rv += 1
            snap0 = self.snapshot()
            hn = home_name(snap0, pc.home_id)
            parts = [f"{noun(snap0.task_map()[e.task_id])}'s {FIELD_WORDS[e.field]} to {e.new_time}"
                     for e in pc.proposed_edits.edits]
            trigger = f"{hn}'s resident changed their " + " and ".join(parts) + "."
            e0 = pc.proposed_edits.edits[0]
            trigger_change = {"home_id": pc.home_id, "task_id": e0.task_id, "field": e0.field,
                              "old_value": e0.old_value, "new_value": e0.new_value,
                              "old_time": e0.old_time, "new_time": e0.new_time,
                              "edits": [x.model_dump() for x in pc.proposed_edits.edits]}
            views = {h.id: (f"You changed your " + " and ".join(parts) + ". Replanning with the neighbors."
                            if h.id == pc.home_id else f"{hn}'s resident changed a requirement. Replanning the street.")
                     for h in snap0.homes}
            self.emit_system(job, sender="backend", recipient="all_agents", type="info",
                             text=trigger + " Replanning the street.", home_views=views)

        snap = self.snapshot(tasks=new_tasks, requirements_version=rv)
        safe = find_feasible_schedule(snap)
        if not safe.ok:
            msg = "No safe plan exists with this change: " + " ".join(safe.reasons)
            if pc is not None:
                pc.status = "stale"
                self._close_message_job(pc, "infeasible")
            self.emit_system(job, sender="validator", recipient="all_agents", type="error", text=msg[:800],
                             home_views={h.id: msg[:800] for h in snap.homes} if pc is None else
                             {pc.home_id: msg[:800]})
            self.finish(job, "completed", "infeasible", msg, reasons=safe.reasons)
            return

        ctx = CoordinateContext(job_id=job.id, snapshot=snap, trigger=trigger,
                                trigger_home_id=pc.home_id if pc else None, trigger_change=trigger_change,
                                previous_schedule=self.coordinated, next_plan_number=self.plan_counter + 1)
        timeout = env_float("POWERSYNC_AGENT_TIMEOUT_S", 60.0)
        source, failure = "stub", None
        result: Optional[CoordinateResult] = None
        try:
            raw = await asyncio.wait_for(self.coordinate_fn(ctx, emit), timeout=timeout)
            result = raw if isinstance(raw, CoordinateResult) else CoordinateResult.model_validate(raw)
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            failure = "The household agents didn't answer in time. Using the safe plan."
        except Exception as e:  # noqa: BLE001
            print(f"[powersync] coordinate failed: {type(e).__name__}: {e}", file=sys.stderr)
            failure = "The household agents ran into a problem. Using the safe plan."
        if gen != self.generation:
            return

        if result is not None:
            findings = validate_schedule(snap, result.schedule)
            if findings:
                failure = "The agents' plan didn't pass the safety check (" + findings[0] + "). Using the safe plan."
                result = None
        if result is not None:
            schedule = canonical_schedule(snap, result.schedule)
            source = result.source
            plan_name = result.plan_name or f"Plan {self.plan_counter + 1}"
            if source == "deterministic_fallback":
                self.ai_mode = "unavailable"
            proposal_id = result.proposal_id
            explanation, home_expl = result.explanation, result.home_explanations
            if result.source == "live":
                self.ai_mode = "live"
        else:
            schedule = safe.schedule
            source = "deterministic_fallback"
            plan_name = f"Plan {self.plan_counter + 1}"
            proposal_id = f"P-{self.plan_counter + 1}"
            explanation = "Engine plan used because the household agents were unavailable."
            home_expl = {}
            self.ai_mode = "unavailable"
            self.emit_system(job, sender="backend", recipient="all_agents", type="error", text=failure,
                             home_views={h.id: failure for h in snap.homes}, proposal_id=proposal_id)

        async with self.lock:
            if gen != self.generation or self.requirements_version != (rv - (1 if pc else 0)):
                self.finish(job, "failed", "stale", "Requirements changed while planning. Please try again.",
                            error="STALE_REVISION: requirements changed during planning")
                return
            v_text, v_views = validation_text(snap, plan_name, schedule)
            self.emit_system(job, sender="validator", recipient="all_agents", type="validation", text=v_text,
                             home_views=v_views, proposal_id=proposal_id, data={"valid": True})
            previous = self.coordinated
            baseline_after = preferred_schedule(snap)
            self.tasks = new_tasks
            self.requirements_version = rv
            self.coordinated = schedule
            # Skip past every plan number this job used (it may propose Plan 1 and commit Plan 2),
            # so the next replan is "Plan 3", never "Plan 2" again.
            used = [proposal_id] + [p.get("proposal_id") for p in ((result.raw or {}).get("plans") or [])
                                    if isinstance(p, dict)] if result is not None else [proposal_id]
            nums = [int(m.group(1)) for pid in used if isinstance(pid, str) and (m := re.match(r"P-(\d+)$", pid))]
            self.plan_counter = max([self.plan_counter + 1, *nums])
            self.coordination = {
                "status": "committed", "explanation": explanation, "reasons": [], "job_id": job.id,
                "source": source, "proposal_id": proposal_id, "plan_name": plan_name,
                "tariff_mode": self.tariff_mode, "home_explanations": dict(home_expl),
            }
            if pc is not None:
                pc.status = "confirmed"
                self._close_message_job(pc, "applied")
                self._stale_conflicting_pending(pc)
            self.revision += 1
            self._recompute()
            announced = False
            if self.announce_fn is not None and result is not None:
                try:
                    await asyncio.wait_for(self.announce_fn(snap, result, emit, job.id),
                                           timeout=env_float("POWERSYNC_ANNOUNCE_TIMEOUT_S", 10.0))
                    announced = True
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001  fall back to D's template
                    print(f"[powersync] announce_commit failed: {type(e).__name__}: {e}", file=sys.stderr)
            if not announced:
                c_text, c_views = commit_text(snap, plan_name, schedule, previous, baseline_after)
                self.emit_system(job, sender="coordinator", recipient="all_agents", type="commit", text=c_text,
                                 home_views=c_views, proposal_id=proposal_id, data={"source": source})
            self.activity = None
            outcome = "applied" if pc is not None else "committed"
            self.finish(job, "completed", outcome, f"{plan_name} committed.", revision=self.revision,
                        proposal_id=proposal_id, source=source,
                        pending_change_id=pc.id if pc else None)

    def _stale_conflicting_pending(self, applied: PendingChange) -> None:
        current = {t.id: t for t in self.tasks}
        for p in self.pending.values():
            if p.status != "pending" or p.id == applied.id:
                continue
            if any(getattr(current[e.task_id], e.field) != e.old_value for e in p.proposed_edits.edits):
                p.status = "stale"

    # ------------------------------------------------------------ appliances (residents add / remove)

    def _appliances_changed(self, home_id: str, own_text: str, verb: str) -> None:
        """Requirements changed: the committed plan no longer covers every appliance, so drop it and say so."""
        self.requirements_version += 1
        self.revision += 1
        self.coordinated = None
        self.coordination = {
            "status": "not_run", "explanation": None,
            "reasons": ["Appliances changed. Coordinate again to plan the new set."],
            "job_id": None, "source": None, "proposal_id": None, "plan_name": None,
            "tariff_mode": None, "home_explanations": {},
        }
        self._recompute()
        name = home_name(self.snapshot(), home_id)
        other = f"{name} {verb} an appliance. The street will replan on the next coordination."
        self.emit_system(None, sender="backend", recipient="all_agents", type="info",
                         text=f"{name} {own_text[4:] if own_text.startswith('You ') else own_text}",
                         home_views={h: (own_text if h == home_id else other) for h in ("A", "B", "C")})

    def add_appliance(self, home_id: str, kind: str, deadline_slot: Optional[int]) -> Task:
        spec = CATALOG.get(kind)
        if spec is None:
            raise StoreError(400, "BAD_REQUEST", f"Unknown appliance '{kind}'. Choose one from the list.")
        own = [t for t in self.tasks if t.home_id == home_id]
        # One of each per home. Matching by name covers the scenario's own appliances too (Home B's dryer),
        # and a double tap on Add can't create a second copy.
        if any(t.name.lower() == spec["name"].lower() for t in own):
            raise StoreError(409, "ALREADY_ADDED",
                             f"Your home already has {spec['label']}. To change when it's done, ask your agent.")
        if len(own) >= MAX_APPLIANCES_PER_HOME:
            raise StoreError(400, "BAD_REQUEST", f"A home can schedule up to {MAX_APPLIANCES_PER_HOME} appliances.")
        dur = spec["duration_slots"]
        deadline = spec["deadline_slot"] if deadline_slot is None else deadline_slot
        if deadline < dur or deadline > 96:
            raise StoreError(400, "BAD_REQUEST",
                             f"{spec['name']} takes {dur * 15 // 60} h {dur * 15 % 60} min, so it can't finish by "
                             f"{slot_to_time(deadline)} when planning starts at 6:00 PM.".replace(" 0 min", ""))
        base = f"{home_id.lower()}_{kind}"
        ids = {t.id for t in self.tasks}
        tid, n = base, 2
        while tid in ids:
            tid, n = f"{base}{n}", n + 1
        pref = max(0, min(spec["preferred_start_slot"], deadline - dur))
        task = Task(id=tid, home_id=home_id, name=spec["name"], power_kw=spec["power_kw"], duration_slots=dur,
                    earliest_slot=0, deadline_slot=deadline, preferred_start_slot=pref, interruptible=False)
        # Refuse an appliance the street can't fit under its limit in time, before anything changes,
        # rather than accepting it and failing at the next coordination.
        plan = find_feasible_schedule(self.snapshot(tasks=[*self.tasks, task]))
        if not plan.ok:
            why = plan.reasons[0] if plan.reasons else "every appliance can't fit under the limit in time"
            raise StoreError(409, "WONT_FIT",
                             f"The street can't fit {spec['label']} done by {slot_to_time(deadline)}: {why} "
                             "Try a later finish time.")
        self.tasks = [*self.tasks, task]
        self._appliances_changed(
            home_id, f"You added {spec['label']} ({spec['power_kw']:g} kW, done by {slot_to_time(deadline)}).",
            "added")
        return task

    def remove_appliance(self, home_id: str, task_id: str) -> None:
        task = next((t for t in self.tasks if t.id == task_id), None)
        if task is None:
            raise StoreError(404, "NOT_FOUND", "That appliance wasn't found. The demo may have been reset.")
        if task.home_id != home_id:
            raise StoreError(403, "FORBIDDEN", "That appliance belongs to another home.")
        if sum(1 for t in self.tasks if t.home_id == home_id) <= 1:
            raise StoreError(400, "BAD_REQUEST", "Keep at least one appliance in your home's plan.")
        self.tasks = [t for t in self.tasks if t.id != task_id]
        for p in self.pending.values():  # a waiting change to the removed appliance can't apply anymore
            if p.status == "pending" and any(e.task_id == task_id for e in p.proposed_edits.edits):
                p.status = "stale"
        self._appliances_changed(home_id, f"You removed the {noun(task)}.", "removed")

    # ------------------------------------------------------------ tariff & reset

    def set_tariff(self, mode: str) -> None:
        if mode == self.tariff_mode:
            return
        self.tariff_mode = mode
        if self.coordinated is not None:
            self.coordination["status"] = "stale_tariff"
            self.coordination["reasons"] = ["Plan priced under the previous tariff. Coordinate again."]
        self.revision += 1
        self._recompute()
        label = "a flat rate (the same price at every hour)" if mode == "flat" else "the time-of-use rates"
        text = f"Prices switched to {label}."
        self.emit_system(None, sender="backend", recipient="all_agents", type="info", text=text,
                         home_views={h: text for h in ("A", "B", "C")})

    def reset(self) -> None:
        for t in list(self.job_tasks.values()):
            t.cancel()
        self.job_tasks.clear()
        self.generation += 1
        self.revision += 1
        self._restore_scenario()

    # ------------------------------------------------------------ views

    def _base_state(self) -> dict[str, Any]:
        snap = self.snapshot()
        raw = load_raw()
        running = [j for j in self.jobs.values() if j.status in ("queued", "running")]
        return {
            "revision": self.revision, "generation": self.generation,
            "requirements_version": self.requirements_version, "scenario_id": raw["scenario_id"],
            "horizon_start": raw["horizon_start"], "slot_minutes": raw["slot_minutes"],
            "capacity_kw": raw["capacity_kw"], "activity": self.activity,
            "tariff_mode": self.tariff_mode, "tariff_label": snap.tariff_label,
            "homes": [h.model_dump() for h in snap.homes],
            "tasks": [t.model_dump() for t in self.tasks],
            "tariff_usd_per_kwh": snap.tariff_usd_per_kwh,
            "background_kw_by_home": dict(snap.background_kw_by_home),
            "baseline_schedule": [e.model_dump() for e in self.baseline],
            "independent_schedule": [e.model_dump() for e in self.independent],
            "coordinated_schedule": [e.model_dump() for e in self.coordinated] if self.coordinated is not None else None,
            "metrics": self.metrics, "metrics_flat_rate": self.metrics_flat, "demand_kw": self.demand,
            "coordination": dict(self.coordination),
            "events": [], "events_hidden": False, "pending_changes": [],
            "job_status": ("running" if running else "idle"),
            "data_mode": "synthetic", "ai_mode": self.ai_mode, "agent_impl": dict(self.agent_impl),
            "view": "dashboard", "view_home_id": None,
        }

    def dashboard_view(self, admin: bool) -> dict[str, Any]:
        s = self._base_state()
        if admin:
            s["events"] = [self._public_event(e) for e in self.events]
            s["pending_changes"] = [p.model_dump() for p in self.pending.values() if p.status == "pending"]
        else:
            s["events_hidden"] = True
        return s

    @staticmethod
    def _public_event(e: AgentEvent) -> dict[str, Any]:
        d = e.model_dump()
        d.pop("home_views", None)
        return d

    def home_view(self, home_id: str) -> dict[str, Any]:
        """Only this home's tasks, schedule, metrics, pending changes, and events (PRD §11.3)."""
        s = self._base_state()
        s["view"], s["view_home_id"] = "home", home_id
        own = lambda rows: [r for r in rows if r.get("home_id") == home_id]  # noqa: E731
        s["homes"] = [h if h["id"] == home_id else {**h, "preferences": {}} for h in s["homes"]]
        s["tasks"] = own(s["tasks"])
        s["baseline_schedule"] = own(s["baseline_schedule"])
        s["independent_schedule"] = own(s["independent_schedule"])
        if s["coordinated_schedule"] is not None:
            s["coordinated_schedule"] = own(s["coordinated_schedule"])
        s["background_kw_by_home"] = {home_id: s["background_kw_by_home"].get(home_id)}
        for key in ("metrics", "metrics_flat_rate"):
            s[key] = {k: (self._home_metrics(m, home_id) if m else None) for k, m in s[key].items()}
        c = s["coordination"]
        expl = c.get("home_explanations", {}).get(home_id)
        s["coordination"] = {**c, "explanation": expl or ("The neighborhood plan is set." if c["status"] in ("committed", "stale_tariff") else None),
                             "home_explanations": {}}
        if s["activity"]:
            s["activity"] = "Planning with the neighbors…"
        s["pending_changes"] = [p.model_dump() for p in self.pending.values()
                                if p.home_id == home_id and p.status == "pending"]
        s["events"] = [ev for e in self.events if (ev := self._home_event(e, home_id)) is not None]
        return s

    @staticmethod
    def _home_metrics(m: dict[str, Any], home_id: str) -> dict[str, Any]:
        # Street totals (aggregate demand, peak, violations) stay; other homes' per-home rows go.
        return {**m, "per_home": {home_id: m["per_home"][home_id]}}

    @staticmethod
    def _home_event(e: AgentEvent, home_id: str) -> Optional[dict[str, Any]]:
        if e.type in PRIVATE_EVENT_TYPES:
            return None
        # With home_views: show only this home's wording, or nothing.
        # Without home_views: show only events this home sent or received.
        if e.home_views is not None:
            text = e.home_views.get(home_id)
            if text is None:
                return None
        else:
            mine = {f"resident_{home_id}", f"agent_{home_id}"}
            if e.sender not in mine and e.recipient not in mine:
                return None
            text = e.text
        d = e.model_dump()
        d.pop("home_views", None)
        d["data"] = None
        d["text"] = text
        return d
