# PowerSync

> **Run `npm` inside `frontend/`.** Running it at the repo root fails with ENOENT.
> **Run Python from the repo root** with `.venv` active, e.g.
> `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`

Every home gets an AI energy representative. Residents say when they need their appliances done, and the agents negotiate a plan with the neighbors that keeps the street under its 15 kW limit and moves usage into cheaper hours without breaking anyone's deadline. Appliances and homes are simulated; the phones and agents are real.

## Docs

- [`CLAUDE.md`](CLAUDE.md): standing rules for coding assistants
- [`docs/PRD.md`](docs/PRD.md): the spec (source of truth)
- [`docs/team-schedule.md`](docs/team-schedule.md): kickoff, checkpoints, cuts
- [`docs/guides/`](docs/guides/): one guide per role (A phone, B dashboard, C agents/MCP, D backend/engine)
- `docs/contract.md`: confirmed fields (D, coming at G2; wins over the PRD)

## Branches

| Role | Branch |
|---|---|
| A: phone | `feat/phone` |
| B: dashboard and integration | `feat/dashboard` |
| C: agents and MCP | `feat/agents-mcp` |
| D: backend and engine | `feat/backend-scheduler` |

## Secrets

Real values go in `.env` only (gitignored). `.env.example` holds names only. Check `git diff --cached` before every commit. Development runs dev-open (blank tokens).
