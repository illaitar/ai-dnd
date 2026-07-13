"""Free-form input domain (/act) — world.py split. Arbiter: intent→possibility/difficulty→outcome (LLM).

Key functions
-------------
_attempt(intent: dict, sc: dict) -> dict : Core resolver for any player action—gates, rolls, transfers, memory.
_run_plan(steps: list, sc: dict, text: str) -> dict : Chain executor; halts on fail, dialog, combat, or salient event.
act(request: Request) -> dict : POST /api/play/act endpoint; parse free-form text to intent and execute."""

from __future__ import annotations

import random
import re

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
from aidnd.server.play.engine.resolve import _dm_snapshot, _voice, resolve
from aidnd.server.play.engine.world import (
    _apply_routine,
    _play,
    _scene_dict,
    _world_tick,
)
from aidnd.server.play.mechanics.combat import _combatant_from_npc, _pc_combatant
from aidnd.server.play.mechanics.contracts import _contract_on_give, _sift_maybe_close
from aidnd.server.play.mechanics.items import (
    _apply_consumable,
    _do_craft,
    _materialize_npc,
    _pc_coins,
)

_DISRUPTIVE_RE = re.compile(
    # a loud/visible player act the whole room notices (→ salient); NOT ordinary speech
    r"кричу|ору\b|заор|во весь голос|громко (говорю|спрашива|зов|крич)|рычу|выхватыва|обнажа"
    r"|хвата\w* за (нож|меч|оруж|клинок|груд)|достаю (нож|меч|клинок|оруж)|швыр"
    r"|броса\w* (кружк|в стену|об пол|об стол)|опрокид|бью кулак|стуч\w* по стол|разбива"
    r"|угрожа|за грудки",
    re.IGNORECASE,
)


def _say_aloud(text: str, sc: dict) -> dict:
    """Player speaks with no specific target: the room hears it (pc_said/pc_spoke feed the world
    tick — see _world_tick), a loud/visible line marks the scene salient, and the DM narrates the
    world's reaction grounded in the live scene snapshot (never invented). Shared by /act's
    non-verb fallback and /api/play/say when the player addresses no one in particular."""
    out: dict = {"narr": []}
    if not text:
        out["narr"].append("Ничего не происходит.")
        return out
    lv = _S.get("live")
    if lv is not None:
        lv["pc_said"] = text
        lv["pc_spoke"] = True
        if _DISRUPTIVE_RE.search(text):
            # a loud/visible act: the whole room notices and reacts in character
            lv["salient"] = f"чужак: {text[:70]}"
    mgr = _model()  # non-action: DM response BASED ON FACTS of live scene (snapshot, not invention)
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
    return out


def _attempt(intent: dict, sc: dict) -> dict:
    """Single resolver for all player actions: gates, rolls, transfers, memory, consequences.
    Returns {narr:[strings], open_talk?, refresh?}."""
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
        if zid in zn:                                # zone matched by LLM-intent, not tokens
            out["narr"].append(_zone_go(zid, zn[zid]))
            out["refresh"] = True
            return out
        out["narr"].append("Такого места в этом помещении нет.")
        out["fail"] = True
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
            out["goto"] = tgt["node"]  # front will execute normal move (with walking)
        else:
            out["narr"].append("Ты не знаешь, где это. Спроси у людей.")
            out["fail"] = True
        return out

    if verb == "take" and intent.get("container"):
        return {"loot": intent["container"], "narr": [], "refresh": True}

    if verb == "take" and intent.get("item"):
        iid = str(intent["item"])
        lv = _S.get("live") or {}
        pl = (lv.get("zone_names") or {}).get(_S.get("zone")) or lv.get("ent", "у входа")
        if iid in (lv.get("zone_fixed", {}).get(pl) or {}).values():
            out["narr"].append("Не унести — вещь прибита к месту или слишком громоздка.")
            out["fail"] = True
            return out
        imap = lv.get("zone_items", {}).get(pl) or {}
        if iid in imap.values():
            it = _store().get_item(iid) or {}
            nm = it.get("name", "вещь")
            wrk = next((wp for wp in (lv.get("workers") or {}) if wp in people), None)
            caught = False
            if wrk and manner == "stealthily":       # stealthily with owner present — dexterity against eyes
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
        if manner == "forcefully":  # take by force: strength against bravery
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
            out["fail"] = True
            out["refresh"] = True
            return out
        # stealthily (default for take+npc): pickpocketing — same gate as the old button
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
            out["fail"] = True
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

    if verb == "say" and npc and isinstance(intent.get("deal"), dict):
        from aidnd.server.play.mechanics.deals import deal_attempt

        r = deal_attempt(npc, intent["deal"], manner, out, people, crof, loc)
        if r is not None:                            # not a deal (no stake) — ordinary dialogue
            return r

    if verb == "say" and npc and manner == "persuasively":
        out["open_talk"] = npc  # persuasion — this is dialogue; the key is asked for there
        out["say_first"] = detail or None
        return out

    if verb == "give" and npc and intent.get("coins"):
        amount = int(intent["coins"])
        have = _store().purse_get(_wid(), "pc")
        if amount <= 0:
            out["narr"].append("Сколько монет отдать?")
            out["fail"] = True
            return out
        if have < amount:
            out["narr"].append(f"У тебя всего {have} зм — столько не отсчитать.")
            out["fail"] = True
            return out
        p = people[npc]
        _store().purse_add(_wid(), "pc", -amount)
        npc_total = _store().purse_add(_wid(), npc, amount)
        rel = p.state.rel(PLAYER)
        rel["affinity"] = min(
            1.0,
            rel["affinity"]
            + min(PB["gift_aff_cap"], PB["gift_aff_base"] + amount / PB["gift_aff_div"]),
        )
        p.state.memory.add(f"игрок дал мне {amount} зм", _mt(), 0.55, about=[PLAYER])
        _pc_remember(f"дал {p.name} {amount} зм", 0.4, about=[npc])
        _npc_save(npc)
        _gt_add(PB["give_min"])
        from aidnd.server.play.engine.journal import j_event

        j_event("gave", f"отдал {p.name} {amount} зм (у {p.name}: {npc_total})")
        done = _sift_maybe_close()  # a coin gift may satisfy a wealth predicate → close on the spot
        out["narr"].append(
            f"Ты отсчитываешь {amount} монет и вкладываешь в ладонь {p.name}."
            + (f" {done}" if done else "")
        )
        out["refresh"] = True
        return out

    if verb == "give" and npc and intent.get("item"):
        iid = intent["item"]
        it = _store().get_item(iid)
        if not it or not any(r["item_id"] == iid for r in _store().inventory(_wid(), "pc")):
            out["narr"].append("У тебя нет этой вещи.")
            out["fail"] = True
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
            out["fail"] = True
            return out
        _gt_add(PB["give_min"])
        if it["kind"] == "consumable" or not it.get("durability"):
            fx = _apply_consumable(it)              # heal / mana from attrs (banded, code-owned)
            _store().inv_move(_wid(), iid, "used")  # drunk/consumed — item is gone
            tail = (" — " + ", ".join(fx)) if fx else ""
            out["narr"].append(f"«{it['name']}» — израсходовано{tail}.")
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

    if verb == "listen":
        lv = _S.get("live") or {}
        zones_l = lv.get("zones") or []
        zn = {z["id"]: z for z in zones_l}
        zid = str(intent.get("zone") or "")
        if zid not in zn:                            # no target — nearest other conversation
            my = (lv.get("zonemap") or {}).get(PLAYER)
            c = next((c for c in (lv.get("convs") or []) if c.get("zone") != my), None)
            zid = c.get("zone") if c else None
        if not zid or zid not in zn:
            out["narr"].append("Прислушиваться не к кому — рядом никто не шепчется.")
            out["fail"] = True
            return out
        z = zn[zid]
        n = int(_store().flag_get(_wid(), "listen") or 0) + 1
        _store().flag_set(_wid(), "listen", str(n))
        roll = random.Random(f"listen|{n}").randint(1, 20)
        mod = _PC_CAP.mod("wis")
        dc = round(PB["listen_dc_base"] + float(z.get("noise", 0.4)) * PB["listen_noise_k"])
        _gt_add(PB["step_min"])
        if roll + mod >= dc:
            _S["eaves"] = {"place": (lv.get("zone_names") or {}).get(zid, z["name"]),
                           "until": (lv.get("clock") or 0) + PB["listen_ticks"]}
            out["narr"].append(f"Восприятие: {roll}+{mod} против {dc} — ты замираешь словно "
                               f"невзначай, и слова от «{z['name']}» долетают ясно.")
        else:
            _S.pop("eaves", None)
            out["narr"].append(f"Восприятие: {roll}+{mod} против {dc} — гул зала глотает "
                               f"чужие слова.")
            out["fail"] = True
        return out

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
            out["fail"] = True
            return out
        if _pc_coins() < PB["rest_cost"]:
            out["narr"].append(f"Ночлег стоит {PB['rest_cost']} зм — а у тебя пусто.")
            out["fail"] = True
            return out
        now = _gt()
        if _phase(now) == "morning":                 # already morning — they don't sleep through the day
            out["narr"].append("Утро на дворе — какой сон? Разве что вздремнуть, да жалко дня.")
            out["fail"] = True
            return out
        _store().purse_add(_wid(), "pc", -PB["rest_cost"])
        wake = (now // 1440) * 1440 + PB["rest_until_h"] * 60
        if wake <= now:
            wake += 1440
        _S["gt"] = wake
        _mana_sleep((wake - now) / 60.0)  # sleep replenishes candle ×3
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
        _lv = _S.get("live")
        if _lv is not None:
            _lv["salient"] = f"чужак выхватил оружие на {p.name}!"
        out["combat"] = True
        out["narr"].append(f"Ты бросаешься на {p.name}. Назад дороги нет.")
        return out

    text = str(intent.get("_text") or detail or "")
    return _say_aloud(text, sc)


def _run_plan(steps: list, sc: dict, text: str) -> dict:
    """Chain executor: links in order, NO rollback. Breaks plan: link fails, contour change
    (talk/combat/loot/move) and SALIENT scene event (hall exploded — world intervened, pattern
    stopped/remaining of city route)."""
    import logging

    logging.getLogger("aidnd.scene").debug(
        "план игрока: %s ← «%s»",
        " → ".join(str(st.get("verb")) for st in steps[:PB["plan_cap"]]), text[:80])
    res: dict = {"narr": [], "refresh": False}
    steps = steps[:PB["plan_cap"]]
    sal0 = bool((_S.get("live") or {}).get("salient"))

    def _cut(i, why):
        if i + 1 < len(steps):
            res["stopped"] = True
            res["remaining"] = " → ".join(str(st.get("verb")) for st in steps[i + 1:])
            res["narr"].append(why)

    for i, step in enumerate(steps):
        step["_text"] = text
        if (len(steps) > 1 and step.get("verb") in ("take", "give", "use", "inspect")
                and not any(step.get(k) for k in ("item", "container", "npc"))):
            res["narr"].append("Этого нет под рукой — план обрывается.")
            break                                     # in the chain narrator does NOT gift non-existent things
        r = _attempt(step, sc)
        narr, refresh = res["narr"] + (r.get("narr") or []), res["refresh"] or bool(
            r.get("refresh"))
        res.update(r)
        res["narr"], res["refresh"] = narr, refresh
        if not sal0 and (_S.get("live") or {}).get("salient"):
            _cut(i, "Зал взрывается — не до задуманного: план обрывается.")
            break                                     # world intervened — like events on the road
        if r.get("fail"):
            _cut(i, "Задуманное дальше не идёт — план оборвался здесь.")
            break
        if any(k in r for k in ("open_talk", "goto", "combat", "loot", "inspect", "map_open")):
            break
    return res


@router.post("/api/play/act")
async def act(request: Request):
    """Free-form action: text → LLM-intent → single resolver. No verb buttons."""
    city, people, crof, cr2b, loc = _play()
    text = str((await request.json()).get("text") or "").strip()
    if not text:
        return {"narr": []}
    sc = _scene_dict(city, people, crof, cr2b, loc)
    it = resolve(text, sc)
    if it is None:
        return {"narr": ["(мир задумался и не понял — попробуй иначе)"], "gt": _gt()}
    res = _run_plan(it.get("plan") or [it], sc, text)
    _pc_remember(f"я: {text[:80]}", 0.2)
    t = _world_tick() if not res.get("combat") else {"feed": [], "address": []}
    return {**res, **t, "gt": _gt(), "coins": _pc_coins(), "hp": _pc_hp()}
