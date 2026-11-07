"""Appliances a household can add from its phone (team request after the live test).

Only appliances that can be *scheduled* are offered: they run for a fixed time at a roughly constant
power and the resident mainly cares when they finish. Cooking appliances run when people eat, so they
can't be moved and are not offered. Values are illustrative, rounded from typical US figures (see
backend/data/provenance.md); slots are 15 minutes and slot 0 is 6:00 PM.
"""
from __future__ import annotations

from typing import Any

# kind -> appliance. deadline/preferred are defaults the resident can change (deadline) or the agents trade.
CATALOG: dict[str, dict[str, Any]] = {
    "ev": {"label": "EV charging", "name": "EV charging", "power_kw": 7.2, "duration_slots": 12,
           "deadline_slot": 48, "preferred_start_slot": 0,
           "note": "Level 2 home charger, 3 hours."},
    "dryer": {"label": "a clothes dryer", "name": "Clothes dryer", "power_kw": 5.0, "duration_slots": 3,
              "deadline_slot": 20, "preferred_start_slot": 2,
              "note": "Electric dryer, 45 minutes."},
    "washer": {"label": "a washing machine", "name": "Washing machine", "power_kw": 0.5, "duration_slots": 4,
               "deadline_slot": 20, "preferred_start_slot": 2,
               "note": "One load, about 1 hour."},
    "dishwasher": {"label": "a dishwasher", "name": "Dishwasher", "power_kw": 1.2, "duration_slots": 4,
                   "deadline_slot": 20, "preferred_start_slot": 6,
                   "note": "One cycle, 1 hour."},
    "water_heater": {"label": "a water heater", "name": "Water heater", "power_kw": 4.5, "duration_slots": 6,
                     "deadline_slot": 48, "preferred_start_slot": 0,
                     "note": "Electric tank reheat, 90 minutes, hot water by morning."},
    "ac": {"label": "air conditioning", "name": "Air conditioning", "power_kw": 3.5, "duration_slots": 8,
           "deadline_slot": 20, "preferred_start_slot": 0,
           "note": "Central AC, a 2-hour cool-down before bed (simplified: real thermostats vary)."},
    "pool_pump": {"label": "a pool pump", "name": "Pool pump", "power_kw": 1.5, "duration_slots": 16,
                  "deadline_slot": 48, "preferred_start_slot": 0,
                  "note": "4-hour filter run overnight."},
}

NOT_SCHEDULABLE = [
    {"name": "Microwave, stove, oven", "why": "They run when you cook, so there's nothing to move."},
    {"name": "Fridge, lights, TV", "why": "Always on or used live; part of each home's 1.2 kW always-on use."},
]

MAX_APPLIANCES_PER_HOME = 6


def catalog_view() -> dict[str, Any]:
    return {
        "schedulable": [{"kind": k, **v} for k, v in CATALOG.items()],
        "not_schedulable": NOT_SCHEDULABLE,
        "max_per_home": MAX_APPLIANCES_PER_HOME,
    }
