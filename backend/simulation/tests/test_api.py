"""API flows with the stub agents (never the real model)."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from backend.simulation.agent_seam import CoordinateResult, InterpretResult, stub_coordinate

TOKENS = {"DEMO_ADMIN_TOKEN": "adm", "DEMO_HOME_A_TOKEN": "ta", "DEMO_HOME_B_TOKEN": "tb", "DEMO_HOME_C_TOKEN": "tc"}


def make_client(monkeypatch, tokens=None, interpret=None, coordinate=None, announce=None):
    monkeypatch.setenv("POWERSYNC_AGENT_IMPL", "stub")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    for k in TOKENS:
        monkeypatch.setenv(k, (tokens or {}).get(k, ""))
    from backend import main
    app = main.create_app()
    if interpret or coordinate:
        i, c, impl = app.state.impl
        app.state.impl = (interpret or i, coordinate or c, impl)
    app.state.announce = announce
    main._hits.clear()
    return TestClient(app)


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


def wait_job(c, jid, until=("completed", "failed", "awaiting_confirmation"), timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = c.get(f"/api/jobs/{jid}").json()
        if j["status"] in until:
            return j
        time.sleep(0.02)
    raise AssertionError(f"job {jid} stuck: {j}")


def send(c, home, text, rid, headers=None):
    r = c.post("/api/message", json={"home_id": home, "text": text, "request_id": rid, "expected_revision": 0},
               headers=headers or {})
    assert r.status_code == 202, r.text
    return r.json()


@pytest.fixture
def client(monkeypatch):
    with make_client(monkeypatch) as c:
        yield c


def test_health_and_initial_state(client):
    h = client.get("/api/health").json()
    assert h["auth_mode"] == "dev-open" and h["agent_impl"] == {"interpret": "stub", "coordinate": "stub"}
    s = client.get("/api/state").json()
    assert s["coordinated_schedule"] is None and s["tariff_mode"] == "tou"
    assert s["metrics"]["baseline"]["variable_cost_usd"] == pytest.approx(63.02, abs=0.005)
    assert s["metrics"]["independent"]["peak_kw"] == pytest.approx(26.6)
    assert len(s["tariff_usd_per_kwh"]) == 96 and len(s["demand_kw"]["baseline"]) == 96
    assert client.get("/api/health").headers["cache-control"] == "no-store"


def test_coordinate_commits_plan_and_events(client):
    r0 = client.get("/api/state").json()["revision"]
    j = client.post("/api/coordinate", json={}).json()
    job = wait_job(client, j["job_id"])
    assert job["status"] == "completed" and job["result"]["outcome"] == "committed"
    s = client.get("/api/state").json()
    assert s["revision"] == r0 + 1
    assert s["metrics"]["coordinated"]["variable_cost_usd"] == pytest.approx(50.85, abs=0.005)
    assert s["coordination"]["source"] == "stub"
    types = [e["type"] for e in sorted(s["events"], key=lambda e: e["sequence"])]
    assert types[0] == "proposal" and types[-2:] == ["validation", "commit"]
    assert all("home_views" not in e for e in s["events"])
    assert "Plan 1" in s["events"][0]["text"] and "9:00 PM" in s["events"][0]["text"]


def test_message_confirm_flow_and_privacy(client):
    j = send(client, "A", "I leave at 11 pm tonight. Have my car ready by then.", "phone-a-1")
    job = wait_job(client, j["job_id"])
    assert job["status"] == "awaiting_confirmation"
    sa = client.get("/api/state?home=A").json()
    pc = sa["pending_changes"][0]
    e = pc["proposed_edits"]["edits"][0]
    assert (e["task_id"], e["field"], e["old_time"], e["new_time"]) == ("a_ev", "deadline_slot", "1:00 AM", "11:00 PM")
    assert pc["feasible"]
    rev = sa["revision"]
    r = client.post("/api/action", json={"home_id": "A", "action": "confirm_change", "pending_change_id": pc["id"],
                                         "request_id": "phone-a-2", "expected_revision": rev})
    assert r.status_code == 202
    done = wait_job(client, r.json()["job_id"])
    assert done["result"]["outcome"] == "applied"
    assert wait_job(client, j["job_id"])["result"]["outcome"] == "applied"
    s = client.get("/api/state").json()
    assert s["revision"] == rev + 1 and s["requirements_version"] == 1
    assert next(t for t in s["tasks"] if t["id"] == "a_ev")["deadline_slot"] == 20

    # Privacy: A's view holds nothing of B or C.
    sa = client.get("/api/state?home=A").json()
    assert {t["home_id"] for t in sa["tasks"]} == {"A"}
    for k in ("baseline_schedule", "independent_schedule", "coordinated_schedule"):
        assert {e["home_id"] for e in sa[k]} == {"A"}
    for k in ("metrics", "metrics_flat_rate"):
        for m in sa[k].values():
            if m:
                assert set(m["per_home"]) == {"A"}
    assert set(sa["background_kw_by_home"]) == {"A"}
    blob = " ".join(e["text"] for e in sa["events"]).lower()
    assert "dryer" not in blob and "home b" not in blob and "home c" not in blob
    assert all(e["type"] not in ("tool_call", "tool_result") for e in sa["events"])
    sb = client.get("/api/state?home=B").json()
    assert "i leave at 11 pm" not in " ".join(e["text"] for e in sb["events"]).lower()
    assert "your car" not in " ".join(e["text"] for e in sb["events"]).lower()


def test_impossible_deadline(client):
    j = send(client, "A", "Car ready by 8 pm", "phone-a-x")
    job = wait_job(client, j["job_id"])
    assert job["status"] == "completed" and job["result"]["outcome"] == "infeasible"
    pc = client.get("/api/state?home=A").json()["pending_changes"][0]
    assert not pc["feasible"] and "8:00 PM" in pc["explanation"]
    r = client.post("/api/action", json={"home_id": "A", "action": "confirm_change", "pending_change_id": pc["id"],
                                         "request_id": "x2"})
    assert r.status_code == 400
    r = client.post("/api/action", json={"home_id": "A", "action": "reject_change", "pending_change_id": pc["id"],
                                         "request_id": "x3"})
    assert r.status_code == 202 and client.get("/api/state?home=A").json()["pending_changes"] == []


def test_duplicate_request_id(client):
    a = send(client, "C", "The car can charge anytime before 7 am.", "dup-1")
    b = client.post("/api/message", json={"home_id": "C", "text": "x", "request_id": "dup-1"}).json()
    assert b["job_id"] == a["job_id"] and b["duplicate"] is True


def test_tariff_toggle_and_reset(client):
    wait_job(client, client.post("/api/coordinate").json()["job_id"])
    r = client.post("/api/tariff", json={"tariff_mode": "flat"}).json()
    s = client.get("/api/state").json()
    assert r["tariff_mode"] == "flat" and s["coordination"]["status"] == "stale_tariff"
    wait_job(client, client.post("/api/coordinate").json()["job_id"])
    s = client.get("/api/state").json()
    assert s["metrics"]["coordinated"]["variable_cost_usd"] == pytest.approx(24.65, abs=0.005)
    assert s["metrics"]["coordinated"]["peak_kw"] == pytest.approx(10.8)
    assert s["coordination"]["tariff_mode"] == "flat"
    rev, gen = s["revision"], s["generation"]
    out = client.post("/api/reset").json()
    s = client.get("/api/state").json()
    assert out["tariff_mode"] == "tou" and s["revision"] > rev and s["generation"] == gen + 1
    assert s["coordinated_schedule"] is None and s["events"] == []


def test_auth_enforced(monkeypatch):
    with make_client(monkeypatch, tokens=TOKENS) as c:
        assert c.get("/api/health").json()["auth_mode"] == "enforced"
        assert c.get("/api/state?home=A").status_code == 401
        r = c.get("/api/state?home=A", headers=H("tb"))
        assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"
        assert c.get("/api/state?home=A", headers=H("ta")).status_code == 200
        assert c.get("/api/state?home=A", headers=H("adm")).status_code == 200
        assert c.get("/api/state").status_code == 401  # whole dashboard view needs admin (B, G2)
        assert c.get("/api/state", headers=H("ta")).status_code == 403
        assert c.get("/api/state", headers=H("adm")).json()["events_hidden"] is False
        assert c.post("/api/coordinate", headers=H("ta")).status_code == 403
        assert c.post("/api/reset").status_code == 401
        r = c.post("/api/message", json={"home_id": "B", "text": "hi", "request_id": "r"}, headers=H("ta"))
        assert r.status_code == 403
        assert c.get("/api/state?home=Z", headers=H("adm")).json()["error"]["code"] == "UNKNOWN_HOME"


def test_errors_shape(client):
    r = client.post("/api/message", json={"home_id": "A"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "BAD_REQUEST"
    r = client.post("/api/message", content=b"x" * 20000, headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert client.get("/api/jobs/nope").json()["error"]["code"] == "NOT_FOUND"
    assert client.get("/api/nothing").status_code == 404


def test_stale_change_after_other_confirm(client):
    j1 = send(client, "A", "Car ready by 11 pm", "s1")
    wait_job(client, j1["job_id"])
    pc1 = client.get("/api/state?home=A").json()["pending_changes"][0]
    j2 = send(client, "A", "Car ready by 10 pm", "s2")  # supersedes pc1
    wait_job(client, j2["job_id"])
    r = client.post("/api/action", json={"home_id": "A", "action": "confirm_change", "pending_change_id": pc1["id"],
                                         "request_id": "s3"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_REVISION"


def test_reset_during_job_discards_late_result(monkeypatch):
    async def slow_coordinate(ctx, emit):
        await asyncio.sleep(0.5)
        return await stub_coordinate(ctx, emit)
    with make_client(monkeypatch, coordinate=slow_coordinate) as c:
        jid = c.post("/api/coordinate").json()["job_id"]
        assert c.post("/api/coordinate").json()["error"]["code"] == "JOB_RUNNING"
        assert c.post("/api/tariff", json={"tariff_mode": "flat"}).status_code == 409
        c.post("/api/reset")
        time.sleep(0.8)
        s = c.get("/api/state").json()
        assert s["coordinated_schedule"] is None and s["events"] == []
        assert c.get(f"/api/jobs/{jid}").status_code == 404


def test_bad_agent_plan_falls_back(monkeypatch):
    async def bad(ctx, emit):
        return CoordinateResult(schedule=[{"task_id": t.id, "start_slot": 12} for t in ctx.snapshot.tasks],
                                proposal_id="P-1", source="live")
    with make_client(monkeypatch, coordinate=bad) as c:
        job = wait_job(c, c.post("/api/coordinate").json()["job_id"])
        s = c.get("/api/state").json()
        assert job["result"]["source"] == "deterministic_fallback"
        assert s["coordination"]["source"] == "deterministic_fallback" and s["ai_mode"] == "unavailable"
        assert s["metrics"]["coordinated"]["capacity_violations"] == 0
        assert any(e["type"] == "error" and "safety check" in e["text"] for e in s["events"])


def test_agent_timeout_falls_back(monkeypatch):
    monkeypatch.setenv("POWERSYNC_AGENT_TIMEOUT_S", "0.1")

    async def hang(ctx, emit):
        await asyncio.sleep(5)
    with make_client(monkeypatch, coordinate=hang) as c:
        job = wait_job(c, c.post("/api/coordinate").json()["job_id"])
        assert job["result"]["source"] == "deterministic_fallback"
        assert any("didn't answer in time" in e["text"] for e in c.get("/api/state").json()["events"])


def test_interpreter_editing_another_home_is_rejected(monkeypatch):
    async def evil(ctx, emit):
        return InterpretResult(outcome="edits", edits=[{"task_id": "b_dryer", "field": "deadline_slot", "new_value": 4}])
    with make_client(monkeypatch, interpret=evil) as c:
        job = wait_job(c, send(c, "A", "move B's dryer", "e1")["job_id"])
        assert job["status"] == "failed" and job["error"].startswith("BAD_MODEL_OUTPUT")
        assert c.get("/api/state?home=A").json()["pending_changes"] == []


def test_three_phone_burst(client):
    jobs = [send(client, h, t, f"burst-{h}") for h, t in
            [("A", "Car ready by 11 pm"), ("B", "My dryer must finish by 10 pm. You can move the dishwasher."),
             ("C", "The car can charge anytime before 7 am.")]]
    for j in jobs:
        assert wait_job(client, j["job_id"])["status"] == "awaiting_confirmation"
    for h in "ABC":
        assert len(client.get(f"/api/state?home={h}").json()["pending_changes"]) == 1


# ---------------------------------------------------------------- C's interface through the adapter

from backend.simulation.agent_seam import adapt_announce, adapt_coordinate, adapt_interpret  # noqa: E402
from backend.simulation.engine_api import find_feasible_schedule as api_find  # noqa: E402


def test_c_style_agents_full_flow(monkeypatch):
    seen = {}

    def c_interpret(snapshot, home_id, text, emit, job_id=None):  # sync on purpose
        assert isinstance(snapshot, dict) and len(snapshot["tariff_usd_per_kwh"]) == 96
        assert "baseline_schedule" in snapshot
        return {"outcome": "proposed_change", "explanation": "Have your car ready by 11:00 PM instead of 1:00 AM?",
                "proposed_edits": {"edits": [{"task_id": "a_ev", "field": "deadline_slot", "old_value": 28,
                                              "new_value": 20, "old_time": "1:00 AM", "new_time": "11:00 PM"}]}}

    async def c_coordinate(snapshot, emit, job_id=None, trigger=None):
        seen["trigger"] = trigger
        emit({"stage": "Home B is reviewing Plan 1"})
        p1 = api_find(snapshot)
        eid = emit({"sender": "coordinator", "recipient": "all_agents", "type": "proposal", "text": "Here's Plan 1.",
                    "home_views": {"A": "Plan 1 for A", "B": "Plan 1 for B", "C": "Plan 1 for C"},
                    "round": 1, "proposal_id": "P-1", "source": "system_template"})
        ask = emit({"sender": "agent_B", "recipient": "agent_A", "type": "counteroffer", "round": 1,
                    "text": "Home A, could your car start 45 minutes later?", "reply_to_event_id": eid,
                    "proposal_id": "P-1", "source": "model"})
        emit({"sender": "agent_A", "recipient": "agent_B", "type": "review", "round": 1, "text": "Sure.",
              "reply_to_event_id": ask, "proposal_id": "P-1", "source": "model"})
        emit({"sender": "agent_B", "recipient": "powersync-energy", "type": "tool_call", "text": "Checking Plan 1"})
        assert p1["ok"]
        p2 = api_find(snapshot, pins={"a_ev": 15}) if trigger is None else p1
        return {"schedule": p2["schedule"], "proposal_id": "P-2", "plan_name": "Plan 2", "source": "live"}

    async def c_announce(snapshot, result, emit, job_id=None):
        emit({"sender": "coordinator", "recipient": "all_agents", "type": "commit", "text": "Plan 2 is set.",
              "home_views": {h: f"Plan 2 is set for {h}." for h in "ABC"}, "proposal_id": result["proposal_id"],
              "source": "system_template"})

    with make_client(monkeypatch, interpret=adapt_interpret(c_interpret), coordinate=adapt_coordinate(c_coordinate),
                     announce=adapt_announce(c_announce)) as c:
        job = wait_job(c, c.post("/api/coordinate").json()["job_id"])
        assert job["result"]["outcome"] == "committed" and job["result"]["source"] == "live"
        s = c.get("/api/state").json()
        assert s["metrics"]["coordinated"]["per_home"]["B"]["variable_cost_usd"] == pytest.approx(12.70, abs=0.005)
        assert s["coordination"]["plan_name"] == "Plan 2" and s["ai_mode"] == "live"
        texts = [e["text"] for e in s["events"]]
        assert "Plan 2 is set." in texts and not any("street's plan" in t for t in texts)  # C announced, not D
        assert seen["trigger"] is None

        # Privacy (C's rule): A sees B's request to it, its own reply, and its own home_views text; never tool events.
        a = [e["text"] for e in c.get("/api/state?home=A").json()["events"]]
        assert "Plan 1 for A" in a and "Home A, could your car start 45 minutes later?" in a and "Sure." in a
        assert "Plan 1 for B" not in a and "Checking Plan 1" not in a
        cview = [e["text"] for e in c.get("/api/state?home=C").json()["events"]]
        assert "Sure." not in cview and "Plan 1 for C" in cview

        j = send(c, "A", "car by 11", "c1")
        assert wait_job(c, j["job_id"])["result"]["outcome"] == "proposed_change"
        pc = c.get("/api/state?home=A").json()["pending_changes"][0]
        r = c.post("/api/action", json={"home_id": "A", "action": "confirm_change", "pending_change_id": pc["id"],
                                        "request_id": "c2"})
        assert wait_job(c, r.json()["job_id"])["result"]["outcome"] == "applied"
        t = seen["trigger"]
        assert t["home_id"] == "A" and t["task_id"] == "a_ev" and t["new_value"] == 20 and t["new_time"] == "11:00 PM"
        assert t["text"].startswith("Home A's resident changed")


def test_c_style_clarification_and_error(monkeypatch):
    async def ask(snapshot, home_id, text, emit, job_id=None):
        return {"outcome": "needs_clarification", "message": "Which appliance do you mean?"}
    with make_client(monkeypatch, interpret=adapt_interpret(ask)) as c:
        job = wait_job(c, send(c, "B", "do the thing", "q1")["job_id"])
        assert job["result"]["outcome"] == "needs_clarification" and "Which appliance" in job["result"]["message"]

    async def broken(snapshot, home_id, text, emit, job_id=None):
        return {"outcome": "error", "message": "model timeout"}
    with make_client(monkeypatch, interpret=adapt_interpret(broken)) as c:
        job = wait_job(c, send(c, "A", "Car ready by 11 pm", "q2")["job_id"])
        assert job["result"]["outcome"] == "proposed_change"  # backup reader took over, and said so
        assert any("backup reader" in e["text"] for e in c.get("/api/state?home=A").json()["events"])


def test_interpreter_reply_source_labels(monkeypatch):
    async def templ(snapshot, home_id, text, emit, job_id=None):
        return {"outcome": "proposed_change", "source": "live", "explanation": "Change your car charging finish time?",
                "proposed_edits": {"edits": [{"task_id": "a_ev", "field": "deadline_slot", "new_value": 20}]}}

    async def question(snapshot, home_id, text, emit, job_id=None):
        return {"outcome": "needs_clarification", "source": "live", "message": "Which appliance do you mean?"}

    for fn, want in ((templ, "system_template"), (question, "model")):
        with make_client(monkeypatch, interpret=adapt_interpret(fn)) as c:
            wait_job(c, send(c, "A", "car by 11", "s-" + want)["job_id"])
            replies = [e for e in c.get("/api/state?home=A").json()["events"] if e["sender"] == "agent_A"]
            assert replies and replies[-1]["source"] == want


def test_events_visible_before_job_ends(monkeypatch):
    """G7: Plan 1 reaches /api/state while the coordination job is still running."""
    async def slow(snapshot, emit, job_id=None, trigger=None):
        emit({"stage": "Home B is reviewing Plan 1"})
        emit({"sender": "coordinator", "recipient": "all_agents", "type": "proposal", "text": "Here's Plan 1.",
              "home_views": {h: "Here's Plan 1." for h in "ABC"}, "round": 1, "proposal_id": "P-1"})
        await asyncio.sleep(0.6)
        return {"schedule": api_find(snapshot)["schedule"], "proposal_id": "P-1", "source": "live"}
    with make_client(monkeypatch, coordinate=adapt_coordinate(slow)) as c:
        jid = c.post("/api/coordinate").json()["job_id"]
        time.sleep(0.2)
        s = c.get("/api/state").json()
        assert c.get(f"/api/jobs/{jid}").json()["status"] == "running"
        assert any(e["text"] == "Here's Plan 1." for e in s["events"])
        assert s["activity"] == "Home B is reviewing Plan 1" and s["job_status"] == "running"
        assert c.get("/api/state?home=B").json()["activity"] == "Planning with the neighbors…"
        assert wait_job(c, jid)["status"] == "completed"
        assert c.get("/api/state").json()["activity"] is None


def test_plan_numbers_continue_after_a_multi_plan_job(monkeypatch):
    """A job that proposes Plan 1 and commits Plan 2 must make the next replan 'Plan 3' (not 'Plan 2' again)."""
    seen = []

    async def two_plans(ctx, emit):
        seen.append(ctx.next_plan_number)
        base = await stub_coordinate(ctx, lambda e: "")
        n = ctx.next_plan_number
        return base.model_copy(update={
            "proposal_id": f"P-{n + 1}", "plan_name": f"Plan {n + 1}",
            "raw": {"plans": [{"proposal_id": f"P-{n}"}, {"proposal_id": f"P-{n + 1}"}]},
        })

    with make_client(monkeypatch, coordinate=two_plans) as c:
        wait_job(c, c.post("/api/coordinate", json={}).json()["job_id"])
        assert c.get("/api/state").json()["coordination"]["plan_name"] == "Plan 2"
        wait_job(c, c.post("/api/coordinate", json={}).json()["job_id"])
        assert seen == [1, 3]
        assert c.get("/api/state").json()["coordination"]["plan_name"] == "Plan 4"


def test_engine_verdict_decides_the_wording(monkeypatch):
    """If the interpreter says "I can't" but the engine finds the change feasible, the resident must
    see a normal confirm question, not "I can't ..." next to a Confirm button."""
    async def says_impossible(ctx, emit):
        return InterpretResult(
            outcome="edits", edits=[{"task_id": "a_ev", "field": "deadline_slot", "new_value": 20}],
            explanation="I can't change the finish time for your car charging from 1:00 AM to 11:00 PM.",
            claimed_feasible=False, source="live",
        )

    with make_client(monkeypatch, interpret=says_impossible) as c:
        j = wait_job(c, c.post("/api/message", json={"home_id": "A", "text": "car by 11", "request_id": "w-1"}).json()["job_id"])
        assert j["status"] == "awaiting_confirmation"
        pc = [p for p in c.get("/api/state?home=A").json()["pending_changes"] if p["status"] == "pending"][0]
        assert pc["feasible"] is True
        assert pc["explanation"].startswith("Change ")
        assert "can't" not in j["result"]["message"]


def test_residents_add_and_remove_appliances(monkeypatch):
    with make_client(monkeypatch) as c:
        cat = c.get("/api/appliances/catalog").json()
        kinds = {a["kind"] for a in cat["schedulable"]}
        assert {"washer", "water_heater", "ac", "pool_pump"} <= kinds and "microwave" not in kinds

        wait_job(c, c.post("/api/coordinate", json={}).json()["job_id"])
        rev = c.get("/api/state").json()["revision"]

        r = c.post("/api/appliances", json={"home_id": "A", "action": "add", "kind": "washer", "deadline_slot": 16})
        assert r.status_code == 200 and r.json()["task_id"] == "a_washer"
        s = c.get("/api/state").json()
        assert s["revision"] == rev + 1
        assert s["coordinated_schedule"] is None and s["coordination"]["status"] == "not_run"
        assert "Coordinate again" in s["coordination"]["reasons"][0]
        washer = next(t for t in s["tasks"] if t["id"] == "a_washer")
        assert washer["deadline_slot"] == 16 and washer["power_kw"] == 0.5
        assert s["metrics"]["baseline"]["tasks_total"] == 7

        # Privacy: Home B never sees Home A's new appliance or its wording.
        b = c.get("/api/state?home=B").json()
        assert all(t["home_id"] == "B" for t in b["tasks"])
        assert not any("washing machine" in e["text"] for e in b["events"])

        # The planner covers the new appliance.
        wait_job(c, c.post("/api/coordinate", json={}).json()["job_id"])
        s = c.get("/api/state").json()
        assert any(e["task_id"] == "a_washer" for e in s["coordinated_schedule"])
        assert s["metrics"]["coordinated"]["tasks_completed"] == 7

        assert c.post("/api/appliances", json={"home_id": "B", "action": "remove", "task_id": "a_washer"}).status_code == 403
        assert c.post("/api/appliances", json={"home_id": "A", "action": "add", "kind": "ev", "deadline_slot": 4}).status_code == 400
        assert c.post("/api/appliances", json={"home_id": "A", "action": "add", "kind": "microwave"}).status_code == 400
        assert c.post("/api/appliances", json={"home_id": "A", "action": "remove", "task_id": "a_washer"}).status_code == 200
        assert not any(t["id"] == "a_washer" for t in c.get("/api/state").json()["tasks"])

        c.post("/api/appliances", json={"home_id": "C", "action": "add", "kind": "pool_pump"})
        c.post("/api/reset", json={})
        assert len(c.get("/api/state").json()["tasks"]) == 6  # reset restores the original scenario


def test_appliance_changes_need_the_home_code(monkeypatch):
    toks = {"DEMO_ADMIN_TOKEN": "ta", "DEMO_HOME_A_TOKEN": "t1", "DEMO_HOME_B_TOKEN": "t2", "DEMO_HOME_C_TOKEN": "t3"}
    with make_client(monkeypatch, tokens=toks) as c:
        body = {"home_id": "A", "action": "add", "kind": "washer"}
        assert c.post("/api/appliances", json=body).status_code == 401
        assert c.post("/api/appliances", json=body, headers=H("t2")).status_code == 403
        assert c.post("/api/appliances", json=body, headers=H("t1")).status_code == 200
