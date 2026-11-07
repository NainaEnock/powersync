"""API flows with the stub agents (never the real model)."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from backend.simulation.agent_seam import CoordinateResult, InterpretResult, stub_coordinate

TOKENS = {"DEMO_ADMIN_TOKEN": "adm", "DEMO_HOME_A_TOKEN": "ta", "DEMO_HOME_B_TOKEN": "tb", "DEMO_HOME_C_TOKEN": "tc"}


def make_client(monkeypatch, tokens=None, interpret=None, coordinate=None):
    monkeypatch.setenv("POWERSYNC_AGENT_IMPL", "stub")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    for k in TOKENS:
        monkeypatch.setenv(k, (tokens or {}).get(k, ""))
    from backend import main
    app = main.create_app()
    if interpret or coordinate:
        i, c, impl = app.state.impl
        app.state.impl = (interpret or i, coordinate or c, impl)
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
        pub = c.get("/api/state").json()
        assert pub["events_hidden"] is True and pub["events"] == []
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
