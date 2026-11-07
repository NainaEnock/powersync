"""JSON-in / JSON-out engine entry points for the MCP server (backend/tools/energy_server.py).

Snapshots are plain dicts (as sent over MCP) with the NeighborhoodState names:
generation, requirements_version, capacity_kw, tariff_mode, tariff_label,
tariff_usd_per_kwh[96], homes, tasks, background_kw_by_home, baseline_schedule.
Extra keys are ignored. pins / preferred_overrides map task_id -> slot.
"""

from __future__ import annotations

from typing import Any, Optional, Union

from . import engine
from .scenario import build_snapshot, scenario_tasks
from .schema import Snapshot, Task

SnapshotLike = Union[Snapshot, dict[str, Any]]


def _snap(snapshot: SnapshotLike) -> Snapshot:
    return snapshot if isinstance(snapshot, Snapshot) else Snapshot.model_validate(snapshot)


def snapshot_dict(snap: Snapshot) -> dict[str, Any]:
    """Snapshot as a JSON-serializable dict, with baseline_schedule (preferred times) included."""
    d = snap.model_dump()
    d["baseline_schedule"] = [e.model_dump() for e in engine.preferred_schedule(snap)]
    return d


def scenario_snapshot(tariff_mode: str = "tou", tasks: Optional[list[Union[Task, dict]]] = None,
                      generation: int = 0, requirements_version: int = 0) -> dict[str, Any]:
    """Fresh snapshot built from backend/data/scenario.json. Use this in tests instead of copied data."""
    t = [x if isinstance(x, Task) else Task.model_validate(x) for x in tasks] if tasks is not None else scenario_tasks()
    return snapshot_dict(build_snapshot(tasks=t, tariff_mode=tariff_mode, generation=generation,
                                        requirements_version=requirements_version))


def find_feasible_schedule(snapshot: SnapshotLike, pins: Optional[dict[str, int]] = None,
                           preferred_overrides: Optional[dict[str, int]] = None) -> dict[str, Any]:
    """-> {ok, schedule[entries], reasons[plain English], proven_impossible, status}"""
    try:
        r = engine.find_feasible_schedule(_snap(snapshot), pins=pins or {}, preferred_overrides=preferred_overrides or {})
    except Exception as e:  # noqa: BLE001  bad snapshot from a tool argument
        return {"ok": False, "schedule": [], "reasons": [f"The plan request couldn't be read ({type(e).__name__})."],
                "proven_impossible": False, "status": "bad_input"}
    return {
        "ok": r.ok,
        "schedule": [e.model_dump() for e in r.schedule],
        "reasons": r.reasons,
        "proven_impossible": r.status == "impossible",
        "status": r.status,
    }


def evaluate_schedule(snapshot: SnapshotLike, schedule: list[dict[str, Any]]) -> dict[str, Any]:
    """-> {valid, findings[], metrics (per_home keyed by home ID) or None, summary, expensive_hours_share_by_home}"""
    snap = _snap(snapshot)
    raw = [e.model_dump() if hasattr(e, "model_dump") else dict(e) for e in schedule]
    out = engine.evaluate_schedule(snap, raw)
    out.setdefault("metrics", None)
    return out


def compare_schedules(snapshot: SnapshotLike, baseline: list[dict[str, Any]], candidate: list[dict[str, Any]]) -> dict[str, Any]:
    snap = _snap(snapshot)
    b = engine.canonical_schedule(snap, baseline)
    c = engine.canonical_schedule(snap, candidate)
    return engine.compare_schedules(snap, b, c)


def get_home_context(snapshot: SnapshotLike, home_id: str) -> dict[str, Any]:
    return engine.home_context(_snap(snapshot), home_id)
