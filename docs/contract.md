# PowerSync contract (D owns; wins over the PRD where they differ)

Status: **v2**. Adds C's agent seam, B's G2 answers, and A's outcome names. Tests: `python -m pytest backend -q` → 31 passed.
Field names follow PRD §10 exactly. Additions beyond the PRD are marked **ADDED**. To change anything here, post
`field → change → affected owners → test to rerun` in Build status first.

Run: `source .venv/bin/activate && pip install -r backend/requirements.txt` then
`python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000` from the repo root.

## 1. Decisions

| Topic | Decision |
|---|---|
| §11.3 public-schedule gap | **Closed (B's call).** `GET /api/state` without `home` needs the admin token: none → `401`, a wrong one → `403`. In dev-open it's open. The dashboard always sends the admin code. Phones always use `?home=`. |
| `/api/action` body (B #1) | Confirmed: `{home_id, action, pending_change_id, expected_revision, request_id}`. |
| Error shape (B #2) | `{"error":{"code","message"}}` on **every** error, including unknown `/api/*` routes (404 `NOT_FOUND`), wrong methods, and bad JSON (400 `BAD_REQUEST`). |
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
| `GET /api/state` | admin | | Dashboard view (§3) |
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
| message | `queued → running (stage) →` | `awaiting_confirmation` / `proposed_change` (+ `pending_change_id`) |
| | | `completed` / `infeasible` (+ `pending_change_id`, `infeasible_reasons`) |
| | | `completed` / `needs_clarification` (`message` is the agent's question) |
| | | `completed` / `no_change` (nothing understood or nothing to change) |
| | | `failed` / `error`, `error: "BAD_MODEL_OUTPUT: …"` (agent named another home's or an unknown appliance) |
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
- `events` (C's rule): `tool_call` and `tool_result` are dropped. **If an event has `home_views`**, the phone gets `home_views.A` as `text`, or doesn't get the event at all when there's no `A` key. **If it has no `home_views`**, the phone gets it only when `resident_A` or `agent_A` is the sender or recipient. `data` is null.
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

## 6. Agent seam (C ↔ D), as C proposed

C exports these from `backend/agents/__init__.py` (D also looks in `backend.agents.orchestrator`). Each one may be sync or async. The backend imports them when present and otherwise uses D's labeled stubs. `health.agent_impl` reports `live` only when C's function is present **and** `OPENROUTER_API_KEY` is set. `POWERSYNC_AGENT_IMPL=stub` forces D's stubs, and D's tests always do.

```python
interpret_request(snapshot: dict, home_id: str, text: str, emit, job_id: str) -> dict
  # {outcome: "proposed_change"|"infeasible"|"needs_clarification"|"no_change"|"error",
  #  proposed_edits: {edits: [{task_id, field, old_value, new_value, old_time, new_time}]},
  #  explanation, message, infeasible_reasons}
coordinate_neighborhood(snapshot: dict, emit, job_id: str, trigger: None | dict) -> dict
  # {schedule: [{task_id, start_slot, ...}], proposal_id: "P-2", plan_name: "Plan 2",
  #  source: "live"|"deterministic_fallback", explanation, home_explanations: {A,B,C}}
announce_commit(snapshot: dict, result: dict, emit, job_id: str) -> None   # optional
```

- **snapshot** is `engine_api.snapshot_dict(...)`, with `generation, requirements_version, capacity_kw, tariff_mode, tariff_label, tariff_usd_per_kwh[96], homes, tasks, background_kw_by_home, baseline_schedule`, plus `scenario_id, revision, horizon_start, slots, slot_minutes, capacity_tolerance_kw`.
- **trigger** is `None` for "Coordinate neighborhood". After a confirmed change it is `{home_id, task_id, field, old_value, new_value, old_time, new_time, edits: [...], text}`, where `text` is already third person ("Home A's resident changed their EV charging's finish time to 11:00 PM.").
- **emit(event) → event_id** is sync and stores the event right away. C fills `sender, recipient, type, text (≤800), round, proposal_id, reply_to_event_id, source, home_views, data`. D fills `id, sequence, timestamp, revision`. `emit({"stage": text or None})` sets `state.activity`. It returns `""` after a reset: stop and return.
- **D re-checks everything C returns.** Edits to another home's task or an unknown task fail the job (`error`, `BAD_MODEL_OUTPUT`). D's engine decides feasibility and rewrites `old_value`, `old_time`, and `new_time` from the canonical tasks. `outcome: "error"`, an exception, or a timeout (`POWERSYNC_AGENT_TIMEOUT_S`, default 30 s for interpret and 60 s for coordinate) sends the request to D's backup reader, and the conversation says so.
- **Commit order:** D validates `schedule`, emits `validation` ("Checked Plan 2: …"), commits with one revision bump, **then** calls `announce_commit`. If C has no `announce_commit`, or it fails or exceeds `POWERSYNC_ANNOUNCE_TIMEOUT_S` (10 s), D emits its own commit text. An invalid schedule, exception, or timeout commits D's engine plan as `deterministic_fallback`, with an error event.
- **Reset** cancels the running task (`asyncio.CancelledError`), so let it propagate.

## 7. Engine API for MCP tools (`backend/simulation/engine_api.py`, dict in, dict out, no state)

| Function | Returns |
|---|---|
| `find_feasible_schedule(snapshot, pins=None, preferred_overrides=None)` | `{ok, schedule[entries], reasons[plain English], proven_impossible, status}` (`status`: found, impossible, budget_exhausted, or bad_input) |
| `evaluate_schedule(snapshot, schedule)` | `{valid, findings[], metrics (per_home keyed A/B/C, or None if invalid), summary, expensive_hours_share_by_home}` |
| `compare_schedules(snapshot, baseline, candidate)` | per-home and total cost changes, plus moved appliances with 12-hour times |
| `get_home_context(snapshot, home_id)` | own tasks only, plus capacity and `tariff_summary` |
| `scenario_snapshot(tariff_mode="tou", tasks=None)` | a fresh snapshot dict from `scenario.json`. **Use this in tests instead of copied data.** |

`pins` and `preferred_overrides` map `task_id` to a slot. `expensive_hours_share_by_home` is each home's share of flexible energy at the top price (0 under flat), which works as the agents' `share_in_expensive_hours`. Text helpers: `timefmt.slot_to_time`, `span_text`, `clock_to_slot(23, as_deadline=True)` → 20.

## 8. Verified numbers (TOU unless noted)

| Schedule | Energy charge | Peak | Over-limit slots |
|---|---:|---:|---:|
| Preferred times | $63.02 | 23.0 kW | 12 |
| Cheap timer (all at 9:00 PM) | $49.87 | 26.6 kW | 12 |
| Engine Plan 1 (A car 9:00 PM, **B dryer 6:30 PM, expensive**, C car 12:00 AM) | $50.85 | 13.2 kW | 0 |
| A's car pinned at 9:45 PM (B dryer 9:00 PM, C car 12:45 AM) | $49.87 | 13.2 kW | 0 |

Per home, Plan 1 → pinned: A $18.59 → $18.59, **B $13.67 → $12.70 (−$0.97)**, C $18.59 → $18.59. Energy is always 136.95 kWh. Under the flat rate, every schedule costs $24.65 and the coordinated peak is 10.8 kW. "Car ready by 11 pm" is feasible: A's car runs 8:00–11:00 PM, which squeezes B's dryer back into expensive hours. "Car ready by 8 pm" is infeasible: "Home A's EV charging needs 3 hours, so it can't finish by 8:00 PM when planning starts at 6:00 PM."

## 9. Environment

`.env` at the repo root: `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `DEMO_ADMIN_TOKEN`, `DEMO_HOME_A_TOKEN`, `DEMO_HOME_B_TOKEN`, `DEMO_HOME_C_TOKEN`, `OPENROUTER_TIMEOUT_SECONDS`, `OPENROUTER_JOB_SECONDS`, `POWERSYNC_AGENT_TIMEOUT_S` (D's outer guard per agent call: interpret default 30 s, coordinate default 60 s), `POWERSYNC_ANNOUNCE_TIMEOUT_S` (default 10 s), and `POWERSYNC_AGENT_IMPL` (`auto` or `stub`). Blank tokens mean dev-open. Restart the backend after editing `.env`.
