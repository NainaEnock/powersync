# PowerSync

Every home gets an AI energy representative. Residents tell their agent, in plain language, when they need their appliances done. The agents then negotiate a plan with the neighbors that keeps the street under a shared 15 kW limit and moves usage into cheaper hours, without breaking anyone's deadline.

Built in six hours at the NOVA 2026 hackathon. The homes and appliances are simulated; the phones, the agents, and their negotiation are real.

## What it does

- **Phone app (one per home).** An installable web app where a resident sees tonight's plan for their own appliances, asks for changes ("have my car ready by 11 pm", "AC done by 10"), answers the agent's follow-up questions, confirms or rejects proposed changes, and adds or removes appliances.
- **Neighborhood dashboard.** A projected control room showing street demand against the limit, each appliance's run window, cost and peak metrics, and the agents' conversation as it happens.
- **Negotiating agents.** Each household agent reviews a proposed plan for its own home, objects when its flexible use lands in expensive hours, and asks a neighbor for a specific change. The neighbor's agent agrees only if its own deadline and cost are unaffected.
- **A deterministic engine has the final say.** Agents propose; the engine and validator check every plan against the real appliance requirements and the street limit before anything is committed.

## How it works

```
 Phones (3) ─┐                       ┌─ OpenRouter model (household agents)
             ├─ FastAPI backend ─────┤
 Dashboard ──┘   state, jobs,        └─ MCP server "powersync-energy"
                 privacy filter            get_home_context · evaluate_schedule
                                           find_feasible_schedule · compare_schedules
                                                    │
                                           deterministic scheduling engine
```

- Planning covers 24 hours in 15-minute steps, starting at 6:00 PM.
- Time-of-use pricing: $0.59/kWh from 4–9 PM and $0.33/kWh otherwise. A flat-rate toggle ($0.18/kWh) shows that under flat pricing, moving appliances changes nothing on the bill.
- Moving an appliance never changes the energy used, only when it is used.
- **Privacy:** each phone receives only its own home's appliances, costs, and messages. Filtering happens on the server.
- **Honesty:** agent messages are labeled AI or code-written, dollar figures always come from the engine rather than the model, and failures are shown as failures. If the model is unavailable, the backend falls back to a labeled engine-only plan.

## Tech stack

- **Frontend:** React, TypeScript, Vite, `vite-plugin-pwa`, Recharts, `lucide-react`
- **Backend:** Python 3.11, FastAPI, Uvicorn, Pydantic, httpx, `fastmcp`
- **AI:** OpenRouter (tool-calling model), with a custom MCP server for the energy tools

## Running it locally

Backend, from the repo root:

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env        # add an OpenRouter key to use live agents; leave blank for stub agents
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Frontend, in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173/dashboard?mode=live` and `http://localhost:5173/phone?home=A&mode=live`. Without `?mode=live` the dev server shows labeled sample data. The Vite dev server proxies `/api` to the backend. For a single-origin build, run `npm run build` in `frontend/` and the backend serves `frontend/dist` itself.

With no OpenRouter key the app runs with rule-based stub agents, clearly labeled as such. Blank access codes leave the app open for local development; set the `DEMO_*_TOKEN` values in `.env` to require codes.

## Tests

```bash
python -m pytest backend -q      # from the repo root; stub models only, never the real API
cd frontend && npm run build     # type-check and production build
```

## Project layout

```
backend/
  main.py            FastAPI app and routes
  simulation/        engine, validator, metrics, state store, privacy views
  agents/            household agents, negotiation, request interpreter
  tools/             MCP server exposing the engine as tools
  data/scenario.json the three-home evening scenario
frontend/src/
  phone/             household app
  dashboard/         neighborhood dashboard
docs/
  PRD.md             product spec
  contract.md        API and agent interface reference
```

## Configuration

All secrets and limits live in `.env` (gitignored); `.env.example` lists the names. Never commit real keys or access codes.
