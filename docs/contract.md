# PowerSync contract (D owns; wins over the PRD where they differ)

Status: **v1, implemented and tested** on `feat/backend-scheduler` (`python -m pytest backend -q`: 28 passed).
Field names follow PRD §10 exactly. Additions beyond the PRD are marked **ADDED**. To change anything here, post
`field → change → affected owners → test to rerun` in Build status first.

Run: `source .venv/bin/activate && pip install -r backend/requirements.txt` then
`python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000` from the repo root.

## 1. Decisions

| Topic | Decision |
|---|---|
| §11.3 public-schedule gap | **Accept the gap.** `GET /api/state` without `home` returns every schedule and metric (the charts need it), but `events` and `pending_changes` are empty and `events_hidden: true` unless the admin token is sent. "The projector is the operator's screen." Phones always use `?home=`. |
| Who serves the build | FastAPI serves `frontend/dist` if it exists. `/api/*` routes come first, then `/assets`, then a fallback to `index.html` for `/phone`, `/dashboard`, and anything else. `index.html`, `sw.js`, `workbox-*`, and the manifest use `no-cache`. Every `/api` response uses `no-store`. |
| Infeasible requests (A's question) | They **leave a pending change** with `feasible: false`, `explanation`, and `infeasible_reasons`. The phone's **OK** button sends `reject_change` to clear it. `confirm_change` on it returns 400. |
| `expected_revision` | Optional and informational on `/api/message`. Confirmations go stale by **field values** (PRD §11.5.4), not raw revision: if an edited field no longer has `old_value`, confirm returns `409 STALE_REVISION`. |
| One open change per home | A new request from a home marks that home's older pending change `stale`. |
| Wrong code | No `Authorization` header → `401 UNAUTHORIZED`. A header that doesn't match this home → `403 FORBIDDEN` (typos included). The admin token works for every home. |
| Home colors | A `#2563eb`, B `#d97706`, C `#059669` (in `state.homes[].color`). |

## 2. Endpoints

All bodies are JSON. Errors are always `{"error":{"code","message"}}` (PRD §11.2). Bodies over 16 KB → `413 PAYLOAD_TOO_LARGE`. More than 20 POSTs in 10 s per home (or admin) → `429 RATE_LIMITED`.

| Method, path | Auth | Body | Returns |
|---|---|---|---|
| `GET /api/health` | none | | `{status, version, scenario_id, revision, generation, auth_mode, agent_impl, openrouter_configured, model}` |
| `GET /api/state` | admin for events | | Dashboard view (§3) |
| `GET /api/state?home=A` | A's token or admin | | Household view (§4) |
| `POST /api/message` | home | `{"home_id":"A","text":"…","request_id":"phone-a-<uuid>","expected_revision":3}` | `202 {job_id, status, accepted_revision}` |
| `POST /api/action` | home | `{"home_id":"A","action":"confirm_change"\|"reject_change","pending_change_id":"pc-…","request_id":"phone-a-<uuid>","expected_revision":4}` | `202 {job_id, status, accepted_revision}` |
| `POST /api/coordinate` | admin | `{}` | `202 {job_id, status, accepted_revision}` |
| `POST /api/tariff` | admin | `{"tariff_mode":"tou"\|"flat"}` | `200 {revision, tariff_mode}` |
| `GET /api/jobs/{id}` | none | | Job (PRD §10) |
| `POST /api/reset` | admin | `{}` | `200 {revision, generation, tariff_mode}` |

- A repeated `request_id` from the same home returns `202` with the existing job and `"duplicate": true`.
- `409 JOB_RUNNING`: confirm or coordinate while a plan job runs. Tariff while **any** job runs. A second message from a home whose last message is still being read.
- `404 NOT_FOUND`: unknown job or pending change, including every job from before a reset.
- `400 UNKNOWN_HOME` for a `home_id` that isn't A, B, or C. `400 BAD_REQUEST` for bad bodies.

### Job lifecycle (`result` always has `outcome` and `message`)

| Kind | Path | Terminal `status` / `result.outcome` |
|---|---|---|
| message | `queued → running (stage) →` | `awaiting_confirmation` / `needs_confirmation` (+ `pending_change_id`) |
| | | `completed` / `infeasible` (+ `pending_change_id`, `infeasible_reasons`) |
| | | `completed` / `no_change` (nothing understood or nothing to change) |
| | | `failed` / `rejected_output`, `error: "BAD_MODEL_OUTPUT: …"` (agent named another home's or an unknown appliance) |
| | after the resident confirms or rejects | the message job flips to `completed` / `applied` or `rejected` |
| action confirm | `queued → running →` | `completed` / `applied` (+ `revision`, `proposal_id`, `source`) or `completed` / `infeasible` |
| action reject | immediate | `completed` / `rejected` (revision bumps) |
| coordinate | `queued → running →` | `completed` / `committed` (+ `revision`, `proposal_id`, `source`) |
| any | reset during the job | `failed`, `error: "RESET: …"` (then the job is gone → 404) |

Confirm **applies the edit and replans in one job, with one revision bump**.

## 3. Dashboard state (`GET /api/state`)

Every PRD §10 `NeighborhoodState` field, plus:

- `coordination`: `{status, explanation, reasons, job_id, source, proposal_id, plan_name, tariff_mode, home_explanations}`. **ADDED:** `proposal_id`, `plan_name` ("Plan 2"), `tariff_mode` (the tariff the plan was priced under), `home_explanations` (always `{}` in the household view).
  - `status`: `not_run` (start, `coordinated_schedule: null`), `committed`, or `stale_tariff`. With `stale_tariff`, `reasons[0]` is "Plan priced under the previous tariff. Coordinate again."
  - `source`: `stub`, `live`, or `deterministic_fallback`.
- `job_status`: `"idle"` or `"running"`.
- `ai_mode`: `live` after a live coordination succeeds, `unavailable` when stubbed or after a fallback.
- **ADDED** `view`: `"dashboard"` or `"home"`, and `view_home_id`.
- `metrics` / `metrics_flat_rate` / `demand_kw` keys: `baseline` (preferred times), `independent` (cheap timer), `coordinated` (`null` until the first commit). `demand_kw.*` arrays have 96 entries.
- `events`: no `home_views` field ever reaches a client.
- Money is rounded to 4 decimals. **Format it to 2 decimals in the UI.**

## 4. Household view (`GET /api/state?home=A`)

Filtered on the server. Contains:
- `tasks`, `baseline_schedule`, `independent_schedule`, `coordinated_schedule`: Home A's entries only.
- `metrics.*.per_home` and `metrics_flat_rate.*.per_home`: only `{A: …}`. Street totals (`peak_kw`, `capacity_violations`, totals) stay, as do `demand_kw` (aggregate), `capacity_kw`, and `tariff_usd_per_kwh`.
- `background_kw_by_home`: only `{A: 1.2}`. `homes`: all three names and colors (other homes' `preferences` emptied).
- `pending_changes`: A's, `status: "pending"` only.
- `events`: events sent by or to `resident_A`/`agent_A`, plus `all_agents` broadcasts **that carry `home_views.A`** (whose text replaces `text`). Tool events are removed, `data` is null. **A broadcast without `home_views` never reaches a phone.**
- `activity`: replaced with "Planning with the neighbors…" while anything runs.
- `coordination.explanation`: `home_explanations.A`, or "The neighborhood plan is set."

The phone shows `events` as-is, sorted by `sequence`. Display `text` and nothing else.

## 5. Events

`id: "evt-<generation>-<n>"`, `sequence` is monotonic across resets. Sort by `sequence`. Code-written events have `source: "system_template"`. The backend writes these itself:

| When | sender → recipient | type |
|---|---|---|
| Resident request | `resident_A → agent_A` | `request` (resident's own words, `data.origin: "resident"`) |
| Interpretation result | `agent_A → resident_A` | `info` (`reply_to_event_id` = request) |
| Confirmed change | `backend → all_agents` | `info` "Home A's resident changed … Replanning the street." (third person) |
| Before commit | `validator → all_agents` | `validation` "Checked Plan 2: …" |
| Commit | `coordinator → all_agents` | `commit` "Plan 2 is now the street's plan. … Compared with the last plan: Home B saves $0.97." |
| Fallback | `backend → all_agents` | `error` "The household agents didn't answer in time. Using the safe plan." |
| Tariff change | `backend → all_agents` | `info` |

## 6. Agent seam (C ↔ D)

C implements `backend/agents/orchestrator.py` with:

```python
from backend.simulation.agent_seam import (CoordinateContext, CoordinateResult, Emit,
                                           InterpretContext, InterpretResult, EditRequest)

async def interpret_request(ctx: InterpretContext, emit: Emit) -> InterpretResult: ...
async def coordinate_neighborhood(ctx: CoordinateContext, emit: Emit) -> CoordinateResult: ...
```

The backend imports each one if present. Otherwise it uses D's labeled stubs, and `health.agent_impl` shows which. `POWERSYNC_AGENT_IMPL=stub` forces the stubs, and tests always do. The models are defined in `backend/simulation/agent_seam.py`.

**`emit(event: dict) -> str`** stores the event **immediately** and returns its id (use it for `reply_to_event_id`). Keys: `sender, recipient, type, text (≤800), round, proposal_id, reply_to_event_id, source ("model"|"system_template"), home_views {A,B,C}, data (flat dict)`. `emit({"stage": "Home B is reviewing Plan 1"})` sets `state.activity` and `job.stage`. It returns `""` if the demo was reset during the job: stop work and return.

**Interpret.** `ctx`: `job_id, home_id, text, request_id, request_event_id, snapshot, scenario_date, planning_starts`. Return `InterpretResult(outcome="edits"|"no_change"|"infeasible", edits=[EditRequest(task_id, field, new_value)], explanation, message, infeasible_reasons, source="live")`. `field` is one of `deadline_slot`, `earliest_slot`, `preferred_start_slot`. **D re-checks everything:** another home's task or an unknown task fails the job, and D runs the engine to decide feasibility. If `explanation` is empty, D writes "Change your EV charging's finish time from 1:00 AM to 11:00 PM?". Resolve "11 pm tonight" with `timefmt.clock_to_slot(23, as_deadline=True)` → 20.

**Coordinate.** `ctx`: `job_id, snapshot` (with any confirmed edit already applied), `trigger` (**third person**, such as "Home A's resident changed their EV charging's finish time to 11:00 PM."), `trigger_home_id`, `previous_schedule` (last committed plan or null), `next_plan_number`. Return `CoordinateResult(schedule=[{task_id, start_slot}], proposal_id="P-2", plan_name="Plan 2", pins, explanation, home_explanations, source="live", rounds, model_calls, tool_calls)`. D validates `schedule` against canonical tasks. If it fails, raises, or exceeds `POWERSYNC_AGENT_TIMEOUT_S` (default 60), D commits the engine plan as `deterministic_fallback` and says so. **Don't emit commit events.** D emits validation and commit after the commit succeeds. **Every `all_agents` broadcast needs `home_views`**, or phones won't see it.

Plan numbering: name proposals from `next_plan_number` up. If Plan 1 is proposed and Plan 2 is committed, return `plan_name="Plan 2"`. D's counter continues from the committed plan.

## 7. Engine functions for MCP tools (`backend/simulation/engine.py`, pure, no state)

| MCP tool | Call |
|---|---|
| `get_home_context` | `home_context(snapshot, home_id)` → own tasks (with 12-hour `deadline_time`), background, capacity, `tariff_summary` |
| `evaluate_schedule` | `evaluate_schedule(snapshot, [{task_id, start_slot}])` → `{valid, findings, metrics, expensive_hours_share_by_home, summary}` |
| `find_feasible_schedule` | `find_feasible_schedule(snapshot, pins={"a_ev": 15}, preferred_overrides={...})` → `ScheduleResult` (`.to_dict()`: `ok, status (found / impossible / budget_exhausted / bad_input), reasons, schedule`) |
| `compare_schedules` | `compare_schedules(snapshot, baseline_entries, candidate_entries)` → per-home and total cost changes and moved appliances |

`Snapshot` is a Pydantic model: send `snapshot.model_dump()` over MCP and rebuild with `Snapshot.model_validate(d)`. Text helpers: `timefmt.slot_to_time`, `span_text`, and `wording.plan_announcement(snap, "Plan 1", before, after, "everyone's preferred times")`, which returns `(text, home_views)`.

## 8. Verified numbers (TOU unless noted)

| Schedule | Energy charge | Peak | Over-limit slots |
|---|---:|---:|---:|
| Preferred times | $63.02 | 23.0 kW | 12 |
| Cheap timer (all at 9:00 PM) | $49.87 | 26.6 kW | 12 |
| Engine Plan 1 (A car 9:00 PM, **B dryer 6:30 PM, expensive**, C car 12:00 AM) | $50.85 | 13.2 kW | 0 |
| A's car pinned at 9:45 PM (B dryer 9:00 PM, C car 12:45 AM) | $49.87 | 13.2 kW | 0 |

Per home, Plan 1 → pinned: A $18.59 → $18.59, **B $13.67 → $12.70 (−$0.97)**, C $18.59 → $18.59. Energy is always 136.95 kWh. Under the flat rate, every schedule costs $24.65 and the coordinated peak is 10.8 kW. "Car ready by 11 pm" is feasible: A's car runs 8:00–11:00 PM, which squeezes B's dryer back into expensive hours. "Car ready by 8 pm" is infeasible: "Home A's EV charging needs 3 hours, so it can't finish by 8:00 PM when planning starts at 6:00 PM."

## 9. Environment

`.env` at the repo root: `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `DEMO_ADMIN_TOKEN`, `DEMO_HOME_A_TOKEN`, `DEMO_HOME_B_TOKEN`, `DEMO_HOME_C_TOKEN`, `OPENROUTER_TIMEOUT_SECONDS`, `OPENROUTER_JOB_SECONDS`, `POWERSYNC_AGENT_TIMEOUT_S` (D's outer guard per agent call: interpret default 30 s, coordinate default 60 s), and `POWERSYNC_AGENT_IMPL` (`auto` or `stub`). Blank tokens mean dev-open. Restart the backend after editing `.env`.
