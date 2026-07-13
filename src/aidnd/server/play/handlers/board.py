"""BOARD/GUILD/DELVE domain (/board /guild_redeem /board_take /delve /surrender /watch_flee) — split from world.py.

Key functions
-------------
board() -> dict : Returns guild board, lairs, job listings, and player status.
guild_redeem(request) -> dict : Pays guild fine to redeem a guild mark.
board_take(request) -> dict : Takes job from guild board; creates active contract.
delve(request) -> dict : Enters lair/dungeon and initiates combat encounter.
surrender(request) -> dict : Surrenders to watch; pays fine or serves jail time.
watch_flee(request) -> dict : Attempts Dex check to flee from guard pursuit.
"""

from __future__ import annotations

import random

from fastapi import Request

from aidnd.combat import Encounter
from aidnd.server.play.engine.core import (
    _PC_CAP,
    _S,
    PB,
    _binfo,
    _gt,
    _gt_add,
    _mt,
    _pc_hp,
    _pc_remember,
    _store,
    _wanted_add,
    _wanted_clear,
    _wid,
    router,
)
from aidnd.server.play.engine.world import (
    _accept_contract,
    _apply_routine,
    _play,
    _scene_dict,
    _watch_check,
)
from aidnd.server.play.mechanics.combat import (
    _combatant_from_npc,
    _guild_bid,
    _guild_board,
    _guild_gate,
    _guild_status,
    _lairs,
    _mint_badge,
    _pc_badge,
    _pc_combatant,
)
from aidnd.server.play.mechanics.items import _pc_coins


def _board_postings() -> list:
    """Public emergent (src:'sift') contracts sitting in board status — grievance/bounty postings
    surfaced by the director (pipeline._surface, PUBLIC_PATTERNS). Step-shape-safe: these contracts
    carry step/steps/flattened current-step fields, but the pitch/reward/giver are top-level."""
    out = []
    for ct in _store().contracts(_wid(), "board"):
        if ct.get("src") != "sift":
            continue
        out.append(
            {
                "id": ct["id"],
                "title": (ct.get("pitch") or "").strip()[:160],
                "reward": ct.get("reward"),
                "giver": ct.get("giver_name"),
            }
        )
    return out


@router.get("/api/play/board")
def board():
    _play()
    gb = _guild_bid()
    joined = None
    if not _pc_badge() and not _store().flag_get(_wid(), "guild_mark|pc"):
        _mint_badge(0)  # first call — accepted, here's Bronze
        joined = "Тебя приняли в гильдию. Вот жетон приключенца (Медь)."
    return {
        "guild": (_binfo(gb)["name"] if gb else None),
        "jobs": _guild_board(),
        "lairs": _lairs(),
        "postings": _board_postings(),
        "status": _guild_status(),
        "joined": joined,
    }


@router.post("/api/play/guild_redeem")
async def guild_redeem(request: Request):
    """Redeem black guild mark with a fine (and get Bronze badge back if missing)."""
    _play()
    if not _store().flag_get(_wid(), "guild_mark|pc"):
        return {"error": "метки нет"}
    fine = PB["guild_mark_fine"]
    if _pc_coins() < fine:
        return {"error": f"нужно {fine} зм, чтобы загладить вину"}
    _store().purse_add(_wid(), "pc", -fine)
    _store().purse_add(_wid(), "guild", fine)
    _store().flag_set(_wid(), "guild_mark|pc", "")  # remove mark
    if not _pc_badge():
        _mint_badge(0)
    _pc_remember("загладил вину перед гильдией штрафом", 0.4)
    return {
        "redeemed": True,
        "coins": _pc_coins(),
        "status": _guild_status(),
        "narr": [f"Ты платишь гильдии {fine} зм. Метку снимают, жетон (Медь) снова у тебя."],
    }


@router.post("/api/play/board_take")
async def board_take(request: Request):
    _play()
    jid = (await request.json()).get("id")
    posting = next(
        (c for c in _store().contracts(_wid(), "board") if c["id"] == jid and c.get("src") == "sift"),
        None,
    )
    if posting:
        note = _accept_contract(jid, posting)
        return {"taken": True, "note": note}
    job = next((j for j in _guild_board() if j["id"] == jid), None)
    if not job:
        return {"error": "этого заказа уже нет"}
    gate = _guild_gate(job["cr"])  # badge · rank by rank · lie check
    if gate and gate.get("error"):
        return {"error": gate["error"], "dice": gate.get("dice"), "status": _guild_status()}
    gb = _guild_bid()
    _store().save_contract(
        _wid(),
        jid,
        "active",
        {
            "giver": "guild",
            "giver_name": _binfo(gb)["name"] if gb else "Гильдия",
            "kind": "clear",
            "want": None,
            "where": job["name"],
            "target": job["lair"],
            "target_name": job["name"],
            "reward": job["reward"],
            "reward_item": None,
            "reward_name": None,
            "pitch": "",
            "why": "доска гильдии",
        },
    )
    _pc_remember(
        f"взял с доски гильдии заказ: {job['name']} (CR {job['cr']}) за {job['reward']} зм", 0.5
    )
    if job.get("incident") and job.get("bid"):         # F5 — taking the job reveals its building
        from aidnd.server.play.engine.pc.hero import _mark_seen

        _mark_seen(job["bid"], prov="told",
                   text=f"взялся за дело: {job['name']} — знаю, где искать")
    stolen = bool(gate and gate.get("ok_stolen"))  # passed with someone else's badge — credit doesn't count
    return {
        "taken": True,
        "dice": (gate.get("dice") if gate else None),
        "narr": (["Распорядитель косится на жетон, но пропускает."] if stolen else []),
    }


@router.post("/api/play/delve")
async def delve(request: Request):
    """Go to lair and enter combat (travel time is real)."""
    _play()
    lid = (await request.json()).get("lair")
    if str(lid).startswith("inc|"):                   # city incident — own entry
        from aidnd.server.play.engine.incidents import incidents_active
        from aidnd.server.play.handlers.dungeon import incident_delve

        inc = next((x for x in incidents_active() if x["id"] == lid), None)
        if not inc:
            return {"error": "там уже разобрались"}
        if _pc_hp() <= 1:
            return {"error": "ты еле стоишь — сперва отлежись"}
        return incident_delve(inc)
    l = next((x for x in _lairs() if x["id"] == lid), None)
    if not l:
        return {"error": "нет такого места"}
    if l["cleared"]:
        return {"error": "там уже пусто — зачищено"}
    if _pc_hp() <= 1:
        return {"error": "ты еле стоишь — сперва отлежись"}
    taken = any(c.get("target") == lid for c in _store().contracts(_wid(), "active"))
    if not taken:  # not on contract — guild gates on site
        gate = _guild_gate(l["cr"])
        if gate and gate.get("error"):
            return {"error": gate["error"], "dice": gate.get("dice")}
    from aidnd.server.play.handlers.dungeon import delve_enter

    return delve_enter(l)  # lair = REAL dungeon (docs/dungeons.md, stage C)


@router.post("/api/play/surrender")
async def surrender(request: Request):
    """Surrender to watch: pay fine (wanted×rate) → clear; can't pay — night in cold + all coins."""
    city, people, crof, cr2b, loc = _play()
    wc = _watch_check(people, crof, loc)
    if not wc:
        return {"error": "стражи рядом нет"}
    fine = wc["fine"]
    if _pc_coins() >= fine:
        _store().purse_add(_wid(), "pc", -fine)
        narr = [f"Ты платишь виру — {fine} зм. «Гляди у меня», — цедит {wc['name']}, и отпускает."]
    else:
        got = _pc_coins()
        _store().purse_add(_wid(), "pc", -got)
        cur = _gt()
        target = ((cur // 1440) + 1) * 1440 + PB["watch_jail_h"] * 60  # until next morning
        _gt_add(max(PB["step_min"], target - cur))
        narr = [f"Платить нечем. Ночь в холодной, из кошеля выгребают {got} зм. Утром выпускают."]
    _wanted_clear()
    _pc_remember("рассчитался со стражей за свои дела", 0.5)
    _apply_routine()
    return {
        **_scene_dict(city, people, crof, cr2b, loc),
        "narr": narr,
        "coins": _pc_coins(),
        "gt": _gt(),
    }


@router.post("/api/play/watch_flee")
async def watch_flee(request: Request):
    """Flee from watch: Dex vs guard's dexterity. Escaped — wanted ↑, you're across town;
    caught — guard engages (combat)."""
    city, people, crof, cr2b, loc = _play()
    wc = _watch_check(people, crof, loc)
    if not wc:
        return {"error": "не от кого бежать"}
    guard = people[wc["guard"]]
    gdex = (guard.state.config.abilities.get("dex", 10) - 10) // 2
    roll = random.Random(f"wflee|{loc}|{_gt()}").randint(1, 20)
    total, dc = roll + _PC_CAP.mod("dex"), PB["watch_flee_dc"] + gdex
    dice = {
        "die": 20,
        "roll": roll,
        "mod": _PC_CAP.mod("dex"),
        "total": total,
        "dc": dc,
        "ok": total >= dc,
        "label": "Побег (Dex) от стражи",
    }
    if total >= dc:
        _wanted_add(1, "сбежал от стражи")  # pursuit intensifies
        nb = random.Random(f"wfleeto|{loc}|{_gt()}").choice(_S["kps"])
        _S["loc"], _S["inside"], _S["room"] = nb, None, None
        _gt_add(PB["step_min"] * 2)
        _apply_routine()
        return {
            **_scene_dict(city, people, crof, cr2b, nb),
            "dice": dice,
            "narr": ["Ты ныряешь в переулки и отрываешься. Но теперь ищут ещё усерднее."],
            "gt": _gt(),
            "coins": _pc_coins(),
        }
    foe = _combatant_from_npc(wc["guard"], guard)
    foe.side = "foes"
    enc = Encounter([_pc_combatant()], [foe], seed=f"watchfight|{wc['guard']}|{_mt()}", w=9, h=7)
    _S["combat"] = {
        "enc": enc,
        "npc": wc["guard"],
        "loc": loc,
        "head": {"name": f"Стража: {guard.name}", "sub": "бегство сорвалось"},
    }
    return {
        "dice": dice,
        "combat": True,
        "narr": [f"{guard.name} перехватывает тебя. Дерись или сдавайся."],
    }
