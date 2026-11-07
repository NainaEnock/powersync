"""Code-written (system_template) text. Plain English, 12-hour times, dollars from code.

The agents own conversation wording; these are the backend's templates for plan/validation/commit
messages and the stub. C may import and reuse them, or tell D what to change.
"""

from __future__ import annotations

from typing import Optional

from .engine import compute_metrics
from .schema import ScheduleEntry, Snapshot, Task
from .timefmt import slot_to_time, span_text, usd


def noun(t: Task) -> str:
    """'EV charging' -> 'car charging' (the agents' wording), 'Clothes dryer' -> 'clothes dryer'."""
    if t.name.lower().startswith("ev "):
        return "car " + t.name[3:]
    return t.name if t.name[:2].isupper() else t.name[0].lower() + t.name[1:]


def home_name(snap: Snapshot, home_id: str) -> str:
    return next((h.name for h in snap.homes if h.id == home_id), f"Home {home_id}")


def _starts(schedule: Optional[list[ScheduleEntry]]) -> dict[str, int]:
    return {e.task_id: e.start_slot for e in (schedule or [])}


def moves(snap: Snapshot, before: list[ScheduleEntry], after: list[ScheduleEntry], home_id: Optional[str] = None,
          you: bool = False) -> list[str]:
    b, a = _starts(before), _starts(after)
    out = []
    for t in snap.tasks:
        if home_id and t.home_id != home_id:
            continue
        if t.id not in a or b.get(t.id) == a[t.id]:
            continue
        who = f"your {noun(t)}" if you else f"{home_name(snap, t.home_id)}'s {noun(t)}"
        if t.id in b:
            out.append(f"{who} moves from {slot_to_time(b[t.id])} to {slot_to_time(a[t.id])}")
        else:
            out.append(f"{who} runs {span_text(a[t.id], t.duration_slots)}")
    return out


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def plan_announcement(snap: Snapshot, plan_name: str, before: list[ScheduleEntry], after: list[ScheduleEntry],
                      before_label: str) -> tuple[str, dict[str, str]]:
    """('Here's Plan 1. Compared with everyone's preferred times: ...', {A: ..., B: ..., C: ...})."""
    m = compute_metrics(snap, after)
    limit = f"The street stays under {snap.capacity_kw:g} kW." if m.capacity_violations == 0 else \
        f"The street goes over {snap.capacity_kw:g} kW."
    mv = moves(snap, before, after)
    b, a = _starts(before), _starts(after)
    stays = [f"{home_name(snap, t.home_id)}'s {noun(t)} stays at {slot_to_time(a[t.id])}"
             for t in snap.tasks if t.id in a and b.get(t.id) == a[t.id]]
    if stays and max(snap.tariff_usd_per_kwh) > min(snap.tariff_usd_per_kwh):
        top = max(snap.tariff_usd_per_kwh)
        stays = [s + (" (expensive hours)" if snap.tariff_usd_per_kwh[a[t.id]] >= top else "")
                 for s, t in zip(stays, [t for t in snap.tasks if t.id in a and b.get(t.id) == a[t.id]])]
    body = _join(mv + stays) if (mv or stays) else "nothing moves"
    text = f"Here's {plan_name}. Compared with {before_label}: {body}. {limit}"
    views = {}
    for h in snap.homes:
        own = moves(snap, before, after, h.id, you=True)
        own_txt = _cap(_join(own)) + "." if own else "Your appliances keep the same times."
        views[h.id] = f"Here's {plan_name}. {own_txt} {limit}"
    return text[:800], {k: v[:800] for k, v in views.items()}


def schedule_lines(snap: Snapshot, schedule: list[ScheduleEntry], home_id: str) -> str:
    tasks = snap.task_map()
    parts = [f"{noun(tasks[e.task_id])} {span_text(e.start_slot, e.duration_slots)}"
             for e in schedule if e.home_id == home_id and e.task_id in tasks]
    return "; ".join(parts)


def validation_text(snap: Snapshot, plan_name: str, schedule: list[ScheduleEntry]) -> tuple[str, dict[str, str]]:
    m = compute_metrics(snap, schedule)
    text = (f"Checked {plan_name}: under the {snap.capacity_kw:g} kW limit (peak {m.peak_kw:.1f} kW), "
            f"and all {m.tasks_total} appliances finish on time.")
    views = {}
    for h in snap.homes:
        n = sum(1 for t in snap.tasks if t.home_id == h.id)
        views[h.id] = (f"Checked {plan_name}: the street stays under its {snap.capacity_kw:g} kW limit, "
                       f"and your {n} appliance{'s' if n != 1 else ''} finish on time.")
    return text, views


def commit_text(snap: Snapshot, plan_name: str, schedule: list[ScheduleEntry],
                previous: Optional[list[ScheduleEntry]], baseline: list[ScheduleEntry]) -> tuple[str, dict[str, str]]:
    m = compute_metrics(snap, schedule)
    mb = compute_metrics(snap, baseline)
    mp = compute_metrics(snap, previous) if previous else None
    diff = mb.variable_cost_usd - m.variable_cost_usd
    vs = (f"{usd(abs(diff))} {'less' if diff >= 0 else 'more'} than everyone's preferred times"
          if abs(diff) >= 0.005 else "the same as everyone's preferred times")
    text = (f"{plan_name} is now the street's plan. Peak demand {m.peak_kw:.1f} kW, under the "
            f"{snap.capacity_kw:g} kW limit. Modeled energy charge for the street: {usd(m.variable_cost_usd)}, {vs}.")
    if mp:
        changes = []
        for h in snap.homes:
            d = m.per_home[h.id].variable_cost_usd - mp.per_home[h.id].variable_cost_usd
            if abs(d) >= 0.005:
                changes.append(f"{h.name} {'saves' if d < 0 else 'pays'} {usd(abs(d))}")
        if changes:
            text += " Compared with the last plan: " + _join(changes) + "."
        else:
            text += " No home's cost changed from the last plan."
    views = {}
    for h in snap.homes:
        mine = m.per_home[h.id].variable_cost_usd
        v = f"{plan_name} is set. Your plan: {schedule_lines(snap, schedule, h.id)}. Modeled energy charge: {usd(mine)}."
        if mp:
            d = mine - mp.per_home[h.id].variable_cost_usd
            v += (f" That's {usd(abs(d))} {'less' if d < 0 else 'more'} than the last plan." if abs(d) >= 0.005
                  else " Same cost as the last plan.")
        views[h.id] = v[:800]
    return text[:800], views
