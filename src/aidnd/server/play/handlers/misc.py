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


@router.get("/api/play/schedule")
def npc_schedule(npc: str = ""):
    """Распорядок дня NPC (карточка Bombers' Notebook): где он в какую фазу — из predict().
    Виден лишь для ЗНАКОМОГО (talk); незнакомца читать нельзя (туман личности)."""
    from aidnd.server.play.engine.core import _S, _met
    from aidnd.server.play.engine.worldsim import forecast, predict
    people = _S.get("people") or {}
    p = people.get(npc)
    if p is None:
        return {"error": "нет такого"}
    if npc not in _met():
        return {"error": "ты его не знаешь — заговори сперва"}
    RU = {"home": "дома", "work": "за работой", "tavern": "в трактире", "temple": "в храме",
          "market": "на рынке", "street": "на улице", "patrol": "в дозоре",
          "prowl": "на промысле", "appointment": "по уговору", "follow": "с тобой", None: "?"}
    fc = forecast(npc)
    return {"npc": npc, "name": p.name, "role": p.role,
            "day": {ph: RU.get(k, k) for ph, k in fc.items()},
            "now": RU.get(predict(npc)["kind"], "?")}


@router.get("/api/play/economy")
def economy_board():
    """Приборка экономики (стенд/наблюдаемость): именованные цепочки — товар/цена/запас/
    производители/дефицит + монета города M."""
    _play()
    from aidnd.server.play.engine.economy import chains_view, money_supply
    return {"money": money_supply(), "chains": chains_view()}


@router.get("/api/play/deeds")
def deeds_list(limit: int = 12):
    """Хроника мира: последние ДЕЛА (журнал deeds) — сырьё для UI-хроники и дебага."""
    _play()
    from aidnd.server.play.engine.core import _store, _wid
    return {"deeds": _store().deeds(_wid(), limit=min(int(limit), 50))}
