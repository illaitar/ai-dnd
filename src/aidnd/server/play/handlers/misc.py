"""Домен ПРОЧЕЕ (/hero /debuglog) — распил world.py. Имя героя, скачиваемый лог сессии."""

from __future__ import annotations

from fastapi import Request

from aidnd.server.play.engine.core import _pc_name, _pc_save, _pc_set_name, router
from aidnd.server.play.engine.world import _play


@router.post("/api/play/hero")
async def set_hero(request: Request):
    """Задать имя героя (с лендинга) — один раз для нового мира; не перетирать уже названного."""
    _play()
    name = (await request.json()).get("name")
    if name and _pc_name() == "Странник":
        _pc_set_name(name)
        _pc_save()
    return {"hero": _pc_name()}


@router.get("/api/play/debuglog")
def debug_log(download: int = 0, tail: int = 0):
    """Подробный лог текущей сессии (все записи + полные трейсбеки). tail=КБ — только хвост;
    download=1 — как файл-вложение. Для отладки из интерфейса."""
    from fastapi.responses import PlainTextResponse

    from aidnd.server.debuglog import read_log

    _play()
    txt = read_log(tail_bytes=(tail * 1024) if tail else None) or "(лог пуст)"
    headers = {"Content-Disposition": 'attachment; filename="play-debug.log"'} if download else {}
    return PlainTextResponse(txt, headers=headers)


@router.post("/api/play/debuglog/clear")
def debug_log_clear():
    """Очистить лог сессии (кнопка «очистить» в интерфейсе)."""
    from aidnd.server.debuglog import clear_log

    _play()
    clear_log()
    return {"ok": True}
