# Guide A: phone app

**Your job:** the household app residents install on their phones. Each phone shows one home's plan, takes requests in plain language, asks before changing a deadline, and shows that home's messages and nothing else.

**You own:** `frontend/src/phone/` and phone assets. **Don't edit** `App.tsx`, `package.json`, `vite.config.ts`, `api.ts`, `types.ts`, or `fixtures.ts`. Ask B, with the exact change you need.

**Read first:** PRD §1, §9.1–9.2, §10, §11 (especially 11.2 and 11.3), §12.3, §16, §18.2. Also `02-Team-Schedule.md`.

## Checkpoints

| Step | Time | Do | Done when | Send |
|---|---|---|---|---|
| A1 | 0:00 | Sketch the single scrolling screen: header with status badge, summary tiles, today's plan, request box, confirmation card, messages | You can describe each state from PRD §16 | none |
| A2 | 0:10 | Clone, `feat/phone`. Build the `PhoneApp` default export with `homeId`, `state`, `api` props against B's sample data | Home A renders from sample data in 12-hour times | B: component path |
| A3 | 0:20 | Agree on props, token entry, `?home=` pinning, and the confirm flow with B and D | Written in `docs/contract.md` | B, D: the exact request you'll test |
| A4 | 0:30 | Render live state from `GET /api/state?home=A` through B's adapter | Correct tasks, kW, kWh, and USD. Badge reads "live, connected". | B: screenshot and revision |
| A5 | 0:50–1:05 | Send a request, follow the job, show the confirmation card, then confirm and reject | The revision changes on the dashboard after Confirm | D: request and job IDs. B: revision. |
| A6 | 1:05 | Error states: 401 opens token entry. 403 shows "That code isn't for this home" plus Change household. 409 refreshes and lets the user resubmit. Backend down shows a clear message. | Each one tested by hand | B, D: anything mismatched |
| A7 | 1:20–2:05 | Installed phones: install one with B, then the other two as separate homes | Three icons open full screen, one per home | Everyone: which phone is which home |
| A8 | 2:05–3:45 | Messages show only this home's view. Polish states: queued, interpreting, planning, applied, infeasible. Keep the old plan visible while replanning. | Privacy check at 3:45: Phone A shows nothing about B or C | B: final PR |
| A9 | After 5:00 | Reset each phone to the start, open the right home, rehearse the requests | All three show the reset revision | B: "phones ready" |

## Things that went wrong in the trial

- **Three tabs showed the same home.** Tabs share local storage. Support `/phone?home=A` to pin a tab to a home.
- **Times showed as 18:00.** Use one 12-hour formatter for every time on screen.
- **Phones could see other homes' messages.** Use the `?home=` view and show `home_views` text. Never filter another home's data out on the client, because it shouldn't arrive at all. If it does, tell D.
- **A wrong code looked like a broken app.** Show FORBIDDEN as a clear message with a way to switch homes.
- **An installed iPhone app has its own storage**, separate from Safari's. Enter the code inside the installed app.

## Demo requests to support

- A: "I leave at 11 pm tonight. Have my car ready by then."
- B: "My dryer must finish by 10 pm. You can move the dishwasher."
- C: "The car can charge anytime before 7 am."
- Impossible: "Car ready by 8 pm" must show an explanation, not a change.

## First prompt for your assistant

```text
My role is A: phone app for PowerSync. Read CLAUDE.md, docs/PRD.md (§9-12, §16,
§18), docs/team-schedule.md, and docs/contract.md if present. I own only
frontend/src/phone/ and phone assets. Don't edit App.tsx, package.json,
vite.config.ts, api.ts, types.ts, or fixtures.ts; tell me the exact change to ask B for.

We are at [time], checkpoint [gate], branch feat/phone. Build the next slice
from my guide: [step]. Use the injected api and state props, show 12-hour times,
show only this home's data, and label sample data. After the slice, run
`npm run build` in frontend/, then tell me what works, what mode it ran in,
and what to send to whom.
```
