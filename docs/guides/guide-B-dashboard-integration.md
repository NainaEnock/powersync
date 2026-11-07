# Guide B: dashboard and integration

**Your job:** the repo, the frontend shell, the projected dashboard, and the demo laptop. You keep `main` runnable and you run the checkpoints. You are the integration lead, not everyone's implementer: each owner fixes their own files.

**You own:** the repo and merges, `frontend/` root config, routing, `api.ts`, `types.ts`, `fixtures.ts`, `frontend/src/dashboard/`, PWA config and icons, frontend dependencies, the tunnel, and the demo laptop's `.env`.

**Read first:** all of the PRD, and in detail §8, §10–12, §17–20, §22–23. All of `02-Team-Schedule.md`.

## Checkpoints

| Step | Time | Do | Done when | Send |
|---|---|---|---|---|
| B1 | 0:00 | Create the repo and invite A, C, D. First commit: README (run `npm` in `frontend/`, Python from the root), `.gitignore`, blank `.env.example`, `CLAUDE.md`, `docs/PRD.md`, `docs/team-schedule.md`. Open Build status. | Everyone can clone | Everyone: URL, SHA |
| B2 | 0:10–0:20 | Vite React TS scaffold. Install recharts, lucide-react, vite-plugin-pwa. Routes `/phone` and `/dashboard`. `/api` proxy to 8000. Sample data from PRD §9 marked "Sample data". | `npm run build` passes | A: props. D: proxy target. |
| B3 | 0:20 | Freeze interfaces with A and D (see schedule). Mirror D's schemas into `types.ts`. | Contract merged | none |
| B4 | 0:30 | `api.ts`: relative URLs, bearer header, `no-store`, one-second polling with cleanup, job polling, `?home=`, `setTariff`, typed errors. Status badge: mode, connection, auth mode, model. "Backend not running on port 8000" when the proxy fails. | Badge reads "live, connected, dev-open" against D's backend | Everyone: passing SHA |
| B5 | 0:35–1:05 | Dashboard: demand chart (preferred, coordinated, optional cheap timer, 15 kW line, shading for expensive hours, 12-hour ticks), metrics with named comparisons, home cards | Numbers match PRD §9.5 | D: anything that doesn't match |
| B6 | 1:05–1:20 | Build served by FastAPI (with D). **Start the tunnel and leave it running.** Install one phone with A. | Installed icon opens full screen, live | A: HTTPS `/phone` URL |
| B7 | 1:20–1:50 | Conversation panel (PRD §12.4): sort by `sequence`, rounds, Plan tags, activity line, Follow and Pause, hidden state | Plan 1 appears live, before the job ends | C, D: event IDs that look wrong |
| B8 | 1:50–2:25 | Task timeline, tariff toggle wired to `POST /api/tariff`, Reset sets the toggle back, admin code popover | Flat, then Coordinate, gives a flat-priced plan | D, C: the result |
| B9 | 2:05 | Enforce tokens on the demo laptop. Three phones with their codes. | Gate G9 passes | Everyone |
| B10 | 2:25–5:00 | Keep `main` runnable. Run every 20-minute check. Polish for 1440×900. Get one person outside the team to read a round. | Each check marked passed or blocked | Everyone: release candidate SHA before 5:00 |
| B11 | After 5:00 | Record the demo SHA, rebuild, check the tunnel and phones, **record the backup video**, run the projector | Final reset done, everything green | Everyone: who does which demo action |

## Merging

- One PR at a time, using a **regular merge commit**, not a squash.
- Before merging frontend work, run `npm run build`. Before merging backend work, have D or C run `python -m pytest backend -q`.
- If a merge breaks the demo path, stop merging until its owner fixes it.
- After merging, post the SHA and a two-click check.

## Things that went wrong in the trial

- **"It works for A but not me."** A had blank tokens and B had real ones. Keep everyone dev-open until G9, and show `auth_mode` in the badge.
- **Fixture versus live confusion.** "Waiting for backend" just meant the backend wasn't running. Make the badge unmistakable.
- **The flat-rate toggle only changed the chart.** Wire it to the backend from the start.
- **A typecheck failure got pushed.** Run `npm run build` before every push.
- **Short timeline bars and Y-axis labels got clipped.** Check at 1440×900 with real data.
- **The key was pasted into `.env.example`.** Check `git diff --cached` on every merge.
- **The tunnel URL changes on restart**, so every phone has to add the icon again. Start it once and keep it running.

## Demo laptop checklist

- `.env` has the event key, the exact model ID, and all four tokens (enforced).
- Built frontend, served by FastAPI on 127.0.0.1:8000. Not the Vite dev server.
- The tunnel is running and the laptop is plugged in, with sleep disabled.
- The dashboard has the admin code. Each phone has its home code.
- The backup video is on the laptop's desktop.

## First prompt for your assistant

```text
My role is B: dashboard and integration for PowerSync. Read CLAUDE.md,
docs/PRD.md, docs/team-schedule.md, and docs/contract.md if present. I own the
frontend root config, routing, api.ts, types.ts, fixtures.ts,
frontend/src/dashboard/, PWA config, and frontend dependencies.

We are at [time], checkpoint [gate], branch feat/dashboard. Build the next slice
from my guide: [step]. Use relative /api URLs, bearer tokens only in headers,
12-hour times, and a visible status badge. Label sample data, and never
invent agent messages. Run `npm run build` in frontend/ before you finish, then
tell me what works, what mode it ran in, and what to send to whom.
```
