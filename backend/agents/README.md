# Agents and MCP (owner: C)

Proposed C↔D seam for `docs/contract.md` (D owns that file; copy what you agree with).

## Entry points (D calls these)

```python
from backend.agents import interpret_request, coordinate_neighborhood, announce_commit, get_energy_tools

await get_energy_tools().start()          # optional, at app startup (lazy otherwise)
await get_energy_tools().close()          # at shutdown

res = await interpret_request(snapshot, "A", text, emit, job_id=job.id)
res = await coordinate_neighborhood(snapshot, emit, job_id=job.id, trigger=None)
# D validates res["schedule"], emits the validation and commit messages, and commits.
# C sends no commit message and no reply to the resident (contract §5 and §6).
```

**Superseded by docs/contract.md v2 where they differ.** Trigger is D's shape (`text` already third person). `emit` returning `""` means the job went stale, and C stops quietly.

Pass no `model` in production: the live OpenRouter client is used if `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` are set.
- `interpret_request` with no key falls back to `RuleStubModel` (labeled `source: "stub"`). Report `agent_impl.interpret` from `res["source"]`.
- `coordinate_neighborhood` with no key returns the engine's Plan 1, labeled `source: "deterministic_fallback"`, `ai_mode: "unavailable"`. For a stub negotiation in dev, pass `model=RuleStubModel()`.
- Both coroutines are cancellable. Reset can `task.cancel()` them. C never commits state.

## Snapshot (built by D, read-only for C)

A subset of `NeighborhoodState` with the same field names:
`scenario_id, generation, requirements_version, revision, horizon_start, slot_minutes, capacity_kw, tariff_mode, tariff_label, tariff_usd_per_kwh[96], homes[], tasks[], background_kw_by_home {A: [96] or number}, baseline_schedule` (preferred times).
It must be JSON-serializable, because it is sent to the MCP subprocess.

## emit

`emit(event: dict) -> event_id` (sync or async). D stores the event at once and returns its stable ID.
- C fills: `job_id, sender, recipient, type, text, round, proposal_id, reply_to_event_id, source, home_views, data`.
- D fills: `id, sequence, timestamp, revision`.
- `emit({"stage": "Home B is reviewing Plan 1"})` sets `state.activity`. `{"stage": None}` clears it.

**Privacy filter rule for `?home=X`** (D implements):
- Drop `tool_call` and `tool_result` events.
- If `home_views` is present: show `home_views[X]` as the text when the key exists, else hide the event from X.
- If `home_views` is absent: show the event only when X is the sender's or recipient's home.

C sets `home_views` on every non-tool event. The views never name another home's appliances or costs (tested).

## Results

`interpret_request` returns `{outcome, message, proposed_edits: {edits: [{task_id, field, old_value, new_value, old_time, new_time}]}, explanation, feasible, infeasible_reasons, source, model, usage}`.
`outcome` is one of `proposed_change | infeasible | needs_clarification | no_change | error`. Errors look like `"AI_UNAVAILABLE: ..."` or `"PLANNER_UNAVAILABLE: ..."`.

`coordinate_neighborhood` returns `{outcome, message, proposal_id, schedule, metrics, source, ai_mode, explanation, reasons, rounds, plans: [{proposal_id, name, summary, pins}], commit_reference, model, usage}`.
`outcome` is one of `plan_ready | no_plan | error`. `source` is one of `live | stub | deterministic_fallback`.

Trigger after a confirmed change: `{"kind": "requirement_change", "home_id": "A", "task_id": "a_ev", "field": "deadline_slot", "old_value": 28, "new_value": 20}`, with the snapshot already holding the new value. Other agents hear it in the third person.

## What C needs from D: `backend/simulation/engine_api.py`

```python
def find_feasible_schedule(snapshot: dict, pins: dict[str, int] | None, preferred_overrides: dict[str, int] | None) -> dict
    # {"ok": bool, "schedule": [ScheduleEntry] | None, "reasons": [plain-English str], "proven_impossible": bool}
def evaluate_schedule(snapshot: dict, schedule: list[dict]) -> dict
    # {"metrics": Metrics (per_home keyed by home ID), "valid": bool, "findings": [str]}
```

Until that module exists, tests use `backend/agents/tests/fake_engine.py` through `POWERSYNC_ENGINE_MODULE`. That fake is test-only and reproduces the PRD §9.5 numbers. Point the bridge somewhere else with `POWERSYNC_ENGINE_MODULE=<module>`.

## MCP server `powersync-energy`

`python -m backend.tools.energy_server` (stdio). It exposes four tools: `get_home_context`, `evaluate_schedule`, `find_feasible_schedule`, `compare_schedules`.
- The server rebuilds every schedule from canonical tasks, so only `start_slot` comes from the caller.
- The child process gets the environment minus `OPENROUTER_API_KEY` and `DEMO_*`.
- Logs go to stderr.
- In fastmcp 4.1.6 / mcp 2.3.0 the tool schema field is `input_schema`. `inputSchema` is deprecated.

## Environment limits (all optional)

| Name | Default |
|---|---|
| `OPENROUTER_TIMEOUT_SECONDS` | 20 (per model call) |
| `OPENROUTER_JOB_SECONDS` | 45 (whole job) |
| `POWERSYNC_TURN_TIMEOUT_S` | 20 (one agent turn; D's `POWERSYNC_AGENT_TIMEOUT_S` is the outer job guard) |
| `POWERSYNC_MAX_ROUNDS` | 3 |
| `POWERSYNC_MAX_MODEL_CALLS` | 12 |
| `POWERSYNC_MAX_TOOL_CALLS` | 24 |
| `POWERSYNC_MAX_TOOL_ROUNDS` | 2 (0 disables model-initiated tool calls) |
| `POWERSYNC_MAX_RETRIES` | 1 |
| `POWERSYNC_ENGINE_MODULE` | `backend.simulation.engine_api` |

## Checks

- `python -m pytest backend/agents -q` uses stub models only and runs real MCP stdio calls.
- `python -m backend.agents.timing_check --review` makes 2 to 3 real calls, so run it on purpose.
