# NOVA 2026 tools guide for an AI collaborator

This is a reference for the team’s neighborhood energy coordination demo. Read it alongside the project PRD, team handoff guide, and live agent conversation addendum. The team may rename the product. Use the names and interfaces already in the repository when writing code.

Three household agents interpret resident requests and exchange scheduling proposals. A coordinator routes the conversation and calls a deterministic scheduling engine. Three installed phone web apps and one projected dashboard read the same backend state. The dashboard shows the actual proposals, replies, tool results, and the final validated schedule as they happen.

## 1. Resources and rules from NOVA

| Resource | What NOVA provided or referenced | How to use it |
|---|---|---|
| OpenRouter | One team API key after submitting the organizer form. The key is sent by email. | Power model calls in the running project, including product smoke tests. Keep calls in the Python backend. |
| Model Context Protocol (MCP) | The supplied technical excerpt explicitly marks MCP server use as mandatory. It links to a server directory. | Use a real MCP client/server connection in the runtime. Our plan is a custom energy-tool server. The excerpt gives no rule about whether the server must come from the directory. Verify that detail with organizers if eligibility depends on it. |
| MCP server directory | `mcpservers.org` and the `/all` directory. | Discover servers, then read each provider’s setup and permissions. The directory itself is a listing. Our energy demo uses tools we implement. |
| React | The Hacker Guide links to the React reference. | Build the household phone screens and projected dashboard. |
| FastAPI | The Hacker Guide links to the FastAPI documentation. | Serve project routes, queue jobs, validate inputs, and expose live state. |
| OpenAI SDK examples | The technical excerpt shows Python and TypeScript OpenAI SDK clients configured for OpenRouter. | Use as reference for an OpenAI-compatible client. The project PRD chooses Python `httpx` for the actual integration. |
| Discord | Organizers direct teams to Discord for event communications. | Check announcements and ask event-specific questions there. |
| AI Video Generation Resources | The Hacker Guide’s table of contents names a section. The supplied excerpt omits the provider details. | Treat these as optional resources and check the full section for provider names and access terms. The energy demo has no video generation dependency. |

The team key is for **project functionality only**. Use personal Claude Code, Copilot, or other coding-assistant access for development. Keep the NOVA key out of Git, including private repositories, browser code, URLs, logs, screenshots, and prompts. Put it in a local backend `.env` or the backend host’s environment. Commit a blank `.env.example` with variable names only. If code loads dotenv, keep the runtime key out of variables prefixed with `VITE_`.

The supplied guide allows teams of one to four. Disclose pre-existing project code during judging. Libraries are allowed. The organizer message gives six hours to hack and five minutes to present, followed by one to two minutes of questions.

- [NOVA 2026 Hacker Guide](https://docs.google.com/document/d/e/2PACX-1vRP3wXpj9wwxF-Vsh35jrj6-UolS0sS7PabDWVRSJ3oIP8CfLE08v4-xjZtFL59C2wYBf9sKbSbSiSb/pub)
- [NOVA Tech Details](https://docs.google.com/document/d/e/2PACX-1vQ23oBFZ0mWiZ0exAmSPhdybzYUwyTXEW48iOTUnAyoLNMuEZD7s0safFPGlKPXsoWA7ucAhpb_zddV/pub)
- [MCP server directory](https://mcpservers.org/all)

Organizer rules above come from the Hacker Guide excerpts and organizer message the team supplied. The published Google Docs did not open during verification. Use organizer announcements for any details beyond those excerpts.

## 2. Project stack and ownership

The following are the team’s implementation choices. Only the resources identified in Section 1 came from the supplied NOVA materials.

| Layer | Tools | Owner and purpose |
|---|---|---|
| Phone and dashboard UI | React, TypeScript, Vite, CSS | A builds phone UI. B owns shared frontend wiring, routing, and the dashboard. |
| Dashboard visuals | Recharts, Lucide React | B uses charts for demand and icons for controls. Plain CSS can handle the schedule timeline. |
| Installable phone app | Web app manifest, service worker, `vite-plugin-pwa` | A and B make the phone UI launch from a home-screen icon. Cache the app shell and fetch current `/api` state from the server. |
| Backend | Python, FastAPI, Uvicorn, Pydantic | D runs one authoritative API process, validates requests, and manages the queue, state, and revisions. |
| Model access | OpenRouter, `httpx` | C calls the model from the backend and handles function-tool requests. |
| Runtime tools | MCP, standalone `fastmcp` Python package | C exposes and calls the energy tools through MCP. D provides the deterministic functions used by the tools. |
| Energy calculations | Team-written Python, synthetic JSON fixtures | D implements scheduling, cost, peak and kWh calculations, and final validation. |
| Live updates | Same-origin HTTP requests and polling | B polls `/api/state` about once a second while the UI is active. D publishes events during the job. |
| Local configuration and tests | `python-dotenv`, `pytest` | D manages backend environment loading and engine tests. C checks real model and MCP calls. |
| Phone connectivity | `cloudflared` Quick Tunnel | B exposes the local FastAPI demo over HTTPS for the three phones. |
| Collaboration | Git, GitHub, branch per owner | B integrates small PRs. D owns backend dependencies and shared API contract. B owns frontend dependencies. |

Use the repo’s pinned dependency versions and lockfiles. If starting from the PRD scaffold, its planned baseline is Python 3.11 and a Node LTS compatible with the installed Vite version. D controls the Python requirements file. B controls the npm dependencies. The planned MVP uses synthetic loads, a modeled tariff, and a simulated shared capacity. It needs no utility credentials, electricity-market API, or real appliance access.

- [React reference](https://react.dev/reference/react) · [Vite guide](https://vite.dev/guide/) · [Vite API proxy](https://vite.dev/config/server-options#server-proxy)
- [FastAPI docs](https://fastapi.tiangolo.com/) · [Uvicorn](https://www.uvicorn.org/) · [Pydantic](https://docs.pydantic.dev/) · [HTTPX](https://www.python-httpx.org/)
- [Recharts](https://recharts.org/) · [Lucide React](https://lucide.dev/guide/packages/lucide-react) · [PWA plugin](https://vite-pwa-org.netlify.app/) · [Installable PWA reference](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Making_PWAs_installable)
- [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) · [Git documentation](https://git-scm.com/doc)

## 3. OpenRouter runtime integration

1. Set `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` on the backend. Keep both placeholders in `.env.example`.
2. Select a model that the team key can access and that supports function tool calls. Check the catalog, then smoke-test one actual tool request. Use the configured model ID and keep the team’s approved request budget.
3. Send `POST https://openrouter.ai/api/v1/chat/completions` with the model, messages, tool schemas, and a bearer authorization header. Use the PRD’s async Python `httpx` path.
4. When the assistant returns `tool_calls`, preserve the assistant message. Validate each allowed tool name and arguments, call the MCP server from the backend, and append the result as a `role: "tool"` message with its matching `tool_call_id`.
5. Continue within the existing round and time limits. Validate model-produced edits and proposals before they influence planning. Use actual engine results for all cost, load, and capacity statements.

The event examples use the OpenAI SDK with `https://openrouter.ai/api/v1` as the base URL. Python calls that setting `base_url` and the JavaScript SDK calls it `baseURL`. The supplied SDK example uses the Responses API. The current project contract uses Chat Completions. Follow the selected endpoint’s message and tool-response format consistently.

- [OpenRouter documentation index for AI](https://openrouter.ai/docs/llms.txt) · [Quickstart](https://openrouter.ai/docs/quickstart) · [Tool calling](https://openrouter.ai/docs/guides/features/tool-calling) · [Model catalog endpoint](https://openrouter.ai/api/v1/models)

## 4. The MCP server and its four planned tools

MCP is the protocol for discovering and calling tools. FastMCP is the Python implementation framework we chose. `gridmates-energy` is the custom server name in the PRD. Use the existing repo name if the team has already renamed it.

| Planned tool | Role in the demo |
|---|---|
| `get_home_context` | Fetch the caller’s authorized task and constraint snapshot. |
| `find_feasible_schedule` | Ask the deterministic engine for a feasible candidate under approved timing flexibility. |
| `evaluate_schedule` | Calculate metrics and report validation findings for a candidate. |
| `compare_schedules` | Compare per-home and neighborhood outcomes against the selected baseline. |

1. Define typed tools in `backend/tools/energy_server.py` using FastMCP and D’s pure engine functions.
2. Launch the local MCP server as a stdio subprocess. Use the same Python environment as the backend. Send diagnostic logs to stderr so stdout carries protocol messages.
3. Smoke-test from the MCP client. List tools and call `evaluate_schedule` against a fixture. Confirm a structured result.
4. Advertise the allowed tool schemas to OpenRouter as function tools. When the model asks to run one, dispatch it through the actual MCP client session. The backend supplies canonical scenario values and household authorization.
5. Publish a safe result summary to the live dashboard. D owns final validation and atomically commits the plan and its metrics. Tool calls evaluate snapshots and return results.

Household and coordinator messages travel through the orchestrator. The MCP connection handles tool calls. D appends events during the running job, and B displays those events as English messages and tool cards as the dashboard polls. The four participants are Home A, Home B, Home C, and the Coordinator.

- [MCP server development](https://modelcontextprotocol.io/docs/develop/build-server) · [MCP client development](https://modelcontextprotocol.io/docs/develop/build-client) · [FastMCP project](https://pypi.org/project/fastmcp/) · [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)

## 5. FastAPI, frontend, and the demo connection

1. **Development.** Run Vite on the frontend dev port and Uvicorn on `127.0.0.1:8000` on the integration laptop. Configure Vite to proxy `/api` to FastAPI. Use relative `/api/...` URLs in React so requests work from both laptops and phones.
2. **API contract.** Use `docs/contract.md` and the PRD for paths and payloads. The planned flow uses `GET /api/health`, `GET /api/state`, `POST /api/message`, `POST /api/action`, `POST /api/coordinate`, `GET /api/jobs/{job_id}`, and `POST /api/reset`. Confirm an interpreted requirement edit before committing it. Jobs and revisions keep multiple phone actions consistent.
3. **Demo build.** Run `npm run build` in `frontend`. Serve `frontend/dist` through FastAPI. Match `/api` routes before the frontend’s route fallback. Keep one Uvicorn worker for the in-memory demo state.
4. **HTTPS.** Start the tunnel against the API port with `cloudflared tunnel --url http://127.0.0.1:8000`. Open the returned HTTPS `/phone` URL on each phone. Install it from the browser and select a separate household. Keep the tunnel running for the presentation.
5. **One end-to-end check.** Send a phone request, see it appear on the dashboard, observe an actual peer message and MCP result, then confirm the phone and dashboard show the same applied plan revision. Label fixture and replay modes when used.

## 6. Paste this prompt with the guide

```text
Use this NOVA Tools Guide alongside the project PRD, Team Handoff Guide, and
Live Agent Conversation Addendum. My role is [A/B/C/D]. First inspect the
current repo, dependencies, and docs/contract.md. Follow the existing field
names and ownership. Identify the smallest runnable slice for my checkpoint.

Use the team’s agreed stack. Keep the NOVA OpenRouter key in the runtime
backend environment. Coding assistants use their own access. The project
must demonstrate actual MCP client-to-server calls and show the live English
conversation among the three household agents and coordinator. Distinguish
fixtures from live results. If a required interface is missing, describe the
smallest stub and exact handoff to its owner. Report the check you ran and
the command or click my teammate should use to verify it.
```
