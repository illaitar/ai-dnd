"""Crime domain (/steal) — split from world.py. Dexterity vs victim attention; witnesses → investigation.

Key functions
-------------
steal(request: Request) -> dict : Pickpocket attempt against NPC; success steals coin/item,
    failure adds witnesses and wanted level.
"""

from __future__ import annotations

import random

from fastapi import Request

from aidnd.mind import World as MWorld
from aidnd.server.play.engine.core import (
    _PC_CAP,
    _S,
    PB,
    PLAYER,
    _gt,
    _gt_add,
    _here,
    _mt,
    _npc_save,
    _pc_remember,
    _store,
    _wanted_add,
    _wid,
    router,
)
from aidnd.server.play.engine.resolve import _voice
from aidnd.server.play.engine.world import _play
from aidnd.server.play.mechanics.items import _item_card, _materialize_npc, _pc_coins


@router.post("/api/play/steal")
async def steal(request: Request):
    """Pickpocket attempt: player dex vs victim attentiveness. Failure = caught + witnesses saw
    (memory+gossip will spread). Success silent — but it's a crime, recorded in the world."""
    _city, people, crof, _cr2b, loc = _play()
    npc = (await request.json()).get("npc")
    if npc not in people:
        return {"error": "нет такого"}
    p = people[npc]
    _materialize_npc(npc, "pockets")
    n = int(_store().flag_get(_wid(), f"steal|{npc}") or 0) + 1
    _store().flag_set(_wid(), f"steal|{npc}", str(n))
    lv = _S.get("live") or {}
    att = next((w.attention for w in [(lv.get("world") or MWorld()).bodies.get(npc)] if w), 0.65)
    roll = random.Random(f"steal|{npc}|{n}").randint(1, 20)
    dc = PB["steal_dc_base"] + round(att * PB["steal_dc_att"])
    _gt_add(PB["act_min"])
    if roll + _PC_CAP.mod("dex") < dc:  # CAUGHT
        rel = p.state.rel(PLAYER)
        rel["affinity"] = min(rel["affinity"], -0.5)
        rel["anchored"] = True                           # пойманная кража — обида жертвы (медленный спад)
        p.state.emotion["anger"] = min(1.0, p.state.emotion.get("anger", 0) + 0.7)
        p.state.emotion_target["anger"] = PLAYER
        p.state.memory.add(
            "поймал(а) игрока, когда тот лез мне в карман!", _mt(), 0.9, about=[PLAYER]
        )
        wit = [w for w in _here(loc, crof) if w != npc]
        for w in wit:
            people[w].state.memory.add(
                f"видел(а), как чужак лез в карман к {p.name}", _mt(), 0.6, about=[PLAYER, npc]
            )
            _npc_save(w)
        _pc_remember(f"попался на краже у {p.name} — при {len(wit)} свидетелях", 0.7, about=[npc])
        _npc_save(npc)
        _wanted_add(PB["crime_pickpocket"] + min(3, len(wit)), "попался на карманной краже")
        return {
            "caught": True,
            "witnesses": len(wit),
            "line": _voice(p, rel, "reply", "(Ты поймал этого человека за руку в своём кармане!)"),
            "gt": _gt(),
        }
    loot_rows = [
        (r["item_id"], _store().get_item(r["item_id"])) for r in _store().inventory(_wid(), npc)
    ]
    loot_rows = [(iid, it) for iid, it in loot_rows if it and it["kind"] != "key"]
    coins_np = _store().purse_get(_wid(), npc)
    if coins_np > 0 and (not loot_rows or roll % 2 == 0):  # take wallet or item
        take = max(1, coins_np // PB["purse_cut"])
        _store().purse_add(_wid(), npc, -take)
        coins = _store().purse_add(_wid(), "pc", take)
        _pc_remember(f"вытащил у {p.name} {take} зм", 0.6, about=[npc])
        return {"caught": False, "coins_taken": take, "coins": coins, "gt": _gt()}
    if not loot_rows:
        return {"caught": False, "nothing": True, "gt": _gt()}
    iid, it = max(loot_rows, key=lambda x: x[1]["worth"])
    _store().inv_move(_wid(), iid, "pc")
    _pc_remember(f"вытащил у {p.name} «{it['name']}»", 0.6, about=[npc])
    return {"caught": False, "item": _item_card(it, set()), "coins": _pc_coins(), "gt": _gt()}
