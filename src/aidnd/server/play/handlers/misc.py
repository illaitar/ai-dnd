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


@router.get("/api/play/market")
def market_board():
    """Товарный прилавок ЗДЕСЬ (B2): цепочки, чей venue = здание игрока, — товар/цена/запас/
    сколько у игрока в котомке. Пусто, если игрок не внутри торгового venue."""
    _play()
    from aidnd.server.play.engine.core import _S, _store, _wid
    from aidnd.server.play.engine.economy import ensure, market_here
    ensure()
    bid = _S.get("inside")
    return {"goods": market_here(bid), "coins": _store().purse_get(_wid(), "pc"),
            "inside": bool(bid)}


@router.post("/api/play/market/buy")
async def market_buy(request: Request):
    """Купить товар цепочки по живой цене: запас−, цена↑, монета pc→производителям (M+)."""
    _play()
    from aidnd.server.play.engine.core import _S, _gt, _gt_add
    from aidnd.server.play.engine.economy import player_buy
    b = await request.json()
    r = player_buy(_S.get("inside"), b.get("key"), int(b.get("qty", 1)))
    if "error" not in r:
        _gt_add(5)
    return {**r, "gt": _gt()}


@router.post("/api/play/market/sell")
async def market_sell(request: Request):
    """Сбыть товар из котомки в цепочку: запас+, цена↓, монета производителей→pc (M−)."""
    _play()
    from aidnd.server.play.engine.core import _S, _gt, _gt_add
    from aidnd.server.play.engine.economy import player_sell
    b = await request.json()
    r = player_sell(_S.get("inside"), b.get("key"), int(b.get("qty", 1)))
    if "error" not in r:
        _gt_add(5)
    return {**r, "gt": _gt()}


@router.get("/api/play/deeds")
def deeds_list(limit: int = 12):
    """Хроника мира: последние ДЕЛА (журнал deeds) — сырьё для UI-хроники и дебага."""
    _play()
    from aidnd.server.play.engine.core import _store, _wid
    return {"deeds": _store().deeds(_wid(), limit=min(int(limit), 50))}
