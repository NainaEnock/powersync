# PowerSync: standing instructions for coding assistants

Save this file as `CLAUDE.md` (Claude Code) or `AGENTS.md` (other assistants) at the repo root. Full spec: `docs/PRD.md`. Confirmed fields: `docs/contract.md`, which wins over the PRD when they differ.

## The project

PowerSync is a six-hour hackathon prototype for the NOVA event. Three homes each have an AI agent that negotiates when simulated appliances run, so the street stays under a 15 kW limit and usage moves into cheaper hours without breaking any resident's deadline. There are three phone web apps (one per home), one projected dashboard, and one FastAPI backend on a laptop. The appliances and homes are simulated. The phones and agents are real.

The code is split into four areas, and an assistant works in one area at a time:

| Area | Files |
|---|---|
| Phone | `frontend/src/phone/` |
| Dashboard and integration | `frontend/` config, routing, `api.ts`, `types.ts`, `fixtures.ts`, `frontend/src/dashboard/`, PWA, merges |
| Agents and MCP | `backend/agents/`, `backend/tools/` |
| Backend and engine | `backend/main.py`, `backend/simulation/`, `backend/data/`, `backend/requirements.txt`, `docs/contract.md` |

Ask which area you're working in if it isn't stated. Don't edit files outside that area. When another area needs to change something, give the exact path and change for them.

## Hard rules

1. **All code is written during the event.** Don't copy or reproduce code from any earlier project or repo.
2. **The event OpenRouter key powers the app only.** Never use it for coding assistance. Never read, print, log, or commit any secret. Secrets live only in `.env`, which is gitignored. `.env.example` holds names only.
3. Never put secrets or tokens in frontend code, `VITE_` variables, URLs, or query strings. Tokens go in `Authorization: Bearer` headers only.
4. Never fake agent traffic or results. Label sample data as sample data. Show failures as failures.
5. Don't claim a test or build passed unless you ran it and saw it pass.
6. Don't rename shared fields or change the contract without saying so first. Propose `field → change → affected areas → test to rerun`.
7. Don't add frameworks, databases, or dependencies outside the PRD stack. Frontend packages belong to the dashboard and integration area; Python packages belong to the backend and engine area.

## Stack and how to run it

- Frontend: React, TypeScript, Vite, `vite-plugin-pwa`, Recharts, `lucide-react`. **Run `npm` inside `frontend/`.**
- Backend: Python 3.11, FastAPI, Uvicorn (one worker), Pydantic, httpx, python-dotenv, fastmcp. **Run Python from the repo root with `.venv` active**, for example `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`.
- Dev: Vite on 5173 proxies `/api` to 8000. All frontend requests use relative `/api/...` URLs.
- Demo: FastAPI serves the built `frontend/dist`, and a `cloudflared` tunnel gives the phones an HTTPS URL.
- Checks: `npm run build` in `frontend/` (includes the typecheck) and `python -m pytest backend -q` from the root. Run the relevant one before saying a slice is done.

## Domain facts (don't change without a team decision)

- 96 slots of 15 minutes, starting at 6:00 PM on 2026-07-15 (America/New_York). Slot 12 = 9:00 PM, slot 28 = 1:00 AM.
- A deadline is an end boundary: `start + duration <= deadline`. Tasks run without interruption.
- Tasks: A has an EV (7.2 kW, 3 h, done by 1 AM) and a dishwasher. B has a dryer (5 kW, 45 min, done by 11 PM) and a dishwasher. C has an EV (7.2 kW, 3 h, done by 6 AM) and a dishwasher. Each dishwasher is 1.2 kW for 1 h, done by 11 PM.
- Always-on use is 1.2 kW per home. The shared limit is 15 kW.
- Time-of-use prices: $0.59/kWh 4–9 PM, $0.33 otherwise. Flat: $0.18.
- Total energy is always 136.95 kWh. Moving a task never changes kWh, and under flat pricing it never changes cost.
- The built-in conflict: the engine's first plan is safe but puts Home B's dryer in expensive hours. Home A starting at 9:45 PM fixes it at no cost to Home A. Agents must find this through a real exchange. **Never hard-code it.**

## Conventions

- **Every time a person reads is 12-hour**, like `9:45 PM`. Slots stay integers internally.
- **Conversation text is plain English** for a judge with no context. Name each plan ("Plan 2") and say what moved and how it differs from the previous plan. Don't use "candidate", "slot", "concession", or task IDs in visible text. Dollar figures come from code, never from the model.
- **Privacy:** `GET /api/state?home=A` returns only Home A's data, using each event's `home_views.A` text. Filtering happens on the server, never only in the browser.
- **Events** are emitted one at a time as they happen, with `sequence`, `round`, `proposal_id`, `reply_to_event_id`, and `source` (`model` or `system_template`).
- The engine and validator decide every committed plan. Agents propose. The backend validates against canonical tasks and commits.
- Model output is parsed with Pydantic. Unknown tasks, changed durations, missing tasks, or another home's tasks are rejected.
- Stdio MCP server logs go to stderr, never stdout.
- Every limit (timeouts, rounds, budgets) is an environment setting.
- Automated tests never call the real model. Use a stub.
- Show `auth_mode`, data mode, and backend connection on screen. A blank token means that access level is open.

## Known pitfalls from the practice run

- `npm` run at the repo root fails with ENOENT. Run it in `frontend/`.
- A Vite proxy 500 usually means the backend isn't running. Show that clearly.
- Browser tabs share local storage, so use `/phone?home=A` to pin a tab to a home.
- First-person trigger text ("I need my car by 11") made another home's agent claim the requirement. Write context in the third person.
- A tariff toggle that only changes the display is a bug. It must call `POST /api/tariff`.
- Keep one `backend/data/scenario.json`, and have every test read it.
- Copy model IDs exactly from the OpenRouter catalog.
- Check `git diff --cached` for secrets before every commit.

## How to report after each slice

Say which files changed, the command or click to try it, what you actually ran and saw, which mode it ran in (sample data, live with stub agent, or fully live), and what the next person needs. Keep it short.
