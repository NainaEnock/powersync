"""PowerSync API (PRD §11). Run from the repo root with .venv active:

    python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

One process, one worker. State lives in memory; reset restores the scenario.
"""

from __future__ import annotations

import hmac
import os
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from .simulation.agent_seam import load_agents  # noqa: E402
from .simulation.scenario import load_raw  # noqa: E402
from .simulation.appliances import catalog_view  # noqa: E402
from .simulation.schema import HOME_IDS, ActionBody, ApplianceBody, MessageBody, TariffBody  # noqa: E402
from .simulation.store import Store, StoreError  # noqa: E402

VERSION = "0.2.0"
MAX_BODY = 16 * 1024
DIST = ROOT / "frontend" / "dist"


# ---------------------------------------------------------------- auth

def _tok(name: str) -> str:
    return os.getenv(name, "").strip()


def tokens() -> dict[str, str]:
    return {
        "admin": _tok("DEMO_ADMIN_TOKEN"),
        "A": _tok("DEMO_HOME_A_TOKEN"), "B": _tok("DEMO_HOME_B_TOKEN"), "C": _tok("DEMO_HOME_C_TOKEN"),
    }


def auth_mode() -> str:
    vals = list(tokens().values())
    if not any(vals):
        return "dev-open"
    return "enforced" if all(vals) else "partial"


def bearer(request: Request) -> str:
    h = request.headers.get("authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else ""


def _eq(a: str, b: str) -> bool:
    return bool(a) and bool(b) and hmac.compare_digest(a.encode(), b.encode())


def is_admin(request: Request) -> bool:
    t = tokens()["admin"]
    return not t or _eq(bearer(request), t)


def require_admin(request: Request) -> None:
    if is_admin(request):
        return
    if not bearer(request):
        raise StoreError(401, "UNAUTHORIZED", "Enter the admin code.")
    raise StoreError(403, "FORBIDDEN", "That code isn't the admin code.")


def require_home(request: Request, home_id: str) -> None:
    if home_id not in HOME_IDS:
        raise StoreError(400, "UNKNOWN_HOME", f"There's no home '{home_id}'. Use A, B, or C.")
    t = tokens()
    if not t[home_id] or is_admin(request) and t["admin"]:
        return
    got = bearer(request)
    if _eq(got, t[home_id]):
        return
    if not got:
        raise StoreError(401, "UNAUTHORIZED", "Enter your household code.")
    raise StoreError(403, "FORBIDDEN", "That code isn't for this home.")


# ---------------------------------------------------------------- rate limit (per role, sliding window)

_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(key: str, limit: int = 20, window_s: float = 10.0) -> None:
    q = _hits[key]
    t = time.monotonic()
    while q and t - q[0] > window_s:
        q.popleft()
    if len(q) >= limit:
        raise StoreError(429, "RATE_LIMITED", "Busy, retry in a moment.")
    q.append(t)


# ---------------------------------------------------------------- app

def create_app() -> FastAPI:
    interpret, coordinate, impl, announce = load_agents()
    app = FastAPI(title="PowerSync", version=VERSION)
    app.state.store = None
    app.state.impl = (interpret, coordinate, impl)
    app.state.announce = announce

    def store() -> Store:
        if app.state.store is None:  # created lazily inside the running event loop
            i, c, im = app.state.impl
            app.state.store = Store(i, c, im, openrouter_configured=bool(_tok("OPENROUTER_API_KEY")),
                                    announce=app.state.announce)
        return app.state.store

    def err(status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse({"error": {"code": code, "message": message}}, status_code=status,
                            headers={"Cache-Control": "no-store"})

    @app.exception_handler(StoreError)
    async def _store_error(_: Request, e: StoreError):
        return err(e.status, e.code, e.message)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError):
        first = e.errors()[0] if e.errors() else {}
        where = ".".join(str(x) for x in first.get("loc", []) if x != "body")
        return err(400, "BAD_REQUEST", f"Invalid request{f' ({where})' if where else ''}: {first.get('msg', 'bad input')}")

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, e: StarletteHTTPException):
        if e.status_code == 404:
            return err(404, "NOT_FOUND", "Not found.")
        if e.status_code == 405:
            return err(405, "BAD_REQUEST", "Method not allowed.")
        return err(e.status_code, "BAD_REQUEST", str(e.detail))

    @app.middleware("http")
    async def _limits_and_cache(request: Request, call_next):
        is_api = request.url.path.startswith("/api")
        if is_api and request.method == "POST":
            cl = request.headers.get("content-length")
            if cl and cl.isdigit() and int(cl) > MAX_BODY:
                return err(413, "PAYLOAD_TOO_LARGE", "Request body is over 16 KB.")
            body = await request.body()
            if len(body) > MAX_BODY:
                return err(413, "PAYLOAD_TOO_LARGE", "Request body is over 16 KB.")
        response = await call_next(request)
        if is_api:
            response.headers["Cache-Control"] = "no-store"
        return response

    # ------------------------------------------------------------ routes

    @app.get("/api/health")
    async def health():
        s = store()
        return {
            "status": "ok", "version": VERSION, "scenario_id": load_raw()["scenario_id"],
            "revision": s.revision, "generation": s.generation, "auth_mode": auth_mode(),
            "agent_impl": s.agent_impl, "openrouter_configured": bool(_tok("OPENROUTER_API_KEY")),
            "model": _tok("OPENROUTER_MODEL") or None,
        }

    @app.get("/api/state")
    async def state(request: Request, home: Optional[str] = None):
        s = store()
        if home is not None:
            require_home(request, home)
            return s.home_view(home)
        require_admin(request)  # the whole dashboard view needs the admin code (PRD §11.3 gap, closed)
        return s.dashboard_view(admin=True)

    @app.post("/api/message", status_code=202)
    async def message(request: Request, body: MessageBody):
        s = store()
        require_home(request, body.home_id)
        dup = s.duplicate(body.home_id, body.request_id)
        if dup:
            return {"job_id": dup.id, "status": dup.status, "accepted_revision": s.revision, "duplicate": True}
        rate_limit(f"home-{body.home_id}")
        busy = [j for j in s.active_jobs() if j.kind == "message" and j.home_id == body.home_id]
        if busy:
            raise StoreError(409, "JOB_RUNNING", "Your last request is still being read. Try again in a moment.")
        job = s.submit_message(body.home_id, body.text.strip(), body.request_id, body.reply_to_event_id)
        return {"job_id": job.id, "status": job.status, "accepted_revision": s.revision}

    @app.post("/api/action", status_code=202)
    async def action(request: Request, body: ActionBody):
        s = store()
        require_home(request, body.home_id)
        dup = s.duplicate(body.home_id, body.request_id)
        if dup:
            return {"job_id": dup.id, "status": dup.status, "accepted_revision": s.revision, "duplicate": True}
        rate_limit(f"home-{body.home_id}")
        pc = s.pending.get(body.pending_change_id)
        if pc is None:
            raise StoreError(404, "NOT_FOUND", "That change wasn't found. The demo may have been reset.")
        if pc.home_id != body.home_id:
            raise StoreError(403, "FORBIDDEN", "That change belongs to another home.")
        if body.action == "reject_change":
            if pc.status != "pending":
                raise StoreError(409, "STALE_REVISION", "That change is no longer waiting for confirmation.")
            job = s.reject_change(pc, body.request_id)
            return {"job_id": job.id, "status": job.status, "accepted_revision": s.revision}
        if s.mutation_job_id:
            raise StoreError(409, "JOB_RUNNING", "Planning is running. Try again in a moment.")
        s.check_confirmable(pc)
        job = s.submit_confirm(pc, body.request_id)
        return {"job_id": job.id, "status": job.status, "accepted_revision": s.revision}

    @app.post("/api/coordinate", status_code=202)
    async def coordinate_route(request: Request):
        s = store()
        require_admin(request)
        rate_limit("admin")
        if s.mutation_job_id:
            raise StoreError(409, "JOB_RUNNING", "Planning is running. Try again in a moment.")
        job = s.submit_coordinate(None)
        return {"job_id": job.id, "status": job.status, "accepted_revision": s.revision}

    @app.post("/api/tariff")
    async def tariff(request: Request, body: TariffBody):
        s = store()
        require_admin(request)
        if s.mutation_job_id or s.active_jobs():
            raise StoreError(409, "JOB_RUNNING", "Planning is running. Try again in a moment.")
        s.set_tariff(body.tariff_mode)
        return {"revision": s.revision, "tariff_mode": s.tariff_mode}

    @app.get("/api/appliances/catalog")
    async def appliance_catalog():
        return catalog_view()

    @app.post("/api/appliances")
    async def appliances(request: Request, body: ApplianceBody):
        """A resident adds a catalog appliance to their own home, or removes one of their own."""
        s = store()
        require_home(request, body.home_id)
        rate_limit(f"home-{body.home_id}")
        if s.mutation_job_id or s.active_jobs():
            raise StoreError(409, "JOB_RUNNING", "Planning is running. Try again in a moment.")
        if body.action == "add":
            if not body.kind:
                raise StoreError(400, "BAD_REQUEST", "Pick an appliance to add.")
            task = s.add_appliance(body.home_id, body.kind, body.deadline_slot)
            return {"revision": s.revision, "task_id": task.id}
        if not body.task_id:
            raise StoreError(400, "BAD_REQUEST", "Pick an appliance to remove.")
        s.remove_appliance(body.home_id, body.task_id)
        return {"revision": s.revision, "task_id": body.task_id}

    @app.get("/api/jobs/{job_id}")
    async def job(job_id: str):
        j = store().jobs.get(job_id)
        if j is None:
            raise StoreError(404, "NOT_FOUND", "That request wasn't found. The demo may have been reset.")
        return j.model_dump()

    @app.post("/api/reset")
    async def reset(request: Request):
        s = store()
        require_admin(request)
        s.reset()
        return {"revision": s.revision, "generation": s.generation, "tariff_mode": s.tariff_mode}

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def api_404(rest: str):
        raise StoreError(404, "NOT_FOUND", f"No API route /api/{rest}.")

    # ------------------------------------------------------------ built frontend (demo: one origin)

    if DIST.is_dir():
        no_cache = {"Cache-Control": "no-cache"}
        if (DIST / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            f = (DIST / path).resolve()
            if path and f.is_file() and DIST.resolve() in f.parents:
                headers = no_cache if f.name in ("sw.js", "manifest.webmanifest", "index.html") or f.name.startswith("workbox-") else None
                return FileResponse(f, headers=headers)
            if "." in path.rsplit("/", 1)[-1]:  # a missing file (e.g. /icons/icon-192.png): 404, never HTML
                raise StoreError(404, "NOT_FOUND", f"No file /{path}.")
            return FileResponse(DIST / "index.html", headers=no_cache)

    return app


app = create_app()
