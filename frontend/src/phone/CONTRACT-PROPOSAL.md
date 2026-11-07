# Phone contract proposal (A → B, D) for G2

A's proposal for `docs/contract.md` (D owns that file). Field names follow PRD §10–11. Anything marked **NEW** isn't in the PRD yet and needs an OK.

## 1. Component (A + B)

```tsx
import PhoneApp from './phone/PhoneApp';
<PhoneApp homeId={homeId} state={householdState} api={phoneApi} />
```

- `homeId: 'A' | 'B' | 'C' | null`. `null` shows the household picker.
- `state`: the response of `GET /api/state?home=<homeId>` (or B's labeled sample data), or `null` while loading.
- `api`: B's adapter, which must satisfy `PhoneApi` in `phone/phoneTypes.ts`:
  - `dataMode: 'live' | 'sample'`, `connection: 'connected' | 'connecting' | 'backend_down' | 'error'`, `authMode` (from `/api/health`), `stateError` (last error from state polling, such as UNAUTHORIZED or FORBIDDEN)
  - `sendMessage(req)` → `POST /api/message`, `sendAction(req)` → `POST /api/action`, `getJob(id)` → `GET /api/jobs/{id}`
  - `refresh()`: re-fetch state now
  - `setToken(home, token)`, `hasToken(home)`, `setHome(home | null)`
- Errors are thrown as `{status, code, message}`, using the codes in PRD §11.2. The adapter should throw `code: 'BACKEND_DOWN'` when the proxy returns 500/502/504 or the fetch fails.
- B polls state every second while visible. The phone polls only its own jobs.

**Home selection and codes:** `phone/session.ts` provides `resolveHomeId()` (`?home=` first, then localStorage), `storeHome()`, `getHomeToken()` and `storeHomeToken()`. B's `App.tsx` and `api.ts` can use these so there's one source of truth. The token only ever goes in `Authorization: Bearer`.

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

## 5. Shared formatting

`phone/format.ts` has the TypeScript 12-hour formatter (`slotToTime`). B can move it to a shared file if the dashboard wants the same one. Tell A first.

## 6. Home colors (A + B)

The phone uses `state.homes[].color`. Fallbacks if missing: A `#2563eb`, B `#d97706`, C `#059669`.
