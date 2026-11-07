# Phone contract proposal (A → B, D) for G2

A's proposal for `docs/contract.md` (D owns that file). Field names follow PRD §10–11. Anything marked **NEW** isn't in the PRD yet and needs an OK.

## 1. Component (A + B), updated for B's api.ts on main

```tsx
import PhoneApp from './phone/PhoneApp'
// in App.tsx, for /phone:
<PhoneApp homeId={homeFromQuery /* HomeId | null */} api={api} />
```

- `homeId`: from `/phone?home=X`, or `null`. With `null`, the phone uses the household last chosen on this device (`localStorage powersync.phone.home`, needed for the installed app, which opens `/phone` with no query), otherwise it shows the picker.
- `api`: B's `Api` from `createApi()`. The phone uses `api.state(home)` (through `usePoll`), `api.message`, `api.action`, `useJob`, `useHealth`, `getToken`/`setToken`, and `StatusBadge`.
- `state` (optional): pass `usePoll(api.state(homeId))` output if B would rather own the polling. If it's left out, the phone polls itself, the same way `Dashboard` does.
- Times: `slotToTime` from `src/time.ts` only.
- Errors: `ApiError.code`. `BACKEND_DOWN` and `NETWORK` show the red banner.
- Home colors: `state.homes[].color`, with fallbacks A `#2563eb`, B `#d97706`, C `#059669`.

## 2. Requests (A + D)

`POST /api/message` (as in the PRD):
```json
{"home_id":"A","text":"I leave at 11 pm tonight. Have my car ready by then.","request_id":"phone-a-<uuid>","expected_revision":3}
```

`POST /api/action` (**NEW**: the body shape isn't in the PRD):
```json
{"home_id":"A","action":"confirm_change","pending_change_id":"pc-…","request_id":"phone-a-<uuid>","expected_revision":4}
```
`action` is `confirm_change` or `reject_change`. Both return `202 {job_id, status, accepted_revision, duplicate?}`.

## 3. What the phone expects from jobs and state (A + D)

- Message job: `queued` → `running` (with `stage`) → either
  - `awaiting_confirmation`, plus a `pending_changes[]` entry in `?home=A` state with `status: "pending"`, `feasible: true` and `edits[].old_time/new_time` in 12-hour time, or
  - `completed` with `result.outcome = "infeasible"`, plus a pending change with `feasible: false`, an `explanation` and `infeasible_reasons`. The phone shows it with an **OK** button, which sends `reject_change` to clear it. **Please confirm:** should infeasible results leave a pending change, or only `result.message`? The phone handles both.
- Action job: `completed` with `result.outcome` of `applied` or `rejected`, after which `revision` goes up.
- `pending_changes[].status` values the phone checks: only `"pending"` is shown.
- The phone shows `state.events` as-is, sorted by `sequence`. **It does no privacy filtering.** The `?home=` view must already contain only that home's events, with `home_views` text swapped into `text`.

## 4. Error behavior (from PRD §11.2, already built)

| Code | Phone shows |
|---|---|
| UNAUTHORIZED | Code entry sheet |
| FORBIDDEN | "That code isn't for this home" + Enter the code again + Change household |
| STALE_REVISION | Refreshes, then "The plan changed while you were typing…". The text stays in the box so the user can resend. |
| JOB_RUNNING | "Planning is running. Try again in a moment." |
| RATE_LIMITED | "Busy, retry in a moment." |
| NOT_FOUND | "That request was lost, maybe because the demo was reset." |
| BACKEND_DOWN | Red banner: "Backend not running on port 8000." The last plan stays visible. |

A `generation` bump (reset) clears any in-flight request on the phone.

## 5. Requests for B (small)

- `useJob` stops silently on `NOT_FOUND`, so the phone can't tell that a job vanished unless `generation` changes. It would help if `useJob` returned the error, or a `{job, error}` pair.
- `time.ts` hard-codes 6:00 PM and 15-minute slots. That's fine while `horizon_start` and `slot_minutes` never change.
