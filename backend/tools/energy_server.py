"""powersync-energy: the custom MCP server (FastMCP, stdio).

Run standalone:  python -m backend.tools.energy_server

The server owns no state. Every tool receives the snapshot the backend built.
Power, duration, tasks, prices, and capacity always come from that snapshot;
schedules passed in are rebuilt from canonical tasks so only start times are
taken from the caller. Logs go to stderr because stdout carries the protocol.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from fastmcp import FastMCP

from backend.agents.timefmt import slot_range, slot_to_time, usd
from backend.tools.engine_bridge import load_engine

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("powersync-energy")

mcp = FastMCP(
    "powersync-energy",
    instructions="Deterministic energy tools for the PowerSync neighborhood. All numbers come from the engine.",
)

_engine = None


def engine():
    global _engine
    if _engine is None:
        _engine = load_engine()
    return _engine


# --- helpers ---------------------------------------------------------------


def _tasks(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tasks = snapshot.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("snapshot has no tasks")
    return {t["id"]: t for t in tasks}


def _check_snapshot(snapshot: dict[str, Any]) -> None:
    _tasks(snapshot)
    prices = snapshot.get("tariff_usd_per_kwh")
    if not isinstance(prices, list) or len(prices) != 96:
        raise ValueError("snapshot tariff must have 96 prices")
    if not isinstance(snapshot.get("capacity_kw"), (int, float)):
        raise ValueError("snapshot has no capacity_kw")


def _canonical(snapshot: dict[str, Any], schedule: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rebuild entries from canonical tasks. Unknown task IDs are dropped here
    and then reported by the engine as missing tasks."""
    tasks = _tasks(snapshot)
    out = []
    for e in schedule or []:
        t = tasks.get(str(e.get("task_id")))
        if t is None:
            continue
        out.append(
            {
                "task_id": t["id"],
                "home_id": t["home_id"],
                "start_slot": int(e["start_slot"]),
                "duration_slots": t["duration_slots"],
                "power_kw": t["power_kw"],
            }
        )
    unknown = [e.get("task_id") for e in schedule or [] if str(e.get("task_id")) not in tasks]
    if unknown:
        log.warning("dropped unknown task ids: %s", unknown)
    return out


def _clean_pins(snapshot: dict[str, Any], pins: dict[str, int] | None) -> dict[str, int]:
    tasks = _tasks(snapshot)
    return {k: int(v) for k, v in (pins or {}).items() if k in tasks}


def _metrics_line(m: dict[str, Any], capacity: float) -> str:
    under = "under" if m.get("capacity_violations", 0) == 0 else "over"
    done = m.get("tasks_completed", 0)
    total = m.get("tasks_total", 0)
    on_time = "all" if done == total and not m.get("missed_deadlines") else f"{done} of"
    return f"peak {m['peak_kw']:.1f} kW, {under} the {capacity:g} kW limit; {on_time} {total} appliances finish on time"


def _home_label(snapshot: dict[str, Any], home_id: str) -> str:
    for h in snapshot.get("homes", []):
        if h.get("id") == home_id:
            return h.get("name") or f"Home {home_id}"
    return f"Home {home_id}"


# --- tools -----------------------------------------------------------------


@mcp.tool
def get_home_context(home_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    """One home's tasks, deadlines, background use, and a tariff summary."""
    _check_snapshot(snapshot)
    if hasattr(engine(), "get_home_context"):
        return engine().get_home_context(snapshot, home_id)
    tasks = [t for t in snapshot["tasks"] if t["home_id"] == home_id]
    if not tasks:
        raise ValueError(f"unknown home {home_id!r}")
    prices = snapshot["tariff_usd_per_kwh"]
    low, high = min(prices), max(prices)
    expensive = [i for i, p in enumerate(prices) if p > low + 1e-9]
    bg = (snapshot.get("background_kw_by_home") or {}).get(home_id, 0)
    return {
        "home_id": home_id,
        "home_name": _home_label(snapshot, home_id),
        "tasks": [
            {
                **t,
                "deadline_time": slot_to_time(t["deadline_slot"]),
                "preferred_start_time": slot_to_time(t["preferred_start_slot"]),
            }
            for t in tasks
        ],
        "background_kw": bg if isinstance(bg, (int, float)) else (bg[0] if bg else 0),
        "capacity_kw": snapshot["capacity_kw"],
        "tariff": {
            "mode": snapshot.get("tariff_mode", "tou"),
            "label": snapshot.get("tariff_label", ""),
            "low_usd_per_kwh": low,
            "high_usd_per_kwh": high,
            "expensive_hours": _hours_text(expensive),
        },
    }


def _hours_text(slots: list[int]) -> str:
    if not slots:
        return "none (same price all day)"
    runs, start, prev = [], slots[0], slots[0]
    for s in slots[1:]:
        if s != prev + 1:
            runs.append((start, prev + 1))
            start = s
        prev = s
    runs.append((start, prev + 1))
    return ", ".join(slot_range(a, b) for a, b in runs)


@mcp.tool
def evaluate_schedule(snapshot: dict[str, Any], schedule: list[dict[str, Any]]) -> dict[str, Any]:
    """Metrics and validation findings for a schedule. Changes nothing."""
    _check_snapshot(snapshot)
    res = engine().evaluate_schedule(snapshot, _canonical(snapshot, schedule))
    if not res.get("summary"):
        m = res.get("metrics")
        line = _metrics_line(m, snapshot["capacity_kw"]) if m else "no metrics"
        res["summary"] = ("Valid: " if res.get("valid") else "Not valid: ") + line
        if res.get("findings"):
            res["summary"] += ". " + "; ".join(res["findings"][:3])
    return res


@mcp.tool
def find_feasible_schedule(
    snapshot: dict[str, Any],
    pins: dict[str, int] | None = None,
    preferred_overrides: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Ask the deterministic engine for a schedule under the street limit.

    pins fix a task's start; preferred_overrides move a soft preference.
    """
    _check_snapshot(snapshot)
    res = engine().find_feasible_schedule(
        snapshot, _clean_pins(snapshot, pins), _clean_pins(snapshot, preferred_overrides)
    )
    if res.get("ok") and res.get("schedule"):
        ev = engine().evaluate_schedule(snapshot, _canonical(snapshot, res["schedule"]))
        res["metrics"] = ev.get("metrics")
        res["valid"] = ev.get("valid", False)
        res["findings"] = ev.get("findings", [])
        res["summary"] = ("Found a plan: " + _metrics_line(ev["metrics"], snapshot["capacity_kw"])
                          if ev.get("metrics") else "Found a plan, but it didn't pass the checks")
    else:
        why = "; ".join(res.get("reasons") or []) or "no reason given"
        kind = "No plan is possible" if res.get("proven_impossible") else "No plan found within the search budget"
        res["summary"] = f"{kind}: {why}"
    return res


@mcp.tool
def compare_schedules(
    snapshot: dict[str, Any], baseline: list[dict[str, Any]], candidate: list[dict[str, Any]]
) -> dict[str, Any]:
    """Per-home and total cost differences between two schedules, plus what moved."""
    _check_snapshot(snapshot)
    tasks = _tasks(snapshot)
    base = _canonical(snapshot, baseline)
    cand = _canonical(snapshot, candidate)
    ec = engine().evaluate_schedule(snapshot, cand)
    if hasattr(engine(), "compare_schedules"):
        d = engine().compare_schedules(snapshot, base, cand)
    else:
        d = _compare_from_evaluate(snapshot, base, cand)

    def delta(v: dict[str, Any], key: str) -> float:
        return float(v.get(f"{key}_change_usd", v.get(f"{key}_delta_usd", 0.0)))

    per_home = {
        h: {
            "cost_before_usd": v["cost_before_usd"],
            "cost_after_usd": v["cost_after_usd"],
            "cost_delta_usd": round(delta(v, "cost"), 4),
        }
        for h, v in d["per_home"].items()
    }
    t = d["total"]

    def derived(which: str, peak: float) -> dict[str, Any]:
        return {
            "variable_cost_usd": t[f"cost_{which}_usd"],
            "peak_kw": peak,
            "per_home": {h: {"variable_cost_usd": v[f"cost_{which}_usd"]} for h, v in d["per_home"].items()},
        }

    baseline_metrics = derived("before", t["peak_before_kw"])
    candidate_metrics = ec.get("metrics") or derived("after", t["peak_after_kw"])
    moved = [
        {
            "task_id": m["task_id"],
            "home_id": m["home_id"],
            "from_slot": m["from_slot"],
            "to_slot": m["to_slot"],
            "deadline_slot": tasks[m["task_id"]]["deadline_slot"],
        }
        for m in d["moved"]
    ]
    cost_delta = t["cost_after_usd"] - t["cost_before_usd"]
    return {
        "baseline_metrics": baseline_metrics,
        "candidate_metrics": candidate_metrics,
        "candidate_valid": bool(ec.get("valid")),
        "candidate_findings": ec.get("findings", []),
        "total": {**t, "cost_delta_usd": round(cost_delta, 4)},
        "per_home": per_home,
        "moved": moved,
        "summary": (
            f"{len(moved)} appliance{'s' if len(moved) != 1 else ''} moved; "
            f"street charge {usd(t['cost_before_usd'])} to {usd(t['cost_after_usd'])}; "
            f"peak {t['peak_before_kw']:.1f} to {t['peak_after_kw']:.1f} kW"
        ),
    }


def _compare_from_evaluate(snapshot, base, cand) -> dict[str, Any]:
    """For an engine module without compare_schedules (needs metrics even when invalid)."""
    mb = engine().evaluate_schedule(snapshot, base)["metrics"]
    mc = engine().evaluate_schedule(snapshot, cand)["metrics"]
    bstart = {e["task_id"]: e["start_slot"] for e in base}
    return {
        "total": {"cost_before_usd": mb["variable_cost_usd"], "cost_after_usd": mc["variable_cost_usd"],
                  "peak_before_kw": mb["peak_kw"], "peak_after_kw": mc["peak_kw"]},
        "per_home": {h: {"cost_before_usd": mb["per_home"][h]["variable_cost_usd"],
                         "cost_after_usd": mc["per_home"][h]["variable_cost_usd"],
                         "cost_change_usd": mc["per_home"][h]["variable_cost_usd"] - mb["per_home"][h]["variable_cost_usd"]}
                     for h in mb["per_home"]},
        "moved": [{"task_id": e["task_id"], "home_id": e["home_id"], "from_slot": bstart[e["task_id"]], "to_slot": e["start_slot"]}
                  for e in cand if e["task_id"] in bstart and bstart[e["task_id"]] != e["start_slot"]],
    }


if __name__ == "__main__":
    mcp.run(show_banner=False)
