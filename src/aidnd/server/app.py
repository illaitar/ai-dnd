"""FastAPI-оболочка НОВОГО контура. Старый игровой движок (runtime/orchestrator/content/gen/world/
npc/combat/rules) снесён — интерфейс игрока строится заново на mind+citygraph+worldgen (aidnd.play).

Пока здесь: авторизация, лимиты, дебаг-страницы города (/citydebug), разума (/minddebug, /npcdebug).
Игровой контур (WS/сессия/веб-UI) добавим следующими кирпичами.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .routes_auth import router as _auth_router
from .routes_citydebug import router as _citydebug_router
from .routes_minddebug import router as _minddebug_router
from .routes_npcdebug import router as _npcdebug_router
from .play import router as _play_router
from .routes_usage import router as _usage_router

WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
app = FastAPI(title="AI-DnD Engine")

# подробный файловый лог сессии (для отладки, скачивается из /api/play/debuglog)
from . import debuglog                                     # noqa: E402
from .play.engine.core import current_world_id             # noqa: E402
debuglog.setup(current_world_id)


@app.middleware("http")
async def _log_requests(request: Request, call_next):
    """Трасса запроса + ПОЛНЫЙ трейсбек любого необработанного исключения в файловый лог."""
    import logging
    import time
    log = logging.getLogger("aidnd.req")
    t0 = time.perf_counter()
    try:
        resp = await call_next(request)
    except Exception:                                      # noqa: BLE001 — залогировать и пробросить
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
    """Создать таблицы сервиса. БД недоступна → анонимный демо-режим всё равно работает."""
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
    """Игра — только под сессией (полная авторизация по email)."""
    from fastapi.responses import RedirectResponse
    from .auth import user_for_token
    from .db import SessionLocal
    token = request.cookies.get("aidnd_session", "")
    user, db_ok = None, True
    try:
        async with SessionLocal() as db:
            if token:
                user = await user_for_token(db, token)
    except Exception:                                      # noqa: BLE001 — БД лежит → демо-режим
        db_ok = False
    if not user and db_ok and not os.environ.get("AIDND_OPEN_PLAY"):
        return RedirectResponse("/login?next=/play", status_code=303)
    with open(os.path.join(WEB_DIR, "play.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/login")
def login_page() -> HTMLResponse:
    with open(os.path.join(WEB_DIR, "login.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())


if os.path.isdir(WEB_DIR):
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

# портреты NPC из пула (worldgen) — файлы в data/portraits (в гит не идут, на прод rsync)
_PORTRAITS = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "portraits")
if os.path.isdir(_PORTRAITS):
    app.mount("/portraits", StaticFiles(directory=_PORTRAITS), name="portraits")


def run(host: str = "127.0.0.1", port: int | None = None) -> None:
    import uvicorn
    port = port or int(os.environ.get("PORT", "8000"))   # PORT env → удобно для preview/прокси
    print(f"AI-DnD веб-сервер: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
