"""FastAPI-оболочка НОВОГО контура. Старый игровой движок (runtime/orchestrator/content/gen/world/
npc/combat/rules) снесён — интерфейс игрока строится заново на mind+citygraph+worldgen (aidnd.play).

Пока здесь: авторизация, лимиты, дебаг-страницы города (/citydebug), разума (/minddebug, /npcdebug).
Игровой контур (WS/сессия/веб-UI) добавим следующими кирпичами.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .routes_auth import router as _auth_router
from .routes_citydebug import router as _citydebug_router
from .routes_minddebug import router as _minddebug_router
from .routes_npcdebug import router as _npcdebug_router
from .routes_usage import router as _usage_router

WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
app = FastAPI(title="AI-DnD Engine")
app.include_router(_auth_router)
app.include_router(_usage_router)
app.include_router(_citydebug_router)
app.include_router(_npcdebug_router)
app.include_router(_minddebug_router)


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
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8><title>AI-DnD</title>"
        "<body style='font:15px/1.6 -apple-system,sans-serif;background:#0f1115;color:#e6e8ec;padding:48px'>"
        "<h1 style='font-size:20px'>AI-DnD — новый контур в сборке</h1>"
        "<p style='color:#9aa0aa'>Старый движок снесён; интерфейс игрока строится на "
        "mind + citygraph + worldgen.</p>"
        "<p>Дебаг: <a style='color:#3b9eff' href='/minddebug'>/minddebug</a> · "
        "<a style='color:#3b9eff' href='/citydebug'>/citydebug</a></p></body>")


@app.get("/login")
def login_page() -> HTMLResponse:
    with open(os.path.join(WEB_DIR, "login.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())


if os.path.isdir(WEB_DIR):
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def run(host: str = "127.0.0.1", port: int | None = None) -> None:
    import uvicorn
    port = port or int(os.environ.get("PORT", "8000"))   # PORT env → удобно для preview/прокси
    print(f"AI-DnD веб-сервер: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
