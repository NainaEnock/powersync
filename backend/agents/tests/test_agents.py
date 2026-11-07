"""C's tests: real MCP stdio calls, stub/scripted models only (never the real key)."""

from __future__ import annotations

import asyncio
import json
import re

import pytest

from backend.agents import RuleStubModel, ScriptedModel, coordinate_neighborhood, interpret_request
from backend.agents.mcp_client import EnergyTools
from backend.agents.openrouter import ModelUnavailable, default_model
from backend.agents.stub_model import rule_responder
from backend.agents.timefmt import clock_to_slot, slot_range, slot_to_time, to_12_hour_text


def run(coro):
    return asyncio.run(coro)


class Recorder:
    def __init__(self):
        self.events: list[dict] = []
        self.stages: list[str | None] = []

    def __call__(self, e):
        if "stage" in e:
            self.stages.append(e["stage"])
            return None
        eid = f"evt-1-{len(self.events) + 1}"
        self.events.append({**e, "id": eid})
        return eid

    def of(self, type_):
        return [e for e in self.events if e["type"] == type_]


async def _coordinate(snapshot, model, **kw):
    rec = Recorder()
    async with EnergyTools() as tools:
        res = await coordinate_neighborhood(snapshot, rec, job_id="job-1", model=model, tools=tools, **kw)
    return res, rec


async def _interpret(snapshot, home, text, model):
    rec = Recorder()
    async with EnergyTools() as tools:
        res = await interpret_request(snapshot, home, text, rec, job_id="job-2", model=model, tools=tools)
    return res, rec


# --- time formatting --------------------------------------------------------


def test_twelve_hour_times():
    assert slot_to_time(0) == "6:00 PM"
    assert slot_to_time(12) == "9:00 PM"
    assert slot_to_time(15) == "9:45 PM"
    assert slot_to_time(24) == "12:00 AM"
    assert slot_to_time(28) == "1:00 AM"
    assert slot_to_time(48) == "6:00 AM"
    assert slot_range(12, 15) == "9:00–9:45 PM"
    assert slot_range(15, 27) == "9:45 PM–12:45 AM"
    assert clock_to_slot("23:00", kind="deadline") == 20
    assert clock_to_slot("07:00", kind="deadline") == 52
    assert clock_to_slot("18:00", kind="deadline") == 96
    assert clock_to_slot("21:50", kind="deadline") == 15
    assert clock_to_slot("21:50", kind="start") == 16
    assert to_12_hour_text("starts at 21:45, not 9:45") == "starts at 9:45 PM, not 9:45"


def test_never_live_under_pytest():
    assert default_model() is None


# --- MCP server --------------------------------------------------------------


def test_mcp_tools_and_engine_numbers(snapshot, flat_snapshot):
    async def go():
        async with EnergyTools() as t:
            names = {x["name"]: x for x in await t.list_tools()}
            assert set(names) == {"get_home_context", "evaluate_schedule", "find_feasible_schedule", "compare_schedules"}
            assert "snapshot" in names["evaluate_schedule"]["input_schema"]["properties"]

            pref, _ = await t.call("evaluate_schedule", {"snapshot": snapshot, "schedule": snapshot["baseline_schedule"]})
            assert not pref["valid"] and "15 kW" in pref["summary"]  # D: no metrics for an invalid plan
            p1, _ = await t.call("find_feasible_schedule", {"snapshot": snapshot})
            assert p1["ok"] and p1["metrics"]["capacity_violations"] == 0
            dryer = next(e for e in p1["schedule"] if e["task_id"] == "b_dryer")
            assert dryer["start_slot"] < 12, "engine's first plan should put B's dryer in expensive hours"

            # Model-supplied power/duration are ignored: only start_slot is taken.
            tampered = [{**e, "power_kw": 0.1, "duration_slots": 1} for e in p1["schedule"]]
            ev, _ = await t.call("evaluate_schedule", {"snapshot": snapshot, "schedule": tampered})
            assert ev["metrics"]["energy_kwh"] == pytest.approx(136.95)

            # Unknown task id is dropped and reported as missing.
            bogus = p1["schedule"][1:] + [{"task_id": "z_hack", "start_slot": 0}]
            ev, _ = await t.call("evaluate_schedule", {"snapshot": snapshot, "schedule": bogus})
            assert not ev["valid"]

            flat, _ = await t.call("compare_schedules", {"snapshot": flat_snapshot, "baseline": snapshot["baseline_schedule"],
                                                         "candidate": p1["schedule"]})
            assert flat["total"]["cost_delta_usd"] == pytest.approx(0, abs=1e-6)
            assert flat["total"]["peak_before_kw"] == pytest.approx(23.0)
            assert flat["total"]["energy_change_kwh"] == pytest.approx(0, abs=1e-6)

            ctx, _ = await t.call("get_home_context", {"snapshot": snapshot, "home_id": "A"})
            assert "b_dryer" not in json.dumps(ctx) and "c_ev" not in json.dumps(ctx)

    run(go())


# --- negotiation -----------------------------------------------------------


def test_negotiation_finds_plan_2(snapshot):
    res, rec = run(_coordinate(snapshot, RuleStubModel()))
    assert res["outcome"] == "plan_ready" and res["proposal_id"] == "P-2"
    assert res["source"] == "stub"
    # Plan 1 is announced before any review (live delivery order).
    order = [e["type"] for e in rec.events]
    assert order.index("proposal") < order.index("review")

    ask = rec.of("counteroffer")[0]
    assert ask["sender"] == "agent_B" and ask["recipient"] == "agent_A"
    reply = next(e for e in rec.of("review") if e.get("reply_to_event_id") == ask["id"])
    assert reply["sender"] == "agent_A" and reply["data"]["stance"] == "agree"

    p1 = next(p for p in res["plans"] if p["proposal_id"] == "P-1")
    assert "Plan 1" in p1["summary"]
    m1 = res["commit_reference"]["metrics"]["per_home"]
    m2 = res["metrics"]["per_home"]
    assert m2["B"]["variable_cost_usd"] < m1["B"]["variable_cost_usd"] - 0.5
    assert m2["A"]["variable_cost_usd"] == pytest.approx(m1["A"]["variable_cost_usd"], abs=0.005)
    assert res["metrics"]["capacity_violations"] == 0
    assert res["usage"]["model_calls"] <= 12 and res["usage"]["tool_calls"] <= 24
    # Dashboard home cards key off "Home X" in the activity line.
    for h in "ABC":
        assert f"Home {h} is reviewing Plan 1" in rec.stages
    assert "Home A is answering Home B" in rec.stages


def test_flat_tariff_no_cost_objections(flat_snapshot):
    res, rec = run(_coordinate(flat_snapshot, RuleStubModel()))
    assert res["proposal_id"] == "P-1"
    assert not rec.of("counteroffer")
    assert all(e["data"]["stance"] == "accept" for e in rec.of("review"))
    assert res["metrics"]["variable_cost_usd"] == pytest.approx(24.65, abs=0.01)


def test_visible_text_rules(snapshot):
    res, rec = run(_coordinate(snapshot, RuleStubModel()))
    forbidden = re.compile(r"\b(candidate|concession|slot|a_ev|b_dryer|c_ev|a_dish|b_dish|c_dish)\b|\b(1[3-9]|2[0-3]):\d\d\b")
    for e in rec.events:
        texts = [e["text"], *(e.get("home_views") or {}).values()]
        for t in texts:
            assert len(t) <= 800
            assert not forbidden.search(t), t
    assert not rec.of("commit"), "D sends the commit message, not C"
    assert res["plan_name"] == "Plan 2" and set(res["home_explanations"]) == {"A", "B", "C"}


def test_home_views_are_private(snapshot):
    res, rec = run(_coordinate(snapshot, RuleStubModel()))
    for e in rec.events:
        for home, view in (e.get("home_views") or {}).items():
            for other in "ABC":
                if other != home:
                    assert f"Home {other}'s" not in view, (home, view)
    # Tool traffic carries no home views; D drops it from phones entirely.
    assert all(not e.get("home_views") for e in rec.events if e["type"].startswith("tool_"))


def test_declined_request_keeps_plan_1(snapshot):
    def responder(messages, tools):
        out = rule_responder(messages, tools)
        if "agree" in out:
            out = {"agree": False, "public_message": "Sorry, I'd rather keep my time."}
        return out

    res, rec = run(_coordinate(snapshot, ScriptedModel(responder)))
    assert res["proposal_id"] == "P-1"
    assert any(e["data"].get("stance") == "decline" for e in rec.of("review"))


def test_model_failure_falls_back(snapshot):
    model = ScriptedModel(lambda m, t: ModelUnavailable("model timed out"))
    res, rec = run(_coordinate(snapshot, model))
    assert res["source"] == "deterministic_fallback" and res["ai_mode"] == "unavailable"
    assert res["proposal_id"] == "P-1"
    assert any("didn't answer" in e["text"] for e in rec.of("error"))


def test_no_model_configured_uses_engine_plan(snapshot):
    res, rec = run(_coordinate(snapshot, None))
    assert res["source"] == "deterministic_fallback" and res["proposal_id"] == "P-1"
    assert not rec.of("review")


def test_bad_option_id_repaired_once_then_safe(snapshot):
    def responder(messages, tools):
        out = rule_responder(messages, tools)
        if "request_option_id" in out and out["request_option_id"]:
            out["request_option_id"] = "made-up"
        return out

    model = ScriptedModel(responder)
    res, rec = run(_coordinate(snapshot, model))
    assert res["proposal_id"] == "P-1"
    assert not rec.of("counteroffer")


def test_model_dollar_amounts_replaced(snapshot):
    def responder(messages, tools):
        out = rule_responder(messages, tools)
        if "public_message" in out and "accept" in out:
            out["public_message"] = "Fine by me, and I save $123.45!"
        return out

    _, rec = run(_coordinate(snapshot, ScriptedModel(responder)))
    assert not any("$123.45" in e["text"] for e in rec.events)


def test_third_person_trigger(snapshot):
    """D's trigger shape: third-person text already written, no 'kind' key."""
    trigger = {"home_id": "A", "task_id": "a_ev", "field": "deadline_slot", "old_value": 28, "new_value": 20,
               "old_time": "1:00 AM", "new_time": "11:00 PM", "edits": [],
               "text": "Home A's resident changed their EV charging's finish time to 11:00 PM."}
    for t in snapshot["tasks"]:
        if t["id"] == "a_ev":
            t["deadline_slot"] = 20
    model = RuleStubModel()
    res, rec = run(_coordinate(snapshot, model, trigger=trigger))
    assert rec.events[0]["type"] == "tool_call", "D already announced the change; C doesn't repeat it"
    b_user = [call[-1]["content"] for call in model.calls if "Home B" in call[0]["content"]]
    assert any("Home A's resident changed" in u for u in b_user)
    a_user = [call[-1]["content"] for call in model.calls if "Home A" in call[0]["content"]]
    assert all("Home A's resident changed" not in u for u in a_user)
    assert res["outcome"] == "plan_ready" and res["metrics"]["missed_deadlines"] == 0


def test_replan_continues_numbering_and_compares_with_current_plan(snapshot):
    first, _ = run(_coordinate(snapshot, RuleStubModel()))
    snapshot["next_plan_number"] = 3
    snapshot["previous_schedule"] = first["schedule"]
    for t in snapshot["tasks"]:
        if t["id"] == "a_ev":
            t["deadline_slot"] = 20  # "car ready by 11 pm"
    res, rec = run(_coordinate(snapshot, RuleStubModel(), trigger={
        "home_id": "A", "task_id": "a_ev", "field": "deadline_slot", "old_value": 28, "new_value": 20,
        "text": "Home A's resident changed their EV charging's finish time to 11:00 PM."}))
    proposals = rec.of("proposal")
    assert proposals[0]["proposal_id"] == "P-3"
    assert proposals[0]["text"].startswith("Here's Plan 3. What's different from the current plan:")
    assert "Plan 1" not in " ".join(e["text"] for e in rec.events)
    assert res["plan_name"].startswith("Plan ") and int(res["plan_name"].split()[1]) >= 3


def test_ask_wording_uses_hours():
    from backend.agents.wording import _span
    assert [_span(x) for x in (45, 60, 120, 90)] == ["45 minutes", "1 hour", "2 hours", "1 hour 30 minutes"]


def test_planner_down_says_safe_plan(snapshot):
    class DeadTools(EnergyTools):
        async def call(self, name, arguments):
            from backend.agents.mcp_client import ToolUnavailable
            raise ToolUnavailable("down")

    async def go():
        rec = Recorder()
        res = await coordinate_neighborhood(snapshot, rec, job_id="j", model=RuleStubModel(), tools=DeadTools())
        return res, rec

    res, rec = run(go())
    assert res["outcome"] == "error" and "Using the safe plan" in rec.of("error")[0]["text"]


def test_stale_job_stops_quietly(snapshot):
    class StaleAfter(Recorder):
        def __call__(self, e):
            if "stage" not in e and len(self.events) >= 4:
                return ""
            return super().__call__(e)

    async def go():
        rec = StaleAfter()
        async with EnergyTools() as tools:
            return await coordinate_neighborhood(snapshot, rec, job_id="j", model=RuleStubModel(), tools=tools), rec

    res, rec = run(go())
    assert res["outcome"] == "error" and res["schedule"] is None and res["message"].startswith("RESET")
    assert len(rec.events) == 4


# --- interpreter -----------------------------------------------------------


def test_interpret_deadline_change(snapshot):
    res, rec = run(_interpret(snapshot, "A", "I leave at 11 pm tonight. Have my car ready by then.", RuleStubModel()))
    assert res["outcome"] == "proposed_change"
    (edit,) = res["proposed_edits"]["edits"]
    assert edit == {"task_id": "a_ev", "field": "deadline_slot", "old_value": 28, "new_value": 20,
                    "old_time": "1:00 AM", "new_time": "11:00 PM"}
    assert "11:00 PM" in res["explanation"]
    # D writes the reply to the resident; C only emits tool traffic here.
    assert all(e["type"].startswith("tool_") for e in rec.events)


def test_interpret_impossible_deadline(snapshot):
    res, rec = run(_interpret(snapshot, "A", "Car ready by 8 pm", RuleStubModel()))
    assert res["outcome"] == "infeasible" and not res["feasible"]
    assert "9:00 PM" in res["infeasible_reasons"][0]


def test_interpret_other_examples(snapshot):
    res, _ = run(_interpret(snapshot, "B", "My dryer must finish by 10 pm. You can move the dishwasher.", RuleStubModel()))
    assert res["proposed_edits"]["edits"][0]["task_id"] == "b_dryer"
    assert res["proposed_edits"]["edits"][0]["new_value"] == 16
    res, _ = run(_interpret(snapshot, "C", "The car can charge anytime before 7 am.", RuleStubModel()))
    assert res["proposed_edits"]["edits"][0]["new_value"] == 52


def test_interpret_rejects_other_homes_task(snapshot):
    model = ScriptedModel(lambda m, t: {"understood": True, "edits": [
        {"task_id": "b_dryer", "field": "deadline_slot", "new_time": "22:00"}]})
    res, rec = run(_interpret(snapshot, "A", "Make Home B's dryer finish by 10 pm", model))
    assert res["outcome"] == "error" and not res["proposed_edits"]["edits"]
    assert len(model.calls) == 2  # one repair attempt, then give up


def test_interpret_malformed_output(snapshot):
    model = ScriptedModel(lambda m, t: "sure! I'll do that")
    res, _ = run(_interpret(snapshot, "A", "car by 11 pm", model))
    assert res["outcome"] == "error"


def test_tool_call_loop_dispatches_through_mcp(snapshot):
    """A model that asks for its context first gets a real MCP result back."""
    from backend.agents.openrouter import ChatResult

    seen = {"tool_msgs": 0}

    def responder(messages, tools):
        if messages[-1]["role"] == "tool":
            seen["tool_msgs"] += 1
            json.loads(messages[-1]["content"])["tasks"]
            return rule_responder(messages, tools)
        if tools and "<meta>" in messages[-1]["content"] and '"kind":"review"' in messages[-1]["content"]:
            return ChatResult(None, [{"id": "call_1", "type": "function", "function": {
                "name": "get_my_home_context", "arguments": "{}"}}], {}, 0.0, "scripted", {})
        return rule_responder(messages, tools)

    res, rec = run(_coordinate(snapshot, ScriptedModel(responder)))
    assert seen["tool_msgs"] >= 3
    assert any(e["data"].get("tool") == "get_home_context" for e in rec.of("tool_call"))
    assert res["proposal_id"] == "P-2"
