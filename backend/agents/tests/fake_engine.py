"""TEST-ONLY stand-in for D's engine, so C's code can be tested before D's
`backend.simulation.engine_api` lands. Not used at runtime.

Implements the two bridge functions (see backend/tools/engine_bridge.py) with
the PRD §15.1 heuristic: least slack, then higher power, then ID; starts
ranked by cost, then resulting street peak, then distance from preference.
"""

from __future__ import annotations

from typing import Any

SLOT_H = 0.25
TOL = 1e-6


def _bg(snapshot: dict[str, Any]) -> dict[str, list[float]]:
    out = {}
    for h, v in (snapshot.get("background_kw_by_home") or {}).items():
        out[h] = list(v) if isinstance(v, list) else [float(v)] * 96
    return out


def _base_load(snapshot) -> list[float]:
    load = [0.0] * 96
    for arr in _bg(snapshot).values():
        for i, x in enumerate(arr):
            load[i] += x
    return load


def evaluate_schedule(snapshot: dict[str, Any], schedule: list[dict[str, Any]]) -> dict[str, Any]:
    tasks = {t["id"]: t for t in snapshot["tasks"]}
    prices = snapshot["tariff_usd_per_kwh"]
    cap = snapshot["capacity_kw"]
    findings = []
    bg = _bg(snapshot)
    homes = sorted(set(bg) | {t["home_id"] for t in tasks.values()})
    home_load = {h: list(bg.get(h, [0.0] * 96)) for h in homes}
    seen = set()
    missed = 0
    for e in schedule:
        t = tasks.get(e["task_id"])
        if t is None:
            findings.append(f"unknown task {e['task_id']}")
            continue
        if e["task_id"] in seen:
            findings.append(f"duplicate task {e['task_id']}")
            continue
        seen.add(e["task_id"])
        s = int(e["start_slot"])
        if s < t["earliest_slot"] or s + t["duration_slots"] > t["deadline_slot"] or s + t["duration_slots"] > 96:
            missed += 1
            findings.append(f"{t['id']} misses its window")
        for i in range(max(0, s), min(96, s + t["duration_slots"])):
            home_load[t["home_id"]][i] += t["power_kw"]
    for tid in tasks:
        if tid not in seen:
            findings.append(f"missing task {tid}")
    total = [sum(home_load[h][i] for h in homes) for i in range(96)]
    violations = sum(1 for x in total if x > cap + TOL)
    if violations:
        findings.append(f"over the limit in {violations} periods")

    def m(load):
        return {
            "energy_kwh": round(sum(x * SLOT_H for x in load), 6),
            "variable_cost_usd": round(sum(x * SLOT_H * p for x, p in zip(load, prices)), 6),
            "peak_kw": round(max(load), 6),
        }

    metrics = {
        **m(total),
        "missed_deadlines": missed,
        "capacity_violations": violations,
        "tasks_completed": len(seen) - missed,
        "tasks_total": len(tasks),
        "per_home": {h: m(home_load[h]) for h in homes},
    }
    return {"metrics": metrics, "valid": not findings, "findings": findings}


def find_feasible_schedule(snapshot, pins=None, preferred_overrides=None) -> dict[str, Any]:
    pins = pins or {}
    prefs = preferred_overrides or {}
    tasks = sorted(
        snapshot["tasks"],
        key=lambda t: (t["deadline_slot"] - t["earliest_slot"] - t["duration_slots"], -t["power_kw"], t["id"]),
    )
    prices = snapshot["tariff_usd_per_kwh"]
    cap = snapshot["capacity_kw"]
    reasons = []
    for t in tasks:
        if t["earliest_slot"] + t["duration_slots"] > min(t["deadline_slot"], 96):
            reasons.append(f"{t['name']} for Home {t['home_id']} cannot finish by its deadline")
    if reasons:
        return {"ok": False, "schedule": None, "reasons": reasons, "proven_impossible": True}

    load = _base_load(snapshot)
    placed: dict[str, int] = {}
    pinned = [t for t in tasks if t["id"] in pins]
    free = [t for t in tasks if t["id"] not in pins]

    def fits(t, s):
        return all(load[i] + t["power_kw"] <= cap + TOL for i in range(s, s + t["duration_slots"]))

    def add(t, s, sign):
        for i in range(s, s + t["duration_slots"]):
            load[i] += sign * t["power_kw"]

    for t in pinned:
        s = pins[t["id"]]
        if not (t["earliest_slot"] <= s and s + t["duration_slots"] <= min(t["deadline_slot"], 96)) or not fits(t, s):
            return {"ok": False, "schedule": None, "reasons": [f"{t['name']} cannot start at the agreed time"], "proven_impossible": True}
        add(t, s, 1)
        placed[t["id"]] = s

    budget = [20000]

    def ranked(t):
        pref = prefs.get(t["id"], t["preferred_start_slot"])
        opts = []
        for s in range(t["earliest_slot"], min(t["deadline_slot"], 96) - t["duration_slots"] + 1):
            if not fits(t, s):
                continue
            cost = sum(prices[i] for i in range(s, s + t["duration_slots"])) * t["power_kw"] * SLOT_H
            peak = max(max(load), max(load[i] + t["power_kw"] for i in range(s, s + t["duration_slots"])))
            opts.append((round(cost, 6), round(peak, 6), abs(s - pref), s))
        return [o[-1] for o in sorted(opts)]

    def search(i):
        if i == len(free):
            return True
        budget[0] -= 1
        if budget[0] < 0:
            return False
        t = free[i]
        for s in ranked(t):
            add(t, s, 1)
            placed[t["id"]] = s
            if search(i + 1):
                return True
            add(t, s, -1)
            del placed[t["id"]]
        return False

    if not search(0):
        return {"ok": False, "schedule": None, "reasons": ["the street limit cannot fit every appliance in time"], "proven_impossible": budget[0] >= 0}
    by_id = {t["id"]: t for t in tasks}
    schedule = [
        {"task_id": tid, "home_id": by_id[tid]["home_id"], "start_slot": s,
         "duration_slots": by_id[tid]["duration_slots"], "power_kw": by_id[tid]["power_kw"]}
        for tid, s in sorted(placed.items())
    ]
    return {"ok": True, "schedule": schedule, "reasons": [], "proven_impossible": False}
