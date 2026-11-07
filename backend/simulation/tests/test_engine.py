"""Engine checks against PRD §9.5-9.6 and §22. Reads the one scenario file."""

import pytest

from backend.simulation.engine import (
    cheap_timer_schedule, compare_schedules, compute_metrics, entry_for, evaluate_schedule,
    expensive_share_by_home, find_feasible_schedule, home_context, preferred_schedule, validate_schedule,
)
from backend.simulation.scenario import build_snapshot, default_snapshot, scenario_tasks
from backend.simulation.timefmt import clock_to_slot, slot_to_time

TOU = default_snapshot("tou")
FLAT = default_snapshot("flat")


def starts(schedule):
    return {e.task_id: e.start_slot for e in schedule}


def test_time_formatting():
    assert slot_to_time(0) == "6:00 PM"
    assert slot_to_time(12) == "9:00 PM"
    assert slot_to_time(15) == "9:45 PM"
    assert slot_to_time(24) == "12:00 AM"
    assert slot_to_time(28) == "1:00 AM"
    assert slot_to_time(48) == "6:00 AM"
    assert clock_to_slot(23) == 20 and clock_to_slot(7) == 52 and clock_to_slot(20) == 8
    assert clock_to_slot(18, as_deadline=True) == 96


def test_hand_checkable_examples():
    ev = next(t for t in scenario_tasks() if t.id == "a_ev")
    assert ev.power_kw * ev.duration_slots * 0.25 == pytest.approx(21.6)
    assert round(21.6 * 0.33, 2) == 7.13 and round(21.6 * 0.59, 2) == 12.74 and round(21.6 * 0.18, 2) == 3.89


def test_preferred_times_overload():
    m = compute_metrics(TOU, preferred_schedule(TOU))
    assert m.variable_cost_usd == pytest.approx(63.02, abs=0.005)
    assert m.peak_kw == pytest.approx(23.0)
    assert m.capacity_violations == 12
    assert m.tasks_completed == 6 and m.missed_deadlines == 0


def test_cheap_timer_piles_up():
    pref = compute_metrics(TOU, preferred_schedule(TOU))
    m = compute_metrics(TOU, cheap_timer_schedule(TOU))
    assert m.variable_cost_usd == pytest.approx(49.87, abs=0.005)
    assert m.peak_kw == pytest.approx(26.6)
    assert m.peak_kw > pref.peak_kw and m.capacity_violations > 0


def test_engine_first_plan_is_safe_but_unfair_to_b():
    r = find_feasible_schedule(TOU)
    assert r.ok
    m = compute_metrics(TOU, r.schedule)
    assert m.capacity_violations == 0 and m.missed_deadlines == 0
    assert m.peak_kw == pytest.approx(13.2)
    assert m.variable_cost_usd == pytest.approx(50.85, abs=0.005)
    dryer = starts(r.schedule)["b_dryer"]
    assert all(TOU.tariff_usd_per_kwh[s] == 0.59 for s in range(dryer, dryer + 3))  # B's dryer in expensive hours
    assert expensive_share_by_home(TOU, r.schedule)["B"] > 0.5
    assert starts(r.schedule)["a_ev"] == 12  # A's car takes 9:00 PM


@pytest.mark.parametrize("kw", ["pins", "preferred_overrides"])
def test_a_concession_fixes_it(kw):
    plan1 = find_feasible_schedule(TOU).schedule
    plan2 = find_feasible_schedule(TOU, **{kw: {"a_ev": 15}})  # A's car at 9:45 PM
    assert plan2.ok
    assert starts(plan2.schedule)["a_ev"] == 15
    assert starts(plan2.schedule)["b_dryer"] == 12
    m1, m2 = compute_metrics(TOU, plan1), compute_metrics(TOU, plan2.schedule)
    assert m2.capacity_violations == 0
    assert m2.variable_cost_usd == pytest.approx(49.87, abs=0.005)
    assert m2.per_home["B"].variable_cost_usd < m1.per_home["B"].variable_cost_usd
    assert m2.per_home["A"].variable_cost_usd == pytest.approx(m1.per_home["A"].variable_cost_usd)
    cmp = compare_schedules(TOU, plan1, plan2.schedule)
    assert cmp["per_home"]["B"]["cost_change_usd"] == pytest.approx(-0.97, abs=0.01)


def test_total_energy_constant_and_flat_control():
    schedules = [preferred_schedule(TOU), cheap_timer_schedule(TOU), find_feasible_schedule(TOU).schedule,
                 find_feasible_schedule(TOU, pins={"a_ev": 15}).schedule, find_feasible_schedule(FLAT).schedule]
    for s in schedules:
        assert compute_metrics(TOU, s).energy_kwh == pytest.approx(136.95)
        assert compute_metrics(FLAT, s).variable_cost_usd == pytest.approx(24.65, abs=0.005)
    assert compute_metrics(FLAT, find_feasible_schedule(FLAT).schedule).peak_kw == pytest.approx(10.8)
    assert all(v == 0 for v in expensive_share_by_home(FLAT, schedules[0]).values())


def test_impossible_deadline_car_by_8pm():
    tasks = [t.model_copy(update={"deadline_slot": 8}) if t.id == "a_ev" else t for t in scenario_tasks()]
    r = find_feasible_schedule(build_snapshot(tasks=tasks))
    assert not r.ok and r.status == "impossible"
    assert "8:00 PM" in r.reasons[0] and "3 hours" in r.reasons[0]


def test_car_by_11pm_is_feasible_and_squeezes_b():
    tasks = [t.model_copy(update={"deadline_slot": 20}) if t.id == "a_ev" else t for t in scenario_tasks()]
    snap = build_snapshot(tasks=tasks)
    r = find_feasible_schedule(snap)
    assert r.ok
    assert starts(r.schedule)["a_ev"] == 8  # 8:00 to 11:00 PM


def test_validator_rejects_bad_output():
    good = [{"task_id": e.task_id, "start_slot": e.start_slot} for e in find_feasible_schedule(TOU).schedule]
    assert validate_schedule(TOU, good) == []
    assert any("Unknown" in f for f in validate_schedule(TOU, good + [{"task_id": "z_pool", "start_slot": 0}]))
    assert any("missing" in f for f in validate_schedule(TOU, good[1:]))
    changed = [dict(good[0], duration_slots=2)] + good[1:]
    assert any("run time" in f for f in validate_schedule(TOU, changed))
    wrong_home = [dict(good[0], home_id="B")] + good[1:]
    assert any("wrong home" in f for f in validate_schedule(TOU, wrong_home))
    over = [{"task_id": t.id, "start_slot": 12} for t in TOU.tasks]
    assert any("over 15 kW" in f for f in validate_schedule(TOU, over))
    late = [dict(g, start_slot=20) if g["task_id"] == "a_ev" else g for g in good]
    assert any("deadline" in f for f in validate_schedule(TOU, late))
    assert validate_schedule(TOU, good, expected_generation=TOU.generation + 1)
    assert any("whole-number" in f for f in validate_schedule(TOU, [dict(good[0], start_slot=1.5)] + good[1:]))


def test_pin_that_breaks_capacity_is_rejected():
    r = find_feasible_schedule(TOU, pins={"a_ev": 12, "c_ev": 12})
    assert not r.ok and "over 15 kW" in r.reasons[0]


def test_home_context_only_own_tasks():
    ctx = home_context(TOU, "B")
    assert {t["id"] for t in ctx["tasks"]} == {"b_dryer", "b_dish"}
    with pytest.raises(ValueError):
        home_context(TOU, "Z")


def test_evaluate_schedule_summary():
    out = evaluate_schedule(TOU, [{"task_id": e.task_id, "start_slot": e.start_slot}
                                  for e in find_feasible_schedule(TOU).schedule])
    assert out["valid"] and "15 kW" in out["summary"]
    entry_for(TOU.tasks[0], 0)


def test_engine_api_dicts_for_mcp():
    import json
    from backend.simulation import engine_api as api
    snap = api.scenario_snapshot()
    json.dumps(snap)  # JSON-serializable for MCP
    for k in ("generation", "requirements_version", "capacity_kw", "tariff_mode", "tariff_label",
              "tariff_usd_per_kwh", "homes", "tasks", "background_kw_by_home", "baseline_schedule"):
        assert k in snap
    p1 = api.find_feasible_schedule(snap, pins=None, preferred_overrides=None)
    assert p1["ok"] and not p1["proven_impossible"]
    ev = api.evaluate_schedule(snap, p1["schedule"])
    assert ev["valid"] and ev["metrics"]["variable_cost_usd"] == pytest.approx(50.85, abs=0.005)
    assert set(ev["metrics"]["per_home"]) == {"A", "B", "C"}
    p2 = api.find_feasible_schedule(snap, {"a_ev": 15}, {})
    assert api.evaluate_schedule(snap, p2["schedule"])["metrics"]["per_home"]["B"]["variable_cost_usd"] == pytest.approx(12.70, abs=0.005)
    late = [dict(t, deadline_slot=8) if t["id"] == "a_ev" else t for t in snap["tasks"]]
    bad = api.find_feasible_schedule(dict(snap, tasks=late))
    assert not bad["ok"] and bad["proven_impossible"] and "8:00 PM" in bad["reasons"][0]
    assert api.evaluate_schedule(snap, p1["schedule"][1:])["valid"] is False
    minimal = {k: snap[k] for k in ("generation", "requirements_version", "capacity_kw", "tariff_mode", "tariff_label",
                                    "tariff_usd_per_kwh", "homes", "tasks", "background_kw_by_home")}
    assert api.find_feasible_schedule(minimal)["ok"]
    assert api.find_feasible_schedule({"nonsense": 1})["status"] == "bad_input"
    flat = api.scenario_snapshot("flat")
    assert api.evaluate_schedule(flat, p1["schedule"])["metrics"]["variable_cost_usd"] == pytest.approx(24.65, abs=0.005)


def test_reasons_say_car_charging_not_ev():
    tasks = [t.model_copy(update={"deadline_slot": 8}) if t.id == "a_ev" else t for t in scenario_tasks()]
    r = find_feasible_schedule(build_snapshot(tasks=tasks))
    assert "Home A's car charging needs 3 hours" in r.reasons[0] and "ev charging" not in r.reasons[0]
