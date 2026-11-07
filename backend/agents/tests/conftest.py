"""Shared fixtures for the agent tests.

The snapshot is built from backend/data/scenario.json when D's loader exists.
Until then it falls back to the PRD §9 table, and says so. TODO(C, after D's
D2/D4 lands): delete the fallback and use only D's snapshot builder.
"""

from __future__ import annotations

import copy
import os
import warnings

import pytest

os.environ["POWERSYNC_ENGINE_MODULE"] = "backend.agents.tests.fake_engine"
os.environ.pop("OPENROUTER_API_KEY", None)  # tests never call the real model


def _prd_snapshot() -> dict:
    def task(id_, home, name, kw, dur, deadline, pref):
        return {"id": id_, "home_id": home, "name": name, "power_kw": kw, "duration_slots": dur,
                "earliest_slot": 0, "deadline_slot": deadline, "preferred_start_slot": pref,
                "interruptible": False}

    tou = [0.59] * 12 + [0.33] * 76 + [0.59] * 8
    tasks = [
        task("a_ev", "A", "EV charging", 7.2, 12, 28, 0),
        task("a_dish", "A", "Dishwasher", 1.2, 4, 20, 6),
        task("b_dryer", "B", "Clothes dryer", 5.0, 3, 20, 2),
        task("b_dish", "B", "Dishwasher", 1.2, 4, 20, 6),
        task("c_ev", "C", "EV charging", 7.2, 12, 48, 0),
        task("c_dish", "C", "Dishwasher", 1.2, 4, 20, 6),
    ]
    return {
        "scenario_id": "prd-v2-fallback",
        "generation": 1,
        "requirements_version": 1,
        "revision": 1,
        "horizon_start": "2026-07-15T18:00:00-04:00",
        "slot_minutes": 15,
        "capacity_kw": 15.0,
        "tariff_mode": "tou",
        "tariff_label": "Illustrative time-of-use tariff",
        "tariff_usd_per_kwh": tou,
        "homes": [{"id": h, "name": f"Home {h}", "color": c, "preferences": {}}
                  for h, c in (("A", "#2563eb"), ("B", "#d97706"), ("C", "#059669"))],
        "tasks": tasks,
        "background_kw_by_home": {h: [1.2] * 96 for h in "ABC"},
        "baseline_schedule": [
            {"task_id": t["id"], "home_id": t["home_id"], "start_slot": t["preferred_start_slot"],
             "duration_slots": t["duration_slots"], "power_kw": t["power_kw"]} for t in tasks
        ],
    }


def _load() -> dict:
    try:
        from backend.simulation.scenario import build_agent_snapshot  # D, once it exists
    except ImportError:
        warnings.warn("backend.simulation snapshot builder not found; using PRD §9 fallback snapshot")
        return _prd_snapshot()
    return build_agent_snapshot()


_SNAP = _load()


@pytest.fixture
def snapshot() -> dict:
    return copy.deepcopy(_SNAP)


@pytest.fixture
def flat_snapshot() -> dict:
    snapshot = copy.deepcopy(_SNAP)
    snapshot["tariff_mode"] = "flat"
    snapshot["tariff_label"] = "Flat rate"
    snapshot["tariff_usd_per_kwh"] = [0.18] * 96
    return snapshot
