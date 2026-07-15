"""FastAPI wrapper for the NEW game loop. The old game engine (runtime/orchestrator/content/gen/world/
npc/combat/rules) has been removed — the player interface is built on mind+citygraph+worldgen.

Here: authentication, rate limits, debug stands (/citydebug, /minddebug, /npcdebug) and routers for the game
loop (server/play/*): scene, action, combat, magic, trading, dungeons, economy.

Key functions
-------------
app : FastAPI instance; router and middleware hub for the game engine.
index() -> HTMLResponse : Serve landing page to new players.
play_page(request) -> HTMLResponse : Serve game page; redirect if not authenticated.
login_page() -> HTMLResponse : Serve login page for email-based authentication.
run(host, port) -> None : Start the uvicorn web server on configured host/port.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..inference import LLMBadOutput, LLMUnavailable
from .play import router as _play_router
from .routes_auth import router as _auth_router
from .routes_citydebug import router as _citydebug_router
from .routes_minddebug import router as _minddebug_router
from .routes_npcdebug import router as _npcdebug_router
from .routes_usage import router as _usage_router

WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
app = FastAPI(title="AI-DnD Engine")


# ── replay recorder: tap /api/play/* JSON responses, mirror the UI render into a per-session text
# file (data/playtest_logs). Registered FIRST so it sits INNER to GZip — it reads the raw
# uncompressed JSON body before compression. Best-effort; never breaks the request path. ──
@app.middleware("http")
async def _replay_tap(request: Request, call_next):
    from fastapi.responses import Response as _Response

    from .play import replay

    path = request.url.path
    if not path.startswith("/api/play/"):
        return await call_next(request)
    resp = await call_next(request)
    try:
        wid = getattr(request.state, "wid", None)
        ctype = resp.headers.get("content-type", "")
        if wid is not None and "application/json" in ctype and hasattr(resp, "body_iterator"):
            body = b""
            async for chunk in resp.body_iterator:
                body += chunk
            resp = _Response(content=body, status_code=resp.status_code,
                             headers=dict(resp.headers), media_type=resp.media_type)
            import json as _json
            try:
                data = _json.loads(body) if body else {}
            except Exception:  # noqa: BLE001
                data = {}
            req_json = getattr(request.state, "replay_req", None)
            replay.record(wid, path[len("/api/play/"):], req_json, data, resp.status_code)
    except Exception:  # noqa: BLE001 — recorder is best-effort, must never break gameplay
        pass
    return resp


# Compress responses — the city map SVG alone is ~650KB uncompressed; gzip cuts it ~85%.
from starlette.middleware.gzip import GZipMiddleware  # noqa: E402

app.add_middleware(GZipMiddleware, minimum_size=1000)

# Detailed session file log (for debugging, downloaded from /api/play/debuglog)
from . import debuglog  # noqa: E402
from .play.engine.core import current_world_id  # noqa: E402

debuglog.setup(current_world_id)


@app.exception_handler(LLMUnavailable)
async def _llm_unavailable(request: Request, exc: LLMUnavailable) -> JSONResponse:
    """Project rule: without LLM we don't substitute content — give honest error to player."""
    return JSONResponse(status_code=503, content={
        "error": "llm_unavailable", "detail": str(exc),
        "narr": ["Рассказчик недоступен — мир замер. Повтори действие чуть позже."]})


@app.exception_handler(LLMBadOutput)
async def _llm_bad_output(request: Request, exc: LLMBadOutput) -> JSONResponse:
    return JSONResponse(status_code=502, content={
        "error": "llm_bad_output", "detail": str(exc),
        "narr": ["Рассказчик сбился с мысли. Повтори действие."]})


@app.middleware("http")
async def _log_requests(request: Request, call_next):
    """Request trace + FULL traceback of any unhandled exception to file log."""
    import logging
    import time
    log = logging.getLogger("aidnd.req")
    t0 = time.perf_counter()
    try:
        resp = await call_next(request)
    except Exception:                                      # noqa: BLE001 — log and re-raise
        log.exception("НЕОБРАБОТАННОЕ исключение: %s %s", request.method, request.url.path)
        raise
    dt = (time.perf_counter() - t0) * 1000
    if request.url.path.startswith("/api/"):
        log.debug("%s %s → %s (%.0f мс)", request.method, request.url.path, resp.status_code, dt)
    return resp


app.include_router(_auth_router)
app.include_router(_usage_router)
app.include_router(_citydebug_router)
app.include_router(_npcdebug_router)
app.include_router(_minddebug_router)
app.include_router(_play_router)


@app.on_event("startup")
async def _init_service_db() -> None:
    """Create service tables. DB unavailable → anonymous demo mode still works."""
    try:
        from .db import init_db
        await init_db()
    except Exception as exc:                       # noqa: BLE001
        import logging
        logging.getLogger("aidnd").warning("service DB unavailable (%s) — auth disabled", exc)


@app.middleware("http")
async def _no_cache(request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith("/static") or request.url.path == "/":
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/")
def index() -> HTMLResponse:
    with open(os.path.join(WEB_DIR, "landing.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/play")
async def play_page(request: Request) -> HTMLResponse:
    """Game — only under session (full email-based authentication)."""
    from fastapi.responses import RedirectResponse

    from .auth import user_for_token
    from .db import SessionLocal
    token = request.cookies.get("aidnd_session", "")
    user, db_ok = None, True
    try:
        async with SessionLocal() as db:
            if token:
                user = await user_for_token(db, token)
    except Exception:                                      # noqa: BLE001 — DB down → demo mode
        db_ok = False
    if not user and db_ok and not os.environ.get("AIDND_OPEN_PLAY"):
        return RedirectResponse("/login?next=/play", status_code=303)
    with open(os.path.join(WEB_DIR, "play.html"), encoding="utf-8") as f:
        # no-cache: the client is a single evolving file; a stale copy = "I still see the old UI"
        return HTMLResponse(f.read(), headers={"Cache-Control": "no-cache, must-revalidate"})


@app.get("/login")
def login_page() -> HTMLResponse:
    with open(os.path.join(WEB_DIR, "login.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())


if os.path.isdir(WEB_DIR):
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

# NPC portraits from pool (worldgen) — files in data/portraits (not in git, rsync to prod)
_PORTRAITS = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "portraits")
if os.path.isdir(_PORTRAITS):
    app.mount("/portraits", StaticFiles(directory=_PORTRAITS), name="portraits")


def run(host: str = "127.0.0.1", port: int | None = None) -> None:
    import uvicorn
    port = port or int(os.environ.get("PORT", "8000"))   # PORT env → convenient for preview/proxy
    print(f"AI-DnD веб-сервер: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
