# PowerSync team schedule

Use this with `PRD.md`. Times are elapsed hacking time. Each person also has a role guide with their own numbered steps.

| Person | Role | Branch | Owns |
|---|---|---|---|
| A | Phone app | `feat/phone` | `frontend/src/phone/`, phone assets |
| B | Dashboard and integration | `feat/dashboard` | Repo, merges, `frontend/` config, routing, `api.ts`, `types.ts`, `fixtures.ts`, `frontend/src/dashboard/`, PWA, tunnel, demo laptop |
| C | Agents and MCP | `feat/agents-mcp` | `backend/agents/`, `backend/tools/`, conversation wording |
| D | Backend and engine | `feat/backend-scheduler` | `backend/main.py`, `backend/simulation/`, `backend/data/`, `backend/requirements.txt`, `docs/contract.md` |

## Kickoff

1. **0:00. B creates the repo** and invites A, C, and D. The first commit holds the README, `.gitignore`, a blank `.env.example`, `CLAUDE.md` (from `AI-CONTEXT.md`), `docs/PRD.md`, and `docs/team-schedule.md`. B posts the URL and opens a pinned **Build status** thread.
2. **0:00–0:10. Everyone starts in parallel.** A sketches phone screens. C picks a model from the event key's catalog and prepares a timing call. D writes `scenario.json` from PRD §9 and drafts the contract. B scaffolds Vite.
3. **By 0:10.** Everyone clones and branches, and posts their branch and first task.
4. **By 0:20.** The interfaces are frozen (decisions below). D's contract PR merges first.
5. **From 0:20.** Merge the smallest passing slice, one PR at a time. B posts the last good `main` SHA after each merge.

**Development defaults everyone uses:** blank tokens (dev-open), Vite on 5173, backend on 8000, `npm` inside `frontend/`, Python from the repo root with `.venv` active.

## Decisions to make together

| Who, when | Decide | Write it in |
|---|---|---|
| All, 0:10 | Keep the PRD stack. B owns frontend packages. D owns Python packages. | Build status |
| A + B, 0:20 | Phone props (`homeId`, `state`, `api`), API methods, home colors, token entry, `?home=` tab pinning, status badge | `docs/contract.md` |
| B + D, 0:20 | State JSON for both views, job fields, error codes, the tariff route, the proxy, and who serves the build. **Decide the §11.3 public-schedule gap.** | `docs/contract.md` |
| A + D, 0:20 | Request and confirm flow: `request_id`, `expected_revision`, `pending_change_id`, and what each error shows | `docs/contract.md` |
| C + D, 0:20 | Agent function names and signatures, snapshot shape, the `emit` callback and its returned ID, `home_views`, result and error types, the stub | `docs/contract.md` |
| C + B, 0:30 | Model choice from C's timing call. Wording style for plans and reviews, with one sample of each. | Build status |
| A + B, 1:20 | Icons, manifest, `/phone` URL, which phone is which home | Build status |

To change a shared field: post `field → change → affected owners → test to rerun`. Both owners agree, then D updates the contract.

## Status format

```text
[0:35 | A4 | G3] Ready for B
PR/SHA: ...
Works now: ...
Try it: (command or click)
Expect: ...
Mode: sample data / live + stub agent / fully live
Need from: (person + action) or none
```

Post a blocker right away with the click or command, the exact error, and the smallest input that reproduces it. Remove secrets first.

## Checkpoints

Check-ins take three minutes. B runs one visible check on the demo laptop. Each gate is marked **passed**, **blocked**, or **sample-only**, with the next action and owner.

| Gate | Time | Verify together | Lead |
|---|---|---|---|
| G0 | 0:00 | Roles assigned, timer started, demo laptop chosen | B |
| G1 | 0:10 | Everyone has a branch and a first task | B |
| G2 | 0:20 | Contract merged. Props, API examples, and agent signatures frozen. | All |
| G3 | 0:30 | **C reports the real model timing.** D serves `/api/health` and the full scenario state. B loads it through the proxy, with the status badge showing "live, connected, dev-open". A renders Home A. | C, D, B, A |
| G4 | 0:50 | A sends a request and gets a job ID. B sees the event. C lists and calls a real MCP tool. D's engine matches the PRD §9.5 numbers. | All |
| G5 | 1:05 | A confirms a change with the stub agent. Phone and dashboard show the same revision. `?home=A` returns only Home A. | A, B, D |
| G6 | 1:20 | C's live interpreter handles one real request. **B starts the tunnel (and leaves it running)** and installs one phone from the built app. | All |
| G7 | 1:35 | Coordination runs through real MCP. Plan 1 appears on the dashboard **live, before the job finishes**. | C, D, B |
| G8 | 1:50 | **One real peer exchange:** B objects to Plan 1, A answers, Plan 2 is evaluated. The validator runs and the commit is announced. | All |
| G9 | 2:05 | Three real phones on the same backend, with tokens enforced on the demo laptop. Requests run one after another, then in a burst. | All |

**2:05–4:45, check every 20 minutes:**
- 2:25: tariff toggle, then Coordinate. Expect a plan priced flat and no cost objections.
- 2:45: full phone-to-dashboard rehearsal.
- 3:05: impossible deadline ("car ready by 8 pm").
- 3:25: stale revision, and reset during a job.
- 3:45: privacy. Phone A shows nothing about B or C.
- 4:05: timing and errors. Kill the network once and check the fallback.
- 4:25: rehearse on the projector. Someone outside the team reads one round.
- 4:45: clear the last blockers.

**5:00 feature freeze.** B records the demo SHA and rebuilds. 5:15: three-phone check, then **record the backup video of a full live run**. 5:30: rehearse with a five-minute timer. 5:45: reset, then check the key, the model, the tunnel, and every phone.

Lunch rotates. Never take a break while your own PR is broken on `main`.

## If behind

| When | Cut |
|---|---|
| 2:00 without a loop | Styling. Integrate one phone first. |
| 2:30 with a model over 15 s per review | Switch models, or use one round with larger timeouts |
| 3:00 without negotiation | Demo the engine plan (labeled) and keep wiring agents |
| 4:00 without installed phones | Drop AI polish. Get the PWA and shared state working. |
| Any time | Cut waste reduction and animation before metrics, validation, privacy, or three phones |

Never fake agent traffic, and always label sample data.
