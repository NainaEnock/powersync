# Guide D: backend, data, and engine

**Your job:** the source of truth. You own the scenario, the schemas, the API, the job queue, the scheduler, the validator, the metrics, and the privacy filter. Every number on screen comes from your code.

**You own:** `backend/main.py`, `backend/simulation/`, `backend/data/`, `backend/requirements.txt`, `docs/contract.md`.

**Read first:** PRD §9–11, §15, §18.2, §19, §22, §25. Also `02-Team-Schedule.md`.

## Checkpoints

| Step | Time | Do | Done when | Send |
|---|---|---|---|---|
| D1 | 0:00 | Create `.venv`, install FastAPI, Uvicorn, httpx, Pydantic, python-dotenv, fastmcp, pytest, and pin them. Write `scenario.json` and `provenance.md` from PRD §9 and §26. | The scenario loads | none |
| D2 | 0:10–0:20 | Pydantic schemas from PRD §10. Contract PR with example state (both views), job, message, confirm, tariff, and errors. Agree on the agent seam with C. | B merges the contract | A, B: examples. C: snapshot and engine imports. |
| D3 | 0:30 | `/api/health` (with `auth_mode` and `model`) and full `/api/state` for the scenario | B's badge reads "live, connected" | B, A: start command, first revision |
| D4 | 0:30–0:50 | Metrics, preferred times, cheap timer, capacity-aware scheduler with backtracking and pins. Tests for PRD §9.5–9.6. | Numbers match §9.5, or you post the new table | B: the numbers. C: engine functions. |
| D5 | 0:50–1:05 | Job queue, `/api/message` with the stub interpreter, `/api/action` confirm (edit and replan in one job) and reject, request ID dedup, revision checks | A's confirm flow works with the stub | A, B: request and job IDs, revision |
| D6 | 1:05 | **Privacy views:** `?home=A` returns only Home A's data and `home_views` text, without tool events. The dashboard view hides events without the admin token. Decide the public-schedule gap with B. | A test proves Home A's view has nothing of B or C | A, B |
| D7 | 1:05–1:35 | `emit` callback that stores each event at once and returns its ID, plus `activity`. Swap in C's live interpreter, then live coordination. Serve `frontend/dist` with API routes first. | Plan 1 shows live on the dashboard | C, B: first fully live job |
| D8 | 1:35–2:25 | `POST /api/tariff` (admin, `409 JOB_RUNNING` during a job). Reset returns to time-of-use. Fallback commits the engine plan labeled `deterministic_fallback`. | Flat, then Coordinate, gives $24.65 | B, C |
| D9 | 2:25–5:00 | Tests: impossible deadline, bad model output (unknown task, changed duration, missing task, another home's task), stale change, reset during a job, duplicate tap, three-phone burst, auth with tokens set | `python -m pytest backend -q` passes | Everyone: results and any retry behavior presenters should know |
| D10 | After 5:00 | Run the tests, reset, and confirm the starting revision and baseline numbers | Fresh-start numbers match | A, B: expected starting values |

## The scenario must create a real conflict

Check these with a test, not by eye:
- Preferred times go over 15 kW.
- The cheap timer has a higher peak than preferred times.
- The engine's first plan is under the limit and puts Home B's dryer in expensive hours.
- Pinning Home A's car to 9:45 PM gives a valid plan where B pays less and A pays the same.

If a tie-break changes the exact dollars, that's fine. Post the new table. If it removes the conflict, fix the engine ordering (least slack, then higher power, then ID), not the agents.

## Things that went wrong in the trial

- **Agent tests used an older scenario copy.** Keep one `scenario.json` and have every test read it.
- **Blank versus set tokens confused everyone.** Report `auth_mode` in health. Blank means open.
- **The flat-rate toggle didn't reach the engine.** The tariff lives in backend state and every calculation reads it.
- **Home views were added late.** Build the filter at D6 so A builds against it from the start.
- **Times came out as `18:00`.** Use one 12-hour formatter for event text and `old_time`/`new_time`.
- **Revision must never go back**, even on reset. Bump `generation` on reset.

## First prompt for your assistant

```text
My role is D: backend and engine for PowerSync. Read CLAUDE.md, docs/PRD.md
(§9-11, §15, §18-19, §22), and docs/team-schedule.md. I own backend/main.py,
backend/simulation/, backend/data/, backend/requirements.txt, and
docs/contract.md.

We are at [time], checkpoint [gate], branch feat/backend-scheduler. Build the
next slice from my guide: [step]. One process, one worker, one async queue,
one state lock. Compute every number from slot arrays, validate every
candidate against canonical tasks, keep revision monotonic, and filter
?home= views on the server. Never read or print secret values. Run
`python -m pytest backend -q` before you finish, then tell me what works,
the numbers it produced, and what to send to whom.
```
