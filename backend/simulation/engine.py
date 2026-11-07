"""Deterministic engine: metrics, the three schedules, the scheduler, the validator.

Pure functions over a Snapshot. No state, no I/O, no AI. C's MCP tools wrap these.
Every number shown anywhere comes from here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from .schema import HomeMetrics, Metrics, ScheduleEntry, Snapshot, Task
from .timefmt import hours_text, slot_to_time

SLOT_HOURS = 0.25
DEFAULT_NODE_BUDGET = 50_000


def _r(x: float, nd: int = 4) -> float:
    return round(x + 0.0, nd)


# ---------------------------------------------------------------- loads & metrics

def entry_for(task: Task, start_slot: int) -> ScheduleEntry:
    """Power and duration are always copied from the canonical task. Only start_slot is a decision."""
    return ScheduleEntry(
        task_id=task.id, home_id=task.home_id, start_slot=start_slot,
        duration_slots=task.duration_slots, power_kw=task.power_kw,
    )


def load_by_slot(snap: Snapshot, schedule: Iterable[ScheduleEntry], home_id: Optional[str] = None) -> list[float]:
    n = snap.slots
    bg = sum(kw for h, kw in snap.background_kw_by_home.items() if home_id is None or h == home_id)
    load = [bg] * n
    for e in schedule:
        if home_id is not None and e.home_id != home_id:
            continue
        for s in range(max(0, e.start_slot), min(n, e.start_slot + e.duration_slots)):
            load[s] += e.power_kw
    return [_r(x, 6) for x in load]


def _energy_cost_peak(load: list[float], prices: list[float]) -> tuple[float, float, float]:
    energy = sum(x * SLOT_HOURS for x in load)
    cost = sum(x * SLOT_HOURS * p for x, p in zip(load, prices))
    return energy, cost, max(load) if load else 0.0


def _task_ok(task: Task, start: int, horizon: int) -> bool:
    return start >= task.earliest_slot and start + task.duration_slots <= task.deadline_slot and start + task.duration_slots <= horizon


def compute_metrics(snap: Snapshot, schedule: list[ScheduleEntry], prices: Optional[list[float]] = None) -> Metrics:
    prices = prices if prices is not None else snap.tariff_usd_per_kwh
    total = load_by_slot(snap, schedule)
    energy, cost, peak = _energy_cost_peak(total, prices)
    tasks = snap.task_map()
    starts = {e.task_id: e.start_slot for e in schedule if e.task_id in tasks}
    completed = sum(1 for tid, s in starts.items() if _task_ok(tasks[tid], s, snap.slots))
    missed = sum(1 for tid, s in starts.items() if s + tasks[tid].duration_slots > tasks[tid].deadline_slot)
    missed += sum(1 for tid in tasks if tid not in starts)
    limit = snap.capacity_kw + snap.capacity_tolerance_kw
    per_home = {}
    for h in snap.homes:
        e, c, p = _energy_cost_peak(load_by_slot(snap, schedule, h.id), prices)
        per_home[h.id] = HomeMetrics(energy_kwh=_r(e), variable_cost_usd=_r(c), peak_kw=_r(p))
    return Metrics(
        energy_kwh=_r(energy), variable_cost_usd=_r(cost), peak_kw=_r(peak),
        missed_deadlines=missed,
        capacity_violations=sum(1 for x in total if x > limit),
        tasks_completed=completed, tasks_total=len(tasks), per_home=per_home,
    )


# ---------------------------------------------------------------- simple schedules

def preferred_schedule(snap: Snapshot) -> list[ScheduleEntry]:
    """Everyone runs at their preferred time (the 'preferred times' baseline)."""
    return [entry_for(t, t.preferred_start_slot) for t in snap.tasks]


def _task_cost(t: Task, start: int, prices: list[float]) -> float:
    return round(t.power_kw * SLOT_HOURS * sum(prices[start:start + t.duration_slots]), 9)


def _starts(t: Task, horizon: int) -> range:
    return range(t.earliest_slot, min(t.deadline_slot, horizon) - t.duration_slots + 1)


def cheap_timer_schedule(snap: Snapshot) -> list[ScheduleEntry]:
    """Each home picks its own cheapest start alone, ignoring the shared limit.

    Ties go to the start closest to the preferred time. If a task has no valid start,
    it keeps its preferred start (and shows up as a missed deadline).
    """
    out = []
    for t in snap.tasks:
        starts = list(_starts(t, snap.slots))
        if not starts:
            out.append(entry_for(t, t.preferred_start_slot))
            continue
        best = min(starts, key=lambda s: (_task_cost(t, s, snap.tariff_usd_per_kwh), abs(s - t.preferred_start_slot), s))
        out.append(entry_for(t, best))
    return out


# ---------------------------------------------------------------- scheduler

@dataclass
class ScheduleResult:
    ok: bool
    schedule: list[ScheduleEntry] = field(default_factory=list)
    status: str = "found"  # found | impossible | budget_exhausted | bad_input
    reasons: list[str] = field(default_factory=list)
    nodes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "status": self.status, "reasons": self.reasons, "nodes": self.nodes,
            "schedule": [e.model_dump() for e in self.schedule],
        }


def _task_label(t: Task, snap: Snapshot) -> str:
    home = next((h.name for h in snap.homes if h.id == t.home_id), f"Home {t.home_id}")
    name = "car " + t.name[3:] if t.name.lower().startswith("ev ") else t.name.lower()
    return f"{home}'s {name}"


def window_problem(t: Task, snap: Snapshot) -> Optional[str]:
    """Plain-English reason a task can't fit its own window, or None."""
    label = _task_label(t, snap)
    if t.deadline_slot - t.earliest_slot < t.duration_slots or not list(_starts(t, snap.slots)):
        if t.earliest_slot == 0:
            return (f"{label} needs {hours_text(t.duration_slots)}, so it can't finish by "
                    f"{slot_to_time(t.deadline_slot)} when planning starts at {slot_to_time(0)}.")
        return (f"{label} needs {hours_text(t.duration_slots)}, which doesn't fit between "
                f"{slot_to_time(t.earliest_slot)} and {slot_to_time(t.deadline_slot)}.")
    bg = snap.background_kw_by_home.get(t.home_id, 0.0)
    if sum(snap.background_kw_by_home.values()) + t.power_kw > snap.capacity_kw + snap.capacity_tolerance_kw:
        return f"{label} uses {t.power_kw:g} kW, which can't fit under the {snap.capacity_kw:g} kW street limit at any time."
    del bg
    return None


def find_feasible_schedule(
    snap: Snapshot,
    pins: Optional[dict[str, int]] = None,
    preferred_overrides: Optional[dict[str, int]] = None,
    node_budget: int = DEFAULT_NODE_BUDGET,
) -> ScheduleResult:
    """Bounded backtracking heuristic (PRD §15.1). Not a claim of global optimality.

    Order: least slack, then higher power, then stable ID.
    Rank starts: cost, then resulting street peak, then distance from preferred start.
    pins: fix a task's start (an agreed timing change). preferred_overrides: soft change to preferred start.
    """
    pins = dict(pins or {})
    overrides = dict(preferred_overrides or {})
    tasks = snap.task_map()
    prices = snap.tariff_usd_per_kwh
    horizon = snap.slots
    limit = snap.capacity_kw + snap.capacity_tolerance_kw

    if len(prices) != horizon:
        return ScheduleResult(False, status="bad_input", reasons=["The price list doesn't cover the whole evening."])
    for tid in list(pins) + list(overrides):
        if tid not in tasks:
            return ScheduleResult(False, status="bad_input", reasons=[f"Unknown appliance '{tid}'."])

    reasons = [r for t in snap.tasks if (r := window_problem(t, snap))]
    if reasons:
        return ScheduleResult(False, status="impossible", reasons=reasons)

    load = load_by_slot(snap, [])
    placed: dict[str, int] = {}

    def fits(t: Task, s: int) -> bool:
        return all(load[i] + t.power_kw <= limit for i in range(s, s + t.duration_slots))

    def add(t: Task, s: int, sign: float) -> None:
        for i in range(s, s + t.duration_slots):
            load[i] = round(load[i] + sign * t.power_kw, 6)

    for tid, s in pins.items():
        t = tasks[tid]
        if not _task_ok(t, s, horizon):
            return ScheduleResult(False, status="impossible", reasons=[
                f"Starting {_task_label(t, snap)} at {slot_to_time(s)} would miss its {slot_to_time(t.deadline_slot)} deadline."])
        if not fits(t, s):
            return ScheduleResult(False, status="impossible", reasons=[
                f"Starting {_task_label(t, snap)} at {slot_to_time(s)} would put the street over {snap.capacity_kw:g} kW."])
        add(t, s, 1)
        placed[tid] = s

    order = sorted(
        (t for t in snap.tasks if t.id not in pins),
        key=lambda t: (t.deadline_slot - t.earliest_slot - t.duration_slots, -t.power_kw, t.id),
    )
    nodes = 0
    exhausted = False

    def ranked(t: Task) -> list[int]:
        pref = overrides.get(t.id, t.preferred_start_slot)
        cur_peak = max(load)
        opts = []
        for s in _starts(t, horizon):
            if not fits(t, s):
                continue
            peak = max(cur_peak, max(load[i] + t.power_kw for i in range(s, s + t.duration_slots)))
            opts.append((_task_cost(t, s, prices), round(peak, 6), abs(s - pref), s))
        opts.sort()
        return [o[3] for o in opts]

    def dfs(i: int) -> bool:
        nonlocal nodes, exhausted
        if i == len(order):
            return True
        t = order[i]
        for s in ranked(t):
            nodes += 1
            if nodes > node_budget:
                exhausted = True
                return False
            add(t, s, 1)
            placed[t.id] = s
            if dfs(i + 1):
                return True
            add(t, s, -1)
            del placed[t.id]
            if exhausted:
                return False
        return False

    if not dfs(0):
        if exhausted:
            return ScheduleResult(False, status="budget_exhausted", nodes=nodes,
                                  reasons=["No plan was found within the search budget. One may still exist."])
        return ScheduleResult(False, status="impossible", nodes=nodes,
                              reasons=[f"There's no way to fit every appliance under the {snap.capacity_kw:g} kW street limit with these deadlines."])

    schedule = [entry_for(t, placed[t.id]) for t in snap.tasks]
    findings = validate_schedule(snap, [e.model_dump() for e in schedule])
    if findings:  # re-evaluate the whole horizon before returning
        return ScheduleResult(False, status="impossible", reasons=findings, nodes=nodes)
    return ScheduleResult(True, schedule=schedule, nodes=nodes)


# ---------------------------------------------------------------- validator

def validate_schedule(
    snap: Snapshot,
    raw_entries: list[dict[str, Any]],
    *,
    expected_generation: Optional[int] = None,
    expected_requirements_version: Optional[int] = None,
) -> list[str]:
    """Return a list of findings (empty = valid). Accepts raw dicts so bad model output is caught here.

    Checks: every task exactly once, no unknown IDs, correct home, integer starts, power and
    duration match the canonical task, window and horizon, capacity at every slot,
    and the candidate's generation / requirements version.
    """
    findings: list[str] = []
    if expected_generation is not None and expected_generation != snap.generation:
        findings.append("This plan was made before the demo was reset.")
    if expected_requirements_version is not None and expected_requirements_version != snap.requirements_version:
        findings.append("This plan was made for older requirements.")

    tasks = snap.task_map()
    seen: dict[str, int] = {}
    entries: list[ScheduleEntry] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            findings.append("A schedule entry isn't an object.")
            continue
        tid = raw.get("task_id")
        if tid not in tasks:
            findings.append(f"Unknown appliance '{tid}'.")
            continue
        t = tasks[tid]
        if tid in seen:
            findings.append(f"{_task_label(t, snap)} appears more than once.")
            continue
        start = raw.get("start_slot")
        if not isinstance(start, int) or isinstance(start, bool):
            findings.append(f"{_task_label(t, snap)} has no whole-number start.")
            continue
        if raw.get("home_id", t.home_id) != t.home_id:
            findings.append(f"{_task_label(t, snap)} was assigned to the wrong home.")
        if "duration_slots" in raw and raw["duration_slots"] != t.duration_slots:
            findings.append(f"{_task_label(t, snap)}'s run time was changed.")
        if "power_kw" in raw and abs(float(raw["power_kw"]) - t.power_kw) > 1e-9:
            findings.append(f"{_task_label(t, snap)}'s power was changed.")
        if start < t.earliest_slot or start < 0:
            findings.append(f"{_task_label(t, snap)} starts before {slot_to_time(max(0, t.earliest_slot))}.")
        if start + t.duration_slots > t.deadline_slot:
            findings.append(f"{_task_label(t, snap)} would finish after its {slot_to_time(t.deadline_slot)} deadline.")
        if start + t.duration_slots > snap.slots:
            findings.append(f"{_task_label(t, snap)} runs past the end of the planning window.")
        seen[tid] = start
        entries.append(entry_for(t, start))
    for tid, t in tasks.items():
        if tid not in seen and not any(f"'{tid}'" in x for x in findings):
            findings.append(f"{_task_label(t, snap)} is missing from the plan.")

    load = load_by_slot(snap, entries)
    over = [i for i, x in enumerate(load) if x > snap.capacity_kw + snap.capacity_tolerance_kw]
    if over:
        findings.append(f"The street goes over {snap.capacity_kw:g} kW at {slot_to_time(over[0])} "
                        f"(peak {max(load):.1f} kW).")
    return findings


def canonical_schedule(snap: Snapshot, raw_entries: list[dict[str, Any]]) -> list[ScheduleEntry]:
    """Rebuild entries from canonical tasks. Call only after validate_schedule returned no findings."""
    tasks = snap.task_map()
    starts = {r["task_id"]: r["start_slot"] for r in raw_entries}
    return [entry_for(t, starts[t.id]) for t in snap.tasks]


# ---------------------------------------------------------------- evaluation helpers (for MCP tools)

def evaluate_schedule(snap: Snapshot, raw_entries: list[dict[str, Any]]) -> dict[str, Any]:
    findings = validate_schedule(snap, raw_entries)
    valid = not findings
    out: dict[str, Any] = {"valid": valid, "findings": findings}
    if valid:
        sched = canonical_schedule(snap, raw_entries)
        m = compute_metrics(snap, sched)
        out["metrics"] = m.model_dump()
        out["expensive_hours_share_by_home"] = expensive_share_by_home(snap, sched)
        out["summary"] = (
            f"Under the {snap.capacity_kw:g} kW limit (peak {m.peak_kw:.1f} kW), "
            f"all {m.tasks_total} appliances finish on time."
        )
    else:
        out["summary"] = "This plan doesn't work: " + findings[0]
    return out


def expensive_share_by_home(snap: Snapshot, schedule: list[ScheduleEntry]) -> dict[str, float]:
    """Fraction (0-1) of each home's flexible (task) energy that runs at the highest price. 0 under a flat rate."""
    prices = snap.tariff_usd_per_kwh
    top = max(prices)
    if top - min(prices) < 1e-9:
        return {h.id: 0.0 for h in snap.homes}
    out: dict[str, float] = {}
    for h in snap.homes:
        total = exp = 0.0
        for e in schedule:
            if e.home_id != h.id:
                continue
            for s in range(e.start_slot, e.start_slot + e.duration_slots):
                total += e.power_kw
                if prices[s] >= top - 1e-9:
                    exp += e.power_kw
        out[h.id] = round(exp / total, 4) if total else 0.0
    return out


def compare_schedules(snap: Snapshot, baseline: list[ScheduleEntry], candidate: list[ScheduleEntry]) -> dict[str, Any]:
    mb, mc = compute_metrics(snap, baseline), compute_metrics(snap, candidate)
    per_home = {}
    for h in snap.homes:
        b, c = mb.per_home[h.id], mc.per_home[h.id]
        per_home[h.id] = {
            "cost_before_usd": b.variable_cost_usd, "cost_after_usd": c.variable_cost_usd,
            "cost_change_usd": _r(c.variable_cost_usd - b.variable_cost_usd),
            "energy_change_kwh": _r(c.energy_kwh - b.energy_kwh),
        }
    bstart = {e.task_id: e.start_slot for e in baseline}
    moved = [
        {"task_id": e.task_id, "home_id": e.home_id, "from_slot": bstart.get(e.task_id), "to_slot": e.start_slot,
         "from_time": slot_to_time(bstart[e.task_id]) if e.task_id in bstart else None,
         "to_time": slot_to_time(e.start_slot)}
        for e in candidate if bstart.get(e.task_id) != e.start_slot
    ]
    return {
        "total": {
            "cost_before_usd": mb.variable_cost_usd, "cost_after_usd": mc.variable_cost_usd,
            "cost_change_usd": _r(mc.variable_cost_usd - mb.variable_cost_usd),
            "peak_before_kw": mb.peak_kw, "peak_after_kw": mc.peak_kw,
            "energy_change_kwh": _r(mc.energy_kwh - mb.energy_kwh),
        },
        "per_home": per_home,
        "moved": moved,
    }


def home_context(snap: Snapshot, home_id: str) -> dict[str, Any]:
    """One home's own tasks plus the shared totals it needs. Never another home's tasks."""
    if home_id not in {h.id for h in snap.homes}:
        raise ValueError(f"unknown home {home_id!r}")
    prices = snap.tariff_usd_per_kwh
    return {
        "home_id": home_id,
        "tasks": [
            {**t.model_dump(), "deadline_time": slot_to_time(t.deadline_slot),
             "preferred_start_time": slot_to_time(t.preferred_start_slot)}
            for t in snap.tasks if t.home_id == home_id
        ],
        "background_kw": snap.background_kw_by_home.get(home_id, 0.0),
        "capacity_kw": snap.capacity_kw,
        "tariff_mode": snap.tariff_mode,
        "tariff_label": snap.tariff_label,
        "tariff_summary": tariff_summary(snap),
        "min_price_usd_per_kwh": min(prices),
        "max_price_usd_per_kwh": max(prices),
    }


def tariff_summary(snap: Snapshot) -> str:
    p = snap.tariff_usd_per_kwh
    if max(p) - min(p) < 1e-9:
        return f"Flat rate: ${p[0]:.2f}/kWh at every hour, so moving an appliance doesn't change its cost."
    hi, lo = max(p), min(p)
    first_cheap = next(i for i, x in enumerate(p) if x <= lo + 1e-9)
    back = next((i for i in range(first_cheap, len(p)) if p[i] >= hi - 1e-9), len(p))
    return (f"${hi:.2f}/kWh until {slot_to_time(first_cheap)}, then ${lo:.2f}/kWh until "
            f"{slot_to_time(back)} the next day.")
