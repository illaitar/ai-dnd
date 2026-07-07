"""Домен ТОРГ (/offer /sell /wares /buy /askkey) — распил world.py. Цена глазом NPC, торг, аренда ключа.

Key functions
-------------
askkey(request) -> dict : Request an NPC's key (gated by affinity/trust).
offer(request) -> dict : Get NPC's item price estimate (asymmetric knowledge).
sell(request) -> dict : Sell item to merchant and receive coins.
wares(npc) -> dict : List merchant's wares with prices from their viewpoint.
buy(request) -> dict : Purchase item from merchant if player has coins.
"""

from __future__ import annotations

from fastapi import Request

from aidnd.items import rarity_price
from aidnd.server.play.engine.core import (
    PB,
    PLAYER,
    _gt,
    _gt_add,
    _mt,
    _npc_save,
    _pc_remember,
    _spurns,
    _store,
    _wid,
    router,
)
from aidnd.server.play.engine.world import _play, _voice
from aidnd.server.play.mechanics.items import (
    _CRAFT,
    _item_card,
    _materialize_npc,
    _npc_cap,
    _npc_sees,
    _pc_coins,
)


def _merchant(people, npc):
    p = people.get(npc)
    return p if (p and (p.role in _CRAFT or p.role == "лавочник")) else None


@router.post("/api/play/askkey")
async def askkey(request: Request):
    """Попросить у NPC его ключ. Гейт механикой: симпатия+доверие против жадности/осторожности —
    хозяйка кассы чужаку ключ не отдаст (честно; путь добычи — кража/торг, срез 2)."""
    _city, people, _crof, _cr2b, _loc = _play()
    b = await request.json()
    npc = b.get("npc")
    if npc not in people:
        return {"error": "нет такого"}
    p = people[npc]
    if _spurns(p):
        return {"error": f"{p.name} не желает иметь с тобой дела"}
    _materialize_npc(npc, "visible")
    want = str(b.get("key") or "").strip()  # какой именно ключ просим (имя с чипа)
    keys = [
        (_store().get_item(r["item_id"]), r["item_id"]) for r in _store().inventory(_wid(), npc)
    ]
    keys = [
        (it, iid)
        for it, iid in keys
        if it and it["kind"] == "key" and (not want or it["name"] == want)
    ]
    if not keys:
        return {"error": f"у {p.name} нет такого ключа при себе"}
    rel = p.state.relationships.get(PLAYER, {"affinity": 0.0, "trust": 0.0, "fear": 0.0})
    tr = p.state.config.traits
    bar = (
        PB["askkey_base"]
        + PB["askkey_greed"] * tr.get("greed", 0.5)
        + PB["askkey_honesty"] * tr.get("honesty", 0.5)
    )
    if rel.get("affinity", 0) + rel.get("trust", 0) < bar:
        line = _voice(p, rel, "reply", "Одолжи мне свой ключ.")
        p.state.memory.add(
            "незнакомец просил у меня ключ — я не дал(а)", _mt(), 0.5, about=[PLAYER]
        )
        _npc_save(npc)
        return {"given": False, "line": line}
    it, iid = keys[0]
    _store().inv_move(_wid(), iid, "pc")
    p.state.memory.add(f"я доверил(а) игроку свой ключ «{it['name']}»", _mt(), 0.6, about=[PLAYER])
    _pc_remember(f"{p.name} доверил(а) мне ключ «{it['name']}»", 0.5, about=[npc])
    _npc_save(npc)
    return {
        "given": True,
        "item": _item_card(it, set()),
        "line": _voice(p, rel, "reply", "Спасибо, что доверяешь мне ключ."),
    }


@router.post("/api/play/offer")
async def offer(request: Request):
    """Предложить предмет торговцу: он оценивает СВОИМ глазом (асимметрия знания) и называет цену."""
    _city, people, _crof, _cr2b, _loc = _play()
    b = await request.json()
    npc, iid = b.get("npc"), b.get("item")
    p = _merchant(people, npc)
    if not p:
        return {"error": "он не торгует"}
    if _spurns(p):
        return {"error": f"{p.name} не желает иметь с тобой дела"}
    it = _store().get_item(iid)
    if not it or not any(r["item_id"] == iid for r in _store().inventory(_wid(), "pc")):
        return {"error": "у тебя нет этого"}
    _materialize_npc(npc, "pockets")
    seen = _npc_sees(it, _npc_cap(p), npc)
    rel = p.state.relationships.get(PLAYER, {"affinity": 0.0})
    greed = p.state.config.traits.get("greed", 0.5)
    price = max(
        0,
        round(
            rarity_price(seen["worth"], it.get("rarity", "common"))
            * (PB["sell_base"] + PB["sell_aff"] * rel.get("affinity", 0) + PB["sell_greed"] * greed)
        ),
    )
    price = min(price, _store().purse_get(_wid(), npc))
    line = _voice(
        p,
        rel,
        "reply",
        f"(Я предлагаю тебе купить у меня «{it['name']}». Ты осмотрел вещь и даёшь {price} зм — "
        f"назови эту цену вслух по-своему.)",
    )
    return {"price": price, "line": line, "sees_worth": seen["worth"], "gt": _gt()}


@router.post("/api/play/sell")
async def sell(request: Request):
    _city, people, _crof, _cr2b, _loc = _play()
    b = await request.json()
    npc, iid = b.get("npc"), b.get("item")
    p = _merchant(people, npc)
    it = _store().get_item(iid)
    if not p or not it or not any(r["item_id"] == iid for r in _store().inventory(_wid(), "pc")):
        return {"error": "сделки не будет"}
    if _spurns(p):
        return {"error": f"{p.name} не желает иметь с тобой дела"}

    _materialize_npc(npc, "pockets")
    seen = _npc_sees(it, _npc_cap(p), npc)
    rel = p.state.relationships.get(PLAYER, {"affinity": 0.0})
    greed = p.state.config.traits.get("greed", 0.5)
    price = max(
        0,
        round(
            rarity_price(seen["worth"], it.get("rarity", "common"))
            * (PB["sell_base"] + PB["sell_aff"] * rel.get("affinity", 0) + PB["sell_greed"] * greed)
        ),
    )
    price = min(price, _store().purse_get(_wid(), npc))
    _store().inv_move(_wid(), iid, npc)
    _store().purse_add(_wid(), npc, -price)
    coins = _store().purse_add(_wid(), "pc", price)
    _gt_add(PB["trade_min"])
    p.state.memory.add(
        f"купил(а) у игрока «{it['name']}» за {price} зм", _mt(), 0.4, about=[PLAYER]
    )
    _pc_remember(f"продал {p.name} «{it['name']}» за {price} зм", 0.4, about=[npc])
    _npc_save(npc)
    return {"sold": True, "price": price, "coins": coins, "gt": _gt()}


@router.get("/api/play/wares")
def wares(npc: str):
    """Что торговец продаст (его материализованный инвентарь, кроме ключей) + цены ЕГО глазом."""
    _city, people, _crof, _cr2b, _loc = _play()
    p = _merchant(people, npc)
    if not p:
        return {"error": "он не торгует"}
    if _spurns(p):
        return {"error": f"{p.name} не желает иметь с тобой дела"}
    _materialize_npc(npc, "visible")
    _materialize_npc(npc, "pockets")
    rel = p.state.relationships.get(PLAYER, {"affinity": 0.0})
    greed = p.state.config.traits.get("greed", 0.5)
    out = []
    for r in _store().inventory(_wid(), npc):
        it = _store().get_item(r["item_id"])
        if not it or it["kind"] in ("key", "valuable"):
            continue  # ключи и ЛИЧНОЕ ценное не продаются (то — красть)
        seen = _npc_sees(it, _npc_cap(p), npc)
        price = max(
            1,
            round(
                rarity_price(seen["worth"], it.get("rarity", "common"))
                * (
                    PB["buy_base"]
                    + PB["buy_greed"] * greed
                    + PB["buy_aff"] * rel.get("affinity", 0)
                )
            ),
        )
        out.append({**_item_card(it, set()), "price": price})
    return {"items": out, "coins": _pc_coins()}


@router.post("/api/play/buy")
async def buy(request: Request):
    _city, people, _crof, _cr2b, _loc = _play()
    b = await request.json()
    npc, iid = b.get("npc"), b.get("item")
    p = _merchant(people, npc)
    it = _store().get_item(iid)
    if not p or not it or not any(r["item_id"] == iid for r in _store().inventory(_wid(), npc)):
        return {"error": "у него этого нет"}
    if _spurns(p):
        return {"error": f"{p.name} не желает иметь с тобой дела"}

    rel = p.state.relationships.get(PLAYER, {"affinity": 0.0})
    greed = p.state.config.traits.get("greed", 0.5)
    seen = _npc_sees(it, _npc_cap(p), npc)
    price = max(
        1,
        round(
            rarity_price(seen["worth"], it.get("rarity", "common"))
            * (PB["buy_base"] + PB["buy_greed"] * greed + PB["buy_aff"] * rel.get("affinity", 0))
        ),
    )
    if _pc_coins() < price:
        return {"error": f"не хватает монет (нужно {price})"}
    _store().inv_move(_wid(), iid, "pc")
    coins = _store().purse_add(_wid(), "pc", -price)
    _store().purse_add(_wid(), npc, price)
    _gt_add(PB["trade_min"])
    p.state.memory.add(f"продал(а) игроку «{it['name']}» за {price} зм", _mt(), 0.4, about=[PLAYER])
    _pc_remember(f"купил у {p.name} «{it['name']}» за {price} зм", 0.4, about=[npc])
    _npc_save(npc)
    return {
        "bought": True,
        "item": _item_card(it, set()),
        "price": price,
        "coins": coins,
        "gt": _gt(),
    }
