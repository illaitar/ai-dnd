"""Домен СВОБОДНЫЙ ВВОД (/act) — распил world.py. Арбитр: намерение→возможность/сложность→исход (LLM)."""

from __future__ import annotations

import json
import random

from fastapi import Request

from aidnd.combat import Encounter
from aidnd.items import use as item_use
from aidnd.server.play.engine.core import (
    _DM_SYS,
    _PC_CAP,
    _S,
    PB,
    PLAYER,
    _binfo,
    _gt,
    _gt_add,
    _mana_sleep,
    _model,
    _mt,
    _npc_save,
    _pc_hp,
    _pc_remember,
    _pc_save,
    _phase,
    _store,
    _wid,
    _witness_crime,
    router,
)
from aidnd.server.play.engine.world import (
    _INTENT_SYS,
    _apply_routine,
    _play,
    _scene_dict,
    _voice,
    _world_tick,
)
from aidnd.server.play.mechanics.combat import _combatant_from_npc, _pc_combatant
from aidnd.server.play.mechanics.contracts import _contract_on_give
from aidnd.server.play.mechanics.items import _do_craft, _materialize_npc, _pc_coins


def _intent(text: str, sc: dict) -> dict | None:
    """LLM-разбор фразы игрока. None — ТОЛЬКО «не понял фразу» (игроку честно так и скажем);
    недоступность модели летит исключением из mgr.call."""
    mgr = _model()
    here = "; ".join(f"{h['id']}={h['name']} ({h['role']})" for h in sc["here"]) or "никого"
    conts = (
        "; ".join(
            c["name"] + (" [заперто]" if c["locked"] else "") for c in sc["location"]["containers"]
        )
        or "нет"
    )
    bag = (
        "; ".join(
            f"{r['item_id']}={(_store().get_item(r['item_id']) or {}).get('name', '?')}"
            for r in _store().inventory(_wid(), "pc")
        )
        or "пусто"
    )
    keys_pl = ", ".join(k["label"] for k in _S["geom"]["keys"])
    from aidnd.server.play.engine.world import _scene_zones

    zones_line = "; ".join(f"{z['id']}={z['name']}" for z in _scene_zones()) or "нет"
    lv = _S.get("live") or {}
    pl = (lv.get("zone_names") or {}).get(_S.get("zone")) or lv.get("ent", "у входа")
    near = [f"{iid}={nm}" for nm, iid in (lv.get("zone_items", {}).get(pl) or {}).items()][:10]
    near += [f"{iid}={nm} [прибито]"
             for nm, iid in (lv.get("zone_fixed", {}).get(pl) or {}).items()][:4]
    user = (
        f"МЕСТО: {sc['location']['name']}. ЛЮДИ ЗДЕСЬ: {here}. ЁМКОСТИ: {conts}. "
        f"СУМКА ИГРОКА: {bag}. МЕСТА ГОРОДА: {keys_pl}. ЗОНЫ ПОМЕЩЕНИЯ: {zones_line}. "
        f"ПРЕДМЕТЫ РЯДОМ (твоя зона — {pl}): {'; '.join(near) or 'ничего приметного'}.\n"
        f"ФРАЗА ИГРОКА: «{text}»"
    )
    resp = mgr.call(
        "narrator",
        [{"role": "system", "content": _INTENT_SYS}, {"role": "user", "content": user}],
        options={"temperature": 0.2},
    )
    t = (resp.get("content") or "").strip()
    try:
        return json.loads(t[t.find("{") : t.rfind("}") + 1])
    except (json.JSONDecodeError, ValueError):
        return None


def _attempt(intent: dict, sc: dict) -> dict:
    """ОДИН резолвер на все действия игрока: гейты, броски, перенос, память, последствия.
    Возвращает {narr:[строки], open_talk?, refresh?}."""
    city, people, crof, cr2b, loc = _play()
    verb = intent.get("verb") or "wait"
    manner = intent.get("manner") or "openly"
    raw_npc = str(intent.get("npc") or "").strip()
    npc = (
        raw_npc
        if raw_npc in people
        else next((pid for pid, pp in people.items() if pp.name.lower() == raw_npc.lower()), None)
    )
    detail = str(intent.get("detail") or "")
    out: dict = {"narr": [], "refresh": False}

    if verb == "talk" and npc:
        out["open_talk"] = npc
        return out

    if verb == "move" and intent.get("zone"):
        from aidnd.server.play.engine.world import _scene_zones
        from aidnd.server.play.handlers.travel import _zone_go

        zn = {z["id"]: z["name"] for z in _scene_zones()}
        zid = str(intent["zone"])
        if zid in zn:                                # зону сматчил LLM-интент, не токены
            out["narr"].append(_zone_go(zid, zn[zid]))
            out["refresh"] = True
            return out
        out["narr"].append("Такого места в этом помещении нет.")
        return out

    if verb == "move" and intent.get("place"):
        want = str(intent["place"]).lower()
        tgt = next(
            (
                k
                for k in _S["geom"]["keys"]
                if k["label"].lower() in want or want in k["label"].lower()
            ),
            None,
        )
        if tgt:
            out["goto"] = tgt["node"]  # фронт выполнит обычный move (с ходьбой)
        else:
            out["narr"].append("Ты не знаешь, где это. Спроси у людей.")
        return out

    if verb == "take" and intent.get("container"):
        return {"loot": intent["container"], "narr": [], "refresh": True}

    if verb == "take" and intent.get("item"):
        iid = str(intent["item"])
        lv = _S.get("live") or {}
        pl = (lv.get("zone_names") or {}).get(_S.get("zone")) or lv.get("ent", "у входа")
        if iid in (lv.get("zone_fixed", {}).get(pl) or {}).values():
            out["narr"].append("Не унести — вещь прибита к месту или слишком громоздка.")
            return out
        imap = lv.get("zone_items", {}).get(pl) or {}
        if iid in imap.values():
            it = _store().get_item(iid) or {}
            nm = it.get("name", "вещь")
            wrk = next((wp for wp in (lv.get("workers") or {}) if wp in people), None)
            caught = False
            if wrk and manner == "stealthily":       # тайком при хозяине — ловкость против глаз
                n = int(_store().flag_get(_wid(), f"zsteal|{loc}") or 0) + 1
                _store().flag_set(_wid(), f"zsteal|{loc}", str(n))
                roll = random.Random(f"zsteal|{loc}|{n}").randint(1, 20)
                caught = roll + _PC_CAP.mod("dex") < PB["steal_dc_base"]
            _store().inv_move(_wid(), iid, "pc")
            imap.pop(nm, None)
            _gt_add(PB["act_min"])
            if wrk and (manner != "stealthily" or caught):
                wn = _witness_crime(people, crof, loc, wrk,
                                    f"взял «{nm}» — добро заведения!",
                                    weight=PB["crime_pickpocket"])
                out["narr"].append(f"Ты берёшь «{nm}». {people[wrk].name} это видит — "
                                   f"добро-то заведения. Свидетелей: {wn}.")
            else:
                out["narr"].append(f"«{nm}» тихо перекочёвывает в твою сумку.")
            _pc_remember(f"взял со стола «{nm}»", 0.3)
            out["refresh"] = True
            return out

    if verb == "take" and npc:
        p = people[npc]
        _materialize_npc(npc, "pockets")
        if manner == "forcefully":  # отнять силой: сила против храбрости
            n = int(_store().flag_get(_wid(), f"rob|{npc}") or 0) + 1
            _store().flag_set(_wid(), f"rob|{npc}", str(n))
            roll = random.Random(f"rob|{npc}|{n}").randint(1, 20)
            brav = p.state.config.traits.get("bravery", 0.5)
            _gt_add(PB["act_min"])
            if roll + _PC_CAP.mod("str") >= PB["rob_dc_base"] + round(brav * PB["rob_dc_brav"]):
                take = max(
                    1, _store().purse_get(_wid(), npc) * PB["rob_cut_num"] // PB["rob_cut_den"]
                )
                _store().purse_add(_wid(), npc, -take)
                _store().purse_add(_wid(), "pc", take)
                p.state.rel(PLAYER)["fear"] = max(p.state.rel(PLAYER)["fear"], 0.8)
                w = _witness_crime(
                    people, crof, loc, npc, "силой отнял у меня кошель", weight=PB["crime_rob"]
                )
                out["narr"].append(
                    f"Ты вытрясаешь из {p.name} {take} зм. Свидетелей: {w}. Город такое помнит."
                )
            else:
                w = _witness_crime(
                    people,
                    crof,
                    loc,
                    npc,
                    "пытался отнять моё силой",
                    weight=PB["crime_pickpocket"],
                )
                out["narr"].append(f"{p.name} вырывается и поднимает крик! Свидетелей: {w}.")
            out["refresh"] = True
            return out
        # stealthily (по умолчанию для take+npc): карманная кража — тот же гейт, что был кнопкой
        n = int(_store().flag_get(_wid(), f"steal|{npc}") or 0) + 1
        _store().flag_set(_wid(), f"steal|{npc}", str(n))
        lv = _S.get("live") or {}
        body = lv.get("world").bodies.get(npc) if lv.get("world") else None
        att = body.attention if body else 0.65
        roll = random.Random(f"steal|{npc}|{n}").randint(1, 20)
        _gt_add(PB["act_min"])
        if roll + _PC_CAP.mod("dex") < PB["steal_dc_base"] + round(att * PB["steal_dc_att"]):
            w = _witness_crime(
                people, crof, loc, npc, "лез мне в карман", weight=PB["crime_pickpocket"]
            )
            rel = p.state.relationships.get(PLAYER, {})
            out["narr"].append(f"Тебя ловят за руку! Свидетелей: {w}.")
            out["line"] = {
                "who": p.name,
                "npc": npc,
                "text": _voice(
                    p, rel, "reply", "(Ты поймал этого человека за руку в своём кармане!)"
                ),
            }
        else:
            rows = [
                (r["item_id"], _store().get_item(r["item_id"]))
                for r in _store().inventory(_wid(), npc)
            ]
            rows = [(i, it) for i, it in rows if it and it["kind"] != "key"]
            coins_np = _store().purse_get(_wid(), npc)
            if coins_np > 0 and (not rows or roll % 2 == 0):
                take = max(1, coins_np // PB["purse_cut"])
                _store().purse_add(_wid(), npc, -take)
                _store().purse_add(_wid(), "pc", take)
                _pc_remember(f"вытащил у {p.name} {take} зм", 0.6, about=[npc])
                out["narr"].append(f"Пальцы делают своё: +{take} зм тихо перетекают к тебе.")
            elif rows:
                iid, it = max(rows, key=lambda x: x[1]["worth"])
                _store().inv_move(_wid(), iid, "pc")
                _pc_remember(f"вытащил у {p.name} «{it['name']}»", 0.6, about=[npc])
                out["narr"].append(f"Ты незаметно вытягиваешь «{it['name']}».")
            else:
                out["narr"].append("В карманах пусто.")
        out["refresh"] = True
        return out

    if verb == "say" and npc and manner == "persuasively":
        out["open_talk"] = npc  # уговоры — это диалог; ключ просится там
        out["say_first"] = detail or None
        return out

    if verb == "give" and npc and intent.get("item"):
        iid = intent["item"]
        it = _store().get_item(iid)
        if not it or not any(r["item_id"] == iid for r in _store().inventory(_wid(), "pc")):
            out["narr"].append("У тебя нет этой вещи.")
            return out
        p = people[npc]
        _store().inv_move(_wid(), iid, npc)
        rel = p.state.rel(PLAYER)
        rel["affinity"] = min(
            1.0,
            rel["affinity"]
            + min(PB["gift_aff_cap"], PB["gift_aff_base"] + it["worth"] / PB["gift_aff_div"]),
        )
        p.state.memory.add(f"игрок подарил мне «{it['name']}»", _mt(), 0.55, about=[PLAYER])
        _pc_remember(f"подарил {p.name} «{it['name']}»", 0.4, about=[npc])
        _npc_save(npc)
        _gt_add(PB["give_min"])
        done = _contract_on_give(npc, it)
        out["narr"].append(f"«{it['name']}» переходит к {p.name}." + (f" {done}" if done else ""))
        out["refresh"] = True
        return out

    if verb == "use" and intent.get("item"):
        iid = intent["item"]
        it = _store().get_item(iid)
        if not it or not any(r["item_id"] == iid for r in _store().inventory(_wid(), "pc")):
            out["narr"].append("У тебя нет этой вещи.")
            return out
        _gt_add(PB["give_min"])
        if it["kind"] == "consumable" or not it.get("durability"):
            _store().inv_move(_wid(), iid, "used")  # выпито/израсходовано — вещь уходит
            out["narr"].append(f"«{it['name']}» — израсходовано.")
        else:
            ev = item_use(it, 1)
            _store().save_item(it)
            out["narr"].append(
                f"«{it['name']}» ломается." if ev["broke"] else f"«{it['name']}»: {ev['label']}."
            )
        out["refresh"] = True
        return out

    if verb == "inspect" and intent.get("item"):
        return {"inspect": intent["item"], "narr": [], "refresh": True}

    if verb == "map":
        out["map_open"] = True
        out["narr"].append("Ты разворачиваешь карту.")
        return out

    if verb == "craft":
        return _do_craft(str(intent.get("detail") or intent.get("_text") or ""), out)

    if verb == "rest":
        bid = cr2b.get(loc)
        data = ((_store().get_building(_wid(), bid) or {}).get("data")) if bid else {}
        if "lodging" not in ((data or {}).get("services") or []):
            out["narr"].append("Здесь не переночуешь — ищи место с ночлегом.")
            return out
        if _pc_coins() < PB["rest_cost"]:
            out["narr"].append(f"Ночлег стоит {PB['rest_cost']} зм — а у тебя пусто.")
            return out
        now = _gt()
        if _phase(now) == "morning":                 # уже утро — сутки напролёт не спят
            out["narr"].append("Утро на дворе — какой сон? Разве что вздремнуть, да жалко дня.")
            return out
        _store().purse_add(_wid(), "pc", -PB["rest_cost"])
        wake = (now // 1440) * 1440 + PB["rest_until_h"] * 60
        if wake <= now:
            wake += 1440
        _S["gt"] = wake
        _mana_sleep((wake - now) / 60.0)  # сон наполняет свечу ×3
        _apply_routine()
        _pc_hp(set_to=PB["pc_max_hp"])
        _pc_save()
        out["narr"].append(
            f"Ты снимаешь тюфяк за {PB['rest_cost']} зм и спишь до утра. Силы вернулись."
        )
        out["refresh"] = True
        return out

    if verb == "attack" and npc:
        p = people[npc]
        _materialize_npc(npc, "visible")
        foe = _combatant_from_npc(npc, p)
        foe.side = "foes"
        enc = Encounter([_pc_combatant()], [foe], seed=f"duel|{npc}|{_mt()}", w=9, h=7)
        _S["combat"] = {
            "enc": enc,
            "npc": npc,
            "loc": loc,
            "head": {
                "name": f"Стычка: {p.name}",
                "sub": _binfo(cr2b.get(loc))["name"] if cr2b.get(loc) else "улица",
            },
        }
        _witness_crime(
            people, crof, loc, npc, "бросился на меня с оружием", weight=PB["crime_assault"]
        )
        out["combat"] = True
        out["narr"].append(f"Ты бросаешься на {p.name}. Назад дороги нет.")
        return out

    mgr = _model()  # не-действие: отклик мастера ПО ФАКТАМ живой сцены (снимок, не выдумка)
    text = str(intent.get("_text") or detail or "")
    if text:
        from aidnd.server.play.engine.world import _dm_snapshot

        resp = mgr.call(
            "narrator",
            [
                {"role": "system", "content": _DM_SYS},
                {
                    "role": "user",
                    "content": f"{_dm_snapshot(sc)}\n\nИГРОК ЗАЯВЛЯЕТ: «{text}»",
                },
            ],
            options={"temperature": 0.5},
        )
        line = (resp.get("content") or "").strip()
        out["narr"].append(line or "Ничего не происходит.")
    else:
        out["narr"].append("Ничего не происходит.")
    return out


@router.post("/api/play/act")
async def act(request: Request):
    """Свободное действие: текст → LLM-интент → единый резолвер. Никаких кнопок-глаголов."""
    city, people, crof, cr2b, loc = _play()
    text = str((await request.json()).get("text") or "").strip()
    if not text:
        return {"narr": []}
    sc = _scene_dict(city, people, crof, cr2b, loc)
    it = _intent(text, sc)
    if it is None:
        return {"narr": ["(мир задумался и не понял — попробуй иначе)"], "gt": _gt()}
    it["_text"] = text
    res = _attempt(it, sc)
    _pc_remember(f"я: {text[:80]}", 0.2)
    t = _world_tick() if not res.get("combat") else {"feed": [], "address": []}
    return {**res, **t, "gt": _gt(), "coins": _pc_coins(), "hp": _pc_hp()}
