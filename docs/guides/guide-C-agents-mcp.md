# Guide C: household agents and MCP

**Your job:** the AI part. The interpreter turns a resident's words into a proposed change. Three household agents plus a coordinator negotiate a plan through the custom `powersync-energy` MCP server. You also write every message people read in the conversation.

**You own:** `backend/agents/` and `backend/tools/`. **Don't edit** `backend/main.py`, `backend/simulation/`, or Python dependencies. Ask D.

**Read first:** PRD §1, §9.4, §10 (AgentEvent), §12, §13, §14, §25. Also `02-Team-Schedule.md`.

## Checkpoints

| Step | Time | Do | Done when | Send |
|---|---|---|---|---|
| C1 | 0:00 | Pick a fast tool-calling model from the event key's catalog. Copy the ID exactly into `.env`. | A plain request returns | none |
| C2 | 0:10–0:20 | Agree with D on signatures: `interpret_request` and `coordinate_neighborhood`, both taking an `emit` callback that returns the stored event ID. Agree on the snapshot shape, `home_views`, the result envelope, and error codes. | Written in the contract | D: sample signature and output for the stub |
| C3 | 0:30 | **Time one real call** with a tool definition and a structured reply. | A number in seconds | Everyone: model and timing. B: one sample plan message and one review. |
| C4 | 0:30–0:50 | FastMCP stdio server with the four tools, using D's pure engine functions. A client lists the tools and calls `evaluate_schedule`. | A real MCP call with a structured result | D, B: command and sanitized output |
| C5 | 0:50–1:20 | Live interpreter: "I leave at 11 pm tonight…" becomes a proposed `a_ev` deadline edit. "Car ready by 8 pm" comes back infeasible with a reason. | D's confirm flow works with it | D, A: sample request and result |
| C6 | 1:20–1:35 | Coordinator: Plan 1 from the engine through MCP, announced in plain English and emitted live | Plan 1 shows on the dashboard before the job ends | B, D: event IDs |
| C7 | 1:35–1:50 | **Real peer exchange:** B's agent objects with a specific request to A. A's agent receives it as a message, checks its deadline and cost, and answers with `reply_to_event_id`. The offered concession becomes a pin, and the engine evaluates Plan 2. | G8 passes. Plan 2 costs B less and A the same. | Everyone: event IDs, latency |
| C8 | 1:50–3:05 | Per-home `home_views` for every broadcast. No cost objections under flat. Third-person trigger text for deadline changes. | Flat, then Coordinate, gives no cost objections. Phone views name only their own home. | D, A, B |
| C9 | 3:05–5:00 | Limits: three rounds, budgets in environment settings, one retry, Pydantic validation with one repair. Test malformed output, timeout, a forbidden edit to another home's task, and failure fallback. | Each fails cleanly with the old plan kept | A, B, D: the errors the UI will see |
| C10 | After 5:00 | One live run. Confirm the MCP and peer events. Help B record the backup. | Live run passes | B: result, and whether to use the backup |

## Wording checklist (every message a person reads)

- Plain English. No "candidate", "slot", "concession", "constraint", or task IDs.
- Every plan says its name, what moved, and how it differs from the last plan.
- Times are 12-hour. Dollar amounts come from code, never from the model.
- Reviews sound like a friendly neighbor and are one or two sentences.
- Phone versions (`home_views`) mention only that home's appliances and costs.
- Set `source: system_template` on code-written text and `source: model` on model-written text.

## Things that went wrong in the trial

- **The free model was too slow.** Home B timed out at 40 s and 100 s. Measure at 0:30 and choose based on that.
- **The quota ran out from testing.** Automated tests use a stub or fake model. Count every real run.
- **Home C claimed Home A's deadline.** The trigger said "I need my car by…". Write it in the third person: "Home A's resident changed…".
- **No negotiation happened** because the old scenario had no conflict. The new scenario does (PRD §9.4). If agents still all accept, give each agent its share of use in expensive hours as a number and tell it to ask a specific neighbor for a specific change.
- **Messages arrived in one batch at the end.** Call `emit` for each event and publish each home's review as soon as it finishes.
- **The MCP schema field name** (`inputSchema` versus `input_schema`) depends on the installed version. Inspect it. Don't guess.
- **Logs on stdout break stdio MCP.** Send logs to stderr.

## Rules you must keep

- The event key is for runtime only, never for your coding assistant.
- Never print keys. Never commit `.env`.
- Never commit state, compute savings in prose, or relax a hard deadline. D validates and commits.
- An agent never reads another home's private context.

## First prompt for your assistant

```text
My role is C: agents and MCP for PowerSync. Read CLAUDE.md, docs/PRD.md (§9.4,
§10, §12-14, §25), docs/team-schedule.md, and docs/contract.md. I own only
backend/agents/ and backend/tools/. Don't edit backend/main.py,
backend/simulation/, or requirements; tell me what to ask D for.

We are at [time], checkpoint [gate], branch feat/agents-mcp. Build the next
slice from my guide: [step]. Use real MCP stdio calls, emit each event as it
happens, write plain-English text with 12-hour times, and keep limits in
environment settings. Never read or print secret values. Tests must use a stub
model, not the real key. Run `python -m pytest backend/agents -q` before you
finish, then tell me what works and what to send to whom.
```
