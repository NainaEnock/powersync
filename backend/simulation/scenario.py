"""Load the one scenario file. Every test and the live app read backend/data/scenario.json."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .schema import Home, Snapshot, Task

SCENARIO_PATH = Path(__file__).resolve().parent.parent / "data" / "scenario.json"


@lru_cache(maxsize=1)
def load_raw() -> dict[str, Any]:
    with SCENARIO_PATH.open() as f:
        return json.load(f)


def scenario_tasks() -> list[Task]:
    return [Task(**t) for t in load_raw()["tasks"]]


def scenario_homes() -> list[Home]:
    return [Home(**h) for h in load_raw()["homes"]]


def tariff_prices(mode: str) -> list[float]:
    raw = load_raw()
    n = raw["slots"]
    if mode == "flat":
        return [raw["tariffs"]["flat"]["usd_per_kwh"]] * n
    tou = raw["tariffs"]["tou"]
    prices = [tou["offpeak_usd_per_kwh"]] * n
    for lo, hi in tou["peak_slot_ranges"]:
        for s in range(lo, hi):
            prices[s] = tou["peak_usd_per_kwh"]
    return prices


def tariff_label(mode: str) -> str:
    return load_raw()["tariffs"][mode]["label"]


def build_snapshot(
    *,
    tasks: list[Task],
    tariff_mode: str = "tou",
    generation: int = 0,
    requirements_version: int = 0,
    revision: int = 0,
) -> Snapshot:
    raw = load_raw()
    homes = scenario_homes()
    return Snapshot(
        scenario_id=raw["scenario_id"],
        generation=generation,
        requirements_version=requirements_version,
        revision=revision,
        horizon_start=raw["horizon_start"],
        slot_minutes=raw["slot_minutes"],
        slots=raw["slots"],
        capacity_kw=raw["capacity_kw"],
        capacity_tolerance_kw=raw["capacity_tolerance_kw"],
        tariff_mode=tariff_mode,
        tariff_label=tariff_label(tariff_mode),
        tariff_usd_per_kwh=tariff_prices(tariff_mode),
        background_kw_by_home={h.id: raw["background_kw_per_home"] for h in homes},
        homes=homes,
        tasks=list(tasks),
    )


def default_snapshot(tariff_mode: str = "tou") -> Snapshot:
    return build_snapshot(tasks=scenario_tasks(), tariff_mode=tariff_mode)
