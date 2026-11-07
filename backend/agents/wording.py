"""Every code-written sentence people read, plus snapshot helpers.

Rules (PRD §12.2): plain English, 12-hour times, named plans that say what
moved, dollar figures formatted here (never by the model), no internal words.
`home_views` versions mention only that home's appliances and costs.
"""

from __future__ import annotations

import re
from typing import Any

from .timefmt import slot_range, slot_to_time, to_12_hour_text, usd, usd_change, usd_vs

MAX_TEXT = 800
HOMES_ORDER = ("A", "B", "C")


# --- snapshot helpers -------------------------------------------------------


def tasks_by_id(snap: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {t["id"]: t for t in snap["tasks"]}


def home_ids(snap: dict[str, Any]) -> list[str]:
    ids = [h["id"] for h in snap.get("homes", [])] or sorted({t["home_id"] for t in snap["tasks"]})
    return ids


def home_name(snap: dict[str, Any], home_id: str) -> str:
    for h in snap.get("homes", []):
        if h["id"] == home_id:
            return h.get("name") or f"Home {home_id}"
    return f"Home {home_id}"


def label(task: dict[str, Any]) -> str:
    """'EV charging' -> 'car charging', 'Clothes dryer' -> 'dryer'."""
    n = task.get("name", task.get("id", "appliance")).strip()
    low = n.lower()
    if "ev" in low.split() or "car" in low or low.startswith("ev "):
        return "car charging"
    if "dryer" in low:
        return "dryer"
    if "dish" in low:
        return "dishwasher"
    return low


def possessive(snap, home_id: str, task: dict[str, Any]) -> str:
    return f"{home_name(snap, home_id)}'s {label(task)}"


def is_flat(snap: dict[str, Any]) -> bool:
    prices = snap["tariff_usd_per_kwh"]
    return snap.get("tariff_mode") == "flat" or max(prices) - min(prices) < 1e-9


def expensive_slots(snap: dict[str, Any]) -> set[int]:
    if is_flat(snap):
        return set()
    prices = snap["tariff_usd_per_kwh"]
    low = min(prices)
    return {i for i, p in enumerate(prices) if p > low + 1e-9}


def starts(schedule: list[dict[str, Any]] | None) -> dict[str, int]:
    return {e["task_id"]: int(e["start_slot"]) for e in schedule or []}


def expensive_share(task: dict[str, Any], start: int, exp: set[int]) -> float:
    run = range(start, start + task["duration_slots"])
    return round(sum(1 for i in run if i in exp) / task["duration_slots"], 3)


def cheap_hours_text(snap: dict[str, Any]) -> str:
    exp = sorted(expensive_slots(snap))
    if not exp:
        return "The price is the same at every hour, so timing doesn't change anyone's bill."
    prices = snap["tariff_usd_per_kwh"]
    first_cheap = next(i for i in range(96) if i not in expensive_slots(snap))
    return (
        f"Electricity costs {usd(max(prices))} per kWh until {slot_to_time(first_cheap)} "
        f"and {usd(min(prices))} per kWh after that."
    )


def runs_text(task: dict[str, Any], start: int) -> str:
    return slot_range(start, start + task["duration_slots"])


def clip(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1].rstrip() + "…"


# --- sanitizing model text ---------------------------------------------------

_MONEY = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?")
_INTERNAL = re.compile(r"\b(candidate|concession|constraint satisfied|slots?|task_id)\b", re.I)


def clean_model_text(text: str, snap: dict[str, Any], allowed_money: set[str]) -> str | None:
    """Make model prose safe to show, or return None to use a template.

    Replaces task IDs with names and 24-hour times with 12-hour times. Rejects
    text with dollar amounts that code did not supply, or with internal words.
    """
    if not text or not text.strip():
        return None
    out = text
    for t in snap["tasks"]:
        out = re.sub(rf"\b{re.escape(t['id'])}\b", possessive(snap, t["home_id"], t), out)
    out = to_12_hour_text(out)
    out = re.sub(r"\b(\d+)\.0\s?kW\b", r"\1 kW", out)
    for m in _MONEY.findall(out):
        if m.replace(" ", "") not in allowed_money:
            return None
    if _INTERNAL.search(out):
        return None
    return clip(out)


# --- plan announcements -----------------------------------------------------


def _moves(snap, before: dict[str, int], after: dict[str, int]) -> list[tuple[dict, int, int]]:
    tasks = tasks_by_id(snap)
    moved = [(tasks[t], before[t], after[t]) for t in after if t in before and before[t] != after[t]]
    moved.sort(key=lambda x: (-x[0]["power_kw"], x[0]["home_id"], x[0]["id"]))
    return moved


def _move_phrase(snap, task, frm: int, to: int, *, own: bool = False) -> str:
    who = f"your {label(task)}" if own else possessive(snap, task["home_id"], task)
    verb = "starts" if "charging" in label(task) else "runs"
    return f"{who} {verb} at {slot_to_time(to)} instead of {slot_to_time(frm)}"


SMALL_KW = 3.0  # appliances below this are grouped by type so big moves stand out
_COUNT = {2: "both", 3: "the three", 4: "the four", 5: "the five", 6: "the six"}


def _changes_text(snap, moved: list[tuple[dict, int, int]]) -> str:
    """Big moves one by one; two or more small moves of one type as a group:
    "the three dishwashers shift to 9:00–11:00 PM"."""
    big = [m for m in moved if m[0]["power_kw"] >= SMALL_KW]
    small: dict[str, list[tuple[dict, int, int]]] = {}
    for m in moved:
        if m[0]["power_kw"] < SMALL_KW:
            small.setdefault(label(m[0]), []).append(m)
    parts = [_move_phrase(snap, t, f, to) for t, f, to in big]
    for lab, ms in small.items():
        if len(ms) == 1:
            t, f, to = ms[0]
            parts.append(_move_phrase(snap, t, f, to))
        else:
            first = min(to for _, _, to in ms)
            last = max(to + t["duration_slots"] for t, _, to in ms)
            parts.append(f"{_COUNT.get(len(ms), str(len(ms)))} {lab}s shift to {slot_range(first, last)}")
    return "; ".join(parts)


def plan_announcement(
    snap: dict[str, Any],
    proposal_id: str,
    plan_name: str,
    schedule: list[dict[str, Any]],
    metrics: dict[str, Any],
    *,
    previous: list[dict[str, Any]] | None,
    previous_name: str,
    previous_metrics: dict[str, Any],
) -> tuple[str, dict[str, str]]:
    """Full dashboard text plus per-home phone text for a new plan."""
    tasks = tasks_by_id(snap)
    after = starts(schedule)
    before = starts(previous)
    moved = _moves(snap, before, after)
    exp = expensive_slots(snap)
    cap = snap["capacity_kw"]

    if moved:
        what = f"What's different from {previous_name}: {_changes_text(snap, moved)}."
    else:
        what = f"Nothing moves compared with {previous_name}."
    pricey = [tasks[t] for t, s in after.items() if exp and expensive_share(tasks[t], s, exp) > 0]
    pricey_txt = ""
    if pricey:
        names = ", ".join(possessive(snap, t["home_id"], t) for t in pricey)
        pricey_txt = f" Still in the expensive hours: {names}."
    limit = "under" if metrics.get("capacity_violations", 0) == 0 else "over"
    full = (
        f"Here's {plan_name}. {what}{pricey_txt} The street peaks at {metrics['peak_kw']:.1f} kW, "
        f"{limit} the {cap:g} kW limit, and every appliance finishes on time. "
        f"Estimated street energy charge: {usd(metrics['variable_cost_usd'])} "
        f"({usd_vs(metrics['variable_cost_usd'] - previous_metrics['variable_cost_usd'], previous_name)})."
    )

    views = {}
    for h in home_ids(snap):
        own = [tasks[t] for t in after if tasks[t]["home_id"] == h]
        own.sort(key=lambda t: -t["power_kw"])
        lines = []
        for t in own:
            s = after[t["id"]]
            done = slot_to_time(s + t["duration_slots"])
            note = ""
            if t["id"] in before and before[t["id"]] != s:
                note = f" (was {slot_to_time(before[t['id']])})"
            lines.append(f"your {label(t)} runs {runs_text(t, s)}{note}, done by {done}")
        mine = metrics["per_home"].get(h, {}).get("variable_cost_usd", 0.0)
        prev = previous_metrics["per_home"].get(h, {}).get("variable_cost_usd", 0.0)
        views[h] = clip(
            f"{plan_name} for your home: " + "; ".join(lines) + ". "
            f"Your estimated charge is {usd(mine)}, {usd_vs(mine - prev, previous_name)}. "
            f"The street stays {limit} its {cap:g} kW limit."
        )
    return clip(full), views


# --- trigger, reviews, asks, commit -----------------------------------------


def is_change(trigger: dict[str, Any] | None) -> bool:
    return bool(trigger and trigger.get("home_id") and trigger.get("task_id"))


def trigger_text(snap: dict[str, Any], trigger: dict[str, Any] | None) -> tuple[str, dict[str, str], str]:
    """(dashboard text, home_views, third-person context for agents).

    The backend's trigger: {home_id, task_id, field, old_value, new_value, old_time,
    new_time, edits, text}, where text is already third person.
    """
    homes = home_ids(snap)
    if not is_change(trigger):
        reason = (trigger or {}).get("reason") or "The neighborhood asked to coordinate tonight's appliances."
        text = f"{reason} {cheap_hours_text(snap)}"
        return clip(text), {h: clip(text) for h in homes}, text
    h = trigger["home_id"]
    task = tasks_by_id(snap).get(trigger.get("task_id", ""), {"name": "an appliance", "id": ""})
    field = {"deadline_slot": "finish time", "earliest_slot": "earliest start", "preferred_start_slot": "preferred start"}.get(
        trigger.get("field", ""), "requirement"
    )
    old, new = trigger.get("old_value"), trigger.get("new_value")
    change = f" from {slot_to_time(old)} to {slot_to_time(new)}" if old is not None and new is not None else ""
    third = trigger.get("text") or f"{home_name(snap, h)}'s resident changed their {label(task)} {field}{change}."
    full = f"{third} Replanning the street around it."
    views = {
        x: (f"You changed your {label(task)} {field}{change}. Replanning the street." if x == h
            else "A neighbor changed one of their requirements. Replanning the street.")
        for x in homes
    }
    return clip(full), views, third


def and_join(items: list[str]) -> str:
    """'dryer' / 'dryer and dishwasher' / 'dryer, dishwasher, and pool pump'."""
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]


def review_view(snap, home_id: str, plan_name: str, accept: bool, own_pricey: list[str], asked: bool) -> str:
    if accept:
        return f"Your agent reviewed {plan_name}: it meets your deadlines, so it agreed."
    if asked:
        what = and_join(own_pricey) or "some of your use"
        return (
            f"Your agent reviewed {plan_name}: it meets your deadlines but runs your {what} in expensive hours, "
            f"so it asked a neighbor to adjust."
        )
    return f"Your agent reviewed {plan_name} and raised a concern."


def _span(minutes: int) -> str:
    """45 -> '45 minutes', 60 -> '1 hour', 120 -> '2 hours', 90 -> '1 hour 30 minutes'."""
    h, m = divmod(minutes, 60)
    parts = ([f"{h} hour{'s' if h != 1 else ''}"] if h else []) + ([f"{m} minutes"] if m else [])
    return " ".join(parts) or "0 minutes"


def option_ask_text(snap, requester: str, ask: dict[str, Any], own_task: dict[str, Any], own_start: int) -> str:
    """Template wording of a specific neighbor request (also given to the model as a hint)."""
    tasks = tasks_by_id(snap)
    t = tasks[ask["task_id"]]
    minutes = (ask["to_slot"] - ask["from_slot"]) * snap.get("slot_minutes", 15)
    shift = f"{_span(abs(minutes))} {'later' if minutes > 0 else 'earlier'}"
    finish = slot_to_time(ask["to_slot"] + t["duration_slots"])
    return (
        f"{home_name(snap, ask['home_id'])}, could your {label(t)} start {shift}, at {slot_to_time(ask['to_slot'])}? "
        f"It would still finish by {finish}, before your {slot_to_time(t['deadline_slot'])} deadline, "
        f"and my {label(own_task)} could run {runs_text(own_task, own_start)} in cheaper hours."
    )


def ask_views(snap, requester: str, ask: dict[str, Any]) -> dict[str, str]:
    t = tasks_by_id(snap)[ask["task_id"]]
    finish = slot_to_time(ask["to_slot"] + t["duration_slots"])
    return {
        requester: f"Your agent asked {home_name(snap, ask['home_id'])} to adjust its timing so your use can move to cheaper hours.",
        ask["home_id"]: (
            f"{home_name(snap, requester)} asked whether your {label(t)} could start at {slot_to_time(ask['to_slot'])} "
            f"instead of {slot_to_time(ask['from_slot'])}. It would still finish by {finish}, before your "
            f"{slot_to_time(t['deadline_slot'])} deadline."
        ),
    }


def reply_views(snap, requester: str, ask: dict[str, Any], agree: bool, cost_delta: float) -> dict[str, str]:
    t = tasks_by_id(snap)[ask["task_id"]]
    responder = ask["home_id"]
    if agree:
        mine = (
            f"Your agent agreed: your {label(t)} can start at {slot_to_time(ask['to_slot'])} and still finish by "
            f"{slot_to_time(ask['to_slot'] + t['duration_slots'])}, with {usd_change(cost_delta)}."
        )
        theirs = f"{home_name(snap, responder)} agreed to adjust its timing."
    else:
        mine = f"Your agent declined to move your {label(t)}."
        theirs = f"{home_name(snap, responder)} couldn't adjust its timing this time."
    return {responder: mine, requester: theirs}
