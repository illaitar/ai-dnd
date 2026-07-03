"""Игровой контур — МИР И ОРКЕСТРАЦИЯ: генерация, сцена, движение, диалог, действие, живая локация + HTTP-эндпоинты.

Авто-разбит из routes_play.py (ТД3). Слои: core<items<contracts<combat<main.
"""


from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import contextvars

from fastapi import APIRouter, Depends, HTTPException, Request

from ... import config
from ...citygraph import CityParams, generate, visual
from ...combat import (Encounter, dungeon, from_monster, from_npc, from_pc, lair_name,
                      pick_encounter, resolve, roll_dice)
from ...magic import build_spec, circle_hash, classify, known_ids, load as magic_load
from ...citygraph.model import NodeKind
from ...items import Capability, ItemCtx, LLMSmith, StubSmith, craft_path, loot_pool, rarity_price
from ...items.craft import ROLE_RECIPES, materials_graph
from ...items import condition as item_condition
from ...items import normalize as item_normalize
from ...items import craft as item_craft
from ...items import inspect as item_inspect
from ...items import repair as item_repair
from ...items import use as item_use
from ...items import view as item_view
from ...mind import Body, NpcConfig, NpcState
from ...mind import Item as MItem
from ...mind import World as MWorld
from ...mind import perceive as mind_perceive
from ...mind import think
from ...mind import StubPlanner, advance_agendas
from ...mind.llm_agent import apply_actions, decide_hybrid, plan_agenda
from ...mind.tick import _decay_emotion, _decay_needs
from ...play import populate
from ...play.population import Townsperson
from ...worldgen import WorldStore

from .core import (PB, PLAYER, TEACHER_ROLES, _COLORS, _DM_SYS, _PHASE_RU, _PORT_DIR, _S, _binfo, _city_name, _display, _emo, _fat_add, _fatigue, _glyph_learn, _glyphs_known, _grimoire_get, _grimoire_list, _grimoire_put, _gt, _gt_add, _here, _in_room, _inscriber, _mana, _mana_cap, _mana_grow, _mana_spend, _mark_seen, _met, _model, _mt, _npc_save, _pc, _pc_cap_eff, _pc_hp, _pc_name, _pc_remember, _pc_save, _pc_set_name, _phase, _pool, _portrait_url, _role_at, _role_for_building, _seen, _spurns, _store, _tokens_ru, _topics_for, _wanted, _wanted_add, _wanted_clear, _wid, _witness_crime, router, _PC_CAP)
from .items import (_CRAFT, _cont_holder, _do_craft, _forge, _item_card, _known, _materialize_npc, _merchant_restock, _npc_cap, _npc_sees, _pc_coins, _pc_key_for, _seed_item_pool)
from .contracts import (_board_ads, _board_npc_fulfill, _board_publish, _contract_offer, _contract_on_give, _contract_on_move, _contract_on_talk, _ct_cur, _ct_steps, _step_desc)
from .combat import (_combat_wrapup, _combatant_from_npc, _guild_bid, _guild_board, _guild_gate, _guild_status, _lairs, _mint_badge, _npc_delves, _pc_badge, _pc_combatant)



def _routine_spot(pid: str, p, phase: str, day: int, keynode: dict, kps: list, taverns) -> int:
    """Где человек в эту фазу суток. Детерминировано на (человек, фаза, день) — мир меняется,
    пока игрока нет, но воспроизводимо. Питейных может быть несколько — каждый выбирает свою."""
    rng = random.Random(f"rout|{pid}|{phase}|{day}")
    tavern = rng.choice(taverns) if taverns else None       # своя питейная на вечер
    if p.role == "стражник" and kps:                        # СТРАЖА патрулирует город днём и вечером
        if phase in ("day", "evening"):
            return kps[(hash((pid, phase, day)) % len(kps))]   # обход перекрёстков (детерминир.)
        return keynode.get(p.work, p.home) if p.work else p.home
    if p.role in ("бродяга", "головорез"):                  # лихой люд: днём по углам, вечером к людям
        if phase in ("evening", "night") and tavern is not None and rng.random() < PB["eve_rogue"]:
            return tavern
        return rng.choice(kps) if kps else p.home
    if p.work:                                              # работник: пост днём, вечером трактир/дом
        wn = keynode.get(p.work, p.home)
        if phase in ("morning", "day"):
            return wn
        if phase == "evening":
            if p.role == "трактирщик":
                return wn                                   # трактирщик вечером на посту
            return tavern if (tavern is not None and rng.random() < PB["eve_worker"]) else p.home
        return p.home
    if phase == "morning":                                  # горожанин: большинство — дома
        return (rng.choice(kps) if kps and rng.random() < PB["morn_out"] else p.home)
    if phase == "day":
        return (rng.choice(kps) if kps and rng.random() < PB["day_out"] else p.home)
    if phase == "evening":
        return tavern if (tavern is not None and rng.random() < PB["eve_commoner"]) else p.home
    return p.home


def _apply_routine() -> None:
    """Пересчитать споты всех жителей при смене фазы суток (дёшево — ключ по фазе+дню)."""
    key = (_phase(), _gt() // 1440)
    if _S.get("routine_key") == key or not _S.get("people"):
        return
    _S["routine_key"] = key
    if key[0] == "morning":                                # утро: смелые идут по заказам доски
        if _wanted() > 0:                                  # розыск остывает со временем (память не вечна)
            _wanted_add(-PB["wanted_decay"])
        try:
            news = _npc_delves()
            if news:
                _S["guild_news"] = (_S.get("guild_news") or [])[-2:] + news
        except Exception:                                  # noqa: BLE001 — вылазка не роняет мир
            pass
        try:                                               # столб: горожане вешают и снимают объявления
            bn = _board_npc_fulfill() + _board_publish()
            if bn:
                _S["board_news"] = (_S.get("board_news") or [])[-3:] + bn
        except Exception:                                  # noqa: BLE001 — доска не роняет мир
            pass
        try:                                               # караван: случайный товар на рынок
            if random.Random(f"caravan|{_gt() // 1440}|{_wid()}").random() < PB["caravan_chance"]:
                _merchant_restock(f"caravan|{_gt() // 1440}")
        except Exception:                                  # noqa: BLE001
            pass
    people, crof = _S["people"], _S["crof"]
    keynode, kps = _S.get("keynode") or {}, _S.get("kps") or []
    taverns = [keynode.get(p.work) for p in people.values()      # питейных может быть несколько
               if p.role == "трактирщик" and p.work and keynode.get(p.work)]
    for pid, p in people.items():
        crof[pid] = _routine_spot(pid, p, key[0], key[1], keynode, kps, taverns)


_TIE_ROLES = {"головорез": "головорез", "шайк": "головорез", "стражн": "стражник",
              "лавочн": "лавочник", "куп": "лавочник", "трактир": "трактирщик", "жрец": "жрец",
              "знахар": "знахарка", "кузнец": "кузнец", "мельник": "мельник", "бард": "бард",
              "бродя": "бродяга", "сапожн": "сапожник", "дубильщ": "дубильщик", "стар": "жрец"}


def _weave_ties(people) -> None:
    """Связи персон («должен головорезам», «враждует со старостой») ПРИВЯЗЫВАЮТСЯ к реальным
    людям пула: обоюдные отношения в mind + память с настоящим именем. Граф «кто кого знает»
    становится настоящим; детерминировано, идемпотентно (по метке в памяти)."""
    rng = random.Random("ties|1")
    byrole: dict = {}
    for oid, o in sorted(people.items()):
        byrole.setdefault(o.role, []).append(oid)
    for pid, p in sorted(people.items()):
        st = p.state
        if any("— это про" in m.text for m in st.memory.items):
            continue                                       # уже вязан (в т.ч. восстановлен из npc_state)
        for tie in ((p.persona or {}).get("ties") or [])[:2]:
            tl = tie.lower()
            role = next((r for w, r in _TIE_ROLES.items() if w in tl), None)
            cands = [x for x in byrole.get(role, []) if x != pid]
            if not cands:
                continue
            oid = rng.choice(cands)
            o = people[oid]
            ar, br = st.rel(oid), o.state.rel(pid)
            hostile = any(w in tl for w in ("вражд", "подозр", "ненавид", "угрож", "презир"))
            debt = any(w in tl for w in ("должен", "долг", "задолж"))
            fear = any(w in tl for w in ("боит", "страш", "опаса"))
            if hostile:                                     # настоящая вражда — обоюдно негатив
                ar["fear"] = max(ar["fear"], 0.3)
                ar["affinity"] = min(ar["affinity"], -0.2)
                br["affinity"] = min(br["affinity"], -0.1)
            elif debt:                                      # долг — обязательство, НЕ ненависть
                ar["fear"] = max(ar["fear"], 0.2)           # должник слегка опасается кредитора
            elif fear:                                      # страх без вражды — симпатия нейтральна
                ar["fear"] = max(ar["fear"], 0.35)
            else:                                           # доброе знакомство/родство
                ar["affinity"] = max(ar["affinity"], 0.4)
                ar["trust"] = max(ar["trust"], 0.3)
                br["affinity"] = max(br["affinity"], 0.3)
            st.memory.add(f"{tie} — это про {o.name}", _mt(), 0.5, kind="fact", about=[oid])
            o.state.memory.add(f"{p.name}: {tie[:90]} — нас связывает", _mt(), 0.4, kind="fact", about=[pid])


def _person_from_row(row: dict, home: int, work: str | None) -> Townsperson:
    """Готовый NPC из банка → Townsperson с мозгом (mind) + богатой персоной/портретами."""
    mech = row.get("mech") or {}
    cfg = NpcConfig(id=row["id"], name=row["name"], role=row["role"],
                    traits=mech.get("traits") or {}, abilities=mech.get("abilities") or {})
    st = NpcState.from_config(cfg)
    r = random.Random(row["id"])                           # лёгкий фон нужд, детерминированно
    for n in st.needs:
        st.needs[n] = round(r.uniform(0.1, 0.35), 2)
    saved = _store().get_npc_state(_wid(), row["id"])  # прожитое переживает рестарт
    if saved:
        st.relationships = saved.get("relationships") or {}
        st.needs.update(saved.get("needs") or {})
        for m in saved.get("memory") or []:
            mm = st.memory.add(m["text"], m["t"], m.get("importance", 0.3),
                               kind=m.get("kind", "observation"), about=m.get("about") or [])
            mm.last_access = m.get("last_access", m["t"])
    tp = Townsperson(id=row["id"], name=row["name"], role=row["role"], home=home, work=work,
                     charisma=row["charisma"], appearance=row["appearance"], state=st,
                     persona=row.get("persona"), portraits=row.get("portraits") or {})
    if work:                                               # владелец здания → ключи от его закрытых ёмкостей
        tp.keys = _building_keys(work)
    return tp


def _building_keys(bid: str) -> list:
    """Ключи-открывашки от LOCKED-ёмкостей здания (для владельца)."""
    bd = _store().get_building(_wid(), bid)
    if not bd:
        return []
    return [{"name": c["key"]["name"], "opens": c["name"], "where": c.get("where", "")}
            for c in (bd["data"].get("containers") or [])
            if c.get("access") == "locked" and c.get("key")]


def _building_rooms(bid: str) -> list:
    """Суб-помещения здания (мини-граф): name/kind/access/hidden (скрытое видно лишь по зоркому осмотру)."""
    bd = _store().get_building(_wid(), bid)
    if not bd:
        return []
    return [{"name": s["name"], "kind": s.get("kind", "backroom"),
             "access": s.get("access", "public")} for s in (bd["data"].get("sub_rooms") or [])]


def _building_containers(bid: str, room: str | None = None) -> list:
    """Ёмкости ТЕКУЩЕГО помещения (без содержимого — вскрывается взаимодействием)."""
    bd = _store().get_building(_wid(), bid)
    if not bd:
        return []
    rooms = bd["data"].get("sub_rooms") or []
    return [{"name": c["name"], "kind": c["kind"], "where": c.get("where", ""),
             "locked": c.get("access") == "locked"}
            for c in (bd["data"].get("containers") or [])
            if _in_room(c.get("where", ""), room, rooms)]


def _assign_key_buildings(city) -> None:
    """Мир создан → раздать ключевым слотам здания ИЗ ПУЛА по типу-хинту слота (гильдия — гильдией).
    Пишется в live-БД мира один раз; повторный заход читает готовое."""
    store, pool = _store(), _pool()
    have = store.building_ids(_wid())
    todo = [bid for bid in city.key_buildings if bid not in have]
    if not todo:
        return
    from aidnd.worldgen.enrichment import _SIGNIFICANT
    rows = pool.pool_buildings("key")
    rng = random.Random(f"bassign|{_wid()}")
    rng.shuffle(rows)
    used = set()

    def take(hint):
        h = hint.split()[0].lower()                        # «Храм удачи» → храм
        for r in rows:                                     # сперва по типу, потом любой
            if r["id"] not in used and h in r["btype"].lower():
                used.add(r["id"]); return r
        for r in rows:
            if r["id"] not in used:
                used.add(r["id"]); return r
        return rows[0]

    for bid in sorted(todo):
        idx = int(bid.split(":")[1]) - 1
        hint = _SIGNIFICANT[idx % len(_SIGNIFICANT)]
        r = take(hint)
        kb = city.key_buildings[bid]
        store.save_building(_wid(), bid, True, kb.interior, r["data"].get("name"), r["data"])


_RES_POOL = None


def _res_binfo(bid: str) -> dict | None:
    """Жилой дом: фактшит детерминированно из пула (без записи в БД — функция от (мир, дом))."""
    global _RES_POOL
    if _RES_POOL is None:
        _RES_POOL = _pool().pool_buildings("res")
    if not _RES_POOL:
        return None
    return random.Random(f"res|{_wid()}|{bid}").choice(_RES_POOL)["data"]


def _fill_from_pool(city, keynode, kps):
    """Наполнить толпу из БАНКА (worldgen.people): ключевые здания по роли + горожане по домам +
    пара лихих. Привязки пишем в placements (персист) и восстанавливаем при повторном заходе.
    Пул пуст → вернём None (падаем на голое populate)."""
    store = _store()
    if _pool().people_count() == 0:
        return None
    people, spot = {}, {}
    placed = {pl["npc_id"]: pl for pl in store.placements_for(_wid())}
    if placed and not all(pl["node"] in city._xy and pl["home"] in city._xy   # noqa: SLF001
                          for pl in placed.values()):
        store.clear_placements(_wid())                 # граф города изменился — узлы протухли
        placed = {}                                        # пере-размещаем заново (память NPC цела)
    if placed:                                             # уже наполнен — восстановить тех же людей
        for pid, pl in placed.items():
            if store.flag_get(_wid(), f"dead|{pid}"):
                continue                                   # мёртвые не возвращаются
            row = _pool().get_person(pid)
            if row:
                people[pid] = _person_from_row(row, pl["home"], pl["work"])
                spot[pid] = pl["node"]
        if people:
            return people, spot
    rng = random.Random(f"settle|{_wid()}")
    rows = _pool().list_people(limit=100000)
    rng.shuffle(rows)
    houses = [h.node for h in city.houses.values()]
    rng.shuffle(houses)
    hi = iter(houses)
    by_role = {}
    for r in rows:
        by_role.setdefault(r["role"], []).append(r)
    used = set()

    def place(row, node, work, home):
        people[row["id"]] = _person_from_row(row, home, work)
        spot[row["id"]] = node
        store.place_person(_wid(), row["id"], node, home, work)
        used.add(row["id"])

    for bid, kb in sorted(city.key_buildings.items()):     # работники — по роли из типа здания
        want = _role_for_building(bid)
        cand = [r for r in by_role.get(want, []) if r["id"] not in used] or                [r for r in rows if r["id"] not in used]
        for row in cand[:2]:                               # хозяин + подмастерье
            place(row, kb.node, bid, home=next(hi, kb.node))
    for row in rows:                                       # ВЕСЬ остальной пул — по домам города
        if row["id"] not in used:
            h = next(hi, None) or rng.choice(houses)
            place(row, h, None, home=h)
    return people, spot


def _play():
    if _S["city"] is None:
        params = CityParams(seed=_S["seed"], key_buildings=12, river=True, walls=True, segment=16)
        city = generate(params)
        _assign_key_buildings(city)                        # мир юзера: здания из ПУЛА, без LLM
        _seed_item_pool()                                  # пул предметов мира (сид-набор, данные)
        vis = visual(params, interactive=True)             # богатый визуал + кликабельные дома
        xy = {n.id: (n.x, n.y) for n in city.nodes()}
        keynode = {bid: kb.node for bid, kb in city.key_buildings.items()}   # здание → БЛИЖАЙШАЯ точка (дверь)
        kps = city.key_points()
        drawn = _fill_from_pool(city, keynode, kps)
        if drawn:                                          # наполнение из банка
            people, spot = drawn
        else:                                              # фоллбэк: голое население (без персон/портретов)
            people = populate(city, seed=_S["seed"], commoners=16, deviants=2)
            rng = random.Random(f"spot|{_wid()}")
            spot = {pid: (keynode.get(p.work) or p.home or rng.choice(kps)) for pid, p in people.items()}
        n2b = {}                                           # узел-точка → здание (ключевые прежде домов)
        for bid, kb in city.key_buildings.items():
            n2b.setdefault(kb.node, bid)
        for hid, ho in city.houses.items():                # жилые дома тоже входимы (фактшит из пула)
            n2b.setdefault(ho.node, hid)
        start = next((keynode.get(p.work) for p in people.values()
                      if p.role == "трактирщик" and p.work), None) or kps[0]
        _weave_ties(people)                                # связи персон → реальные люди пула
        _S.update(city=city, people=people, crof=spot, cr2b=n2b, loc=start,
                  geom=_build_geom(city, xy, n2b, vis), keynode=keynode, kps=kps)
    _apply_routine()                                       # споты = f(время): распорядок дня
    return _S["city"], _S["people"], _S["crof"], _S["cr2b"], _S["loc"]


def _build_geom(city, xy, n2b, vis) -> dict:
    """Лёгкий интерактивный слой поверх богатого визуала: система координат — холст рендера 0 0 W H.
    Дома/улицы/река/стены рисует сам SVG (vis['inner']); клик по дому → его БЛИЖАЙШАЯ точка дороги
    (h2n = h.node, НЕ перекрёсток). Метки зданий подписываем поверх; _xy — узел→xy для маршрута."""
    h2n = {h.id: h.node for h in city.houses.values()}
    road = (NodeKind.CROSSROAD, NodeKind.POINT, NodeKind.BRIDGE, NodeKind.GATE)
    points = [{"id": n, "x": round(xy[n][0], 1), "y": round(xy[n][1], 1)}  # ВСЕ узлы дорог (не только перекрёстки)
              for n in xy if city.node_kind(n) in road]
    keys = []
    for bid, kb in sorted(city.key_buildings.items()):
        keys.append({"node": kb.node, "x": round(kb.x, 1), "y": round(kb.y, 1),
                     "label": _binfo(bid)["label"], "bid": bid})
    cx, cy = vis["W"] / 2, vis["H"] / 2                     # ДОСКА-СТОЛБ: перекрёсток ближе к центру
    cross = [n for n in xy if city.node_kind(n) == NodeKind.CROSSROAD]
    plaza = min(cross, key=lambda n: (xy[n][0] - cx) ** 2 + (xy[n][1] - cy) ** 2) if cross else None
    if plaza is not None:
        keys.append({"node": plaza, "x": round(xy[plaza][0], 1), "y": round(xy[plaza][1], 1),
                     "label": "Доска", "bid": "board:plaza"})
    return {"viewBox": [0, 0, vis["W"], vis["H"]], "svg": vis["inner"],
            "h2n": h2n, "points": points, "keys": keys, "plaza": plaza,
            "_xy": {n: [round(xy[n][0], 1), round(xy[n][1], 1)] for n in xy}}


def _look_key(loc, inside) -> str:
    return f"{loc}|{inside or 'out'}"


def _looked_level(loc, inside) -> int:
    """0 = не осматривался (туман: людей/ёмкостей не различаешь), 1 = осмотрелся, 2 = зоркий бросок."""
    return int((_S.setdefault("looked", {})).get(_look_key(loc, inside), 0))


def _scene_dict(city, people, crof, cr2b, loc):
    role = _role_at(loc, people, crof, cr2b)
    bid = cr2b.get(loc)
    inside = _S.get("inside")
    if inside and inside != bid:                           # отошёл от здания — значит, вышел
        inside = _S["inside"] = None
        _S["room"] = None
    _mark_seen(bid)                                        # пришёл — узнал место
    plaza = (_S.get("geom") or {}).get("plaza")
    if inside:
        info = _binfo(inside)
        name, kind = info["name"], info["kind"]
    elif bid:
        info = _binfo(bid)
        name, kind = f"у входа: {info['name']}", "снаружи"
    elif plaza is not None and loc == plaza:
        name, kind = "Городская доска", "площадь · объявления горожан"
    elif city.node_kind(loc) == NodeKind.CROSSROAD:
        name, kind = "Перекрёсток", "городская развилка"
    else:
        name, kind = "Улица", "мостовая меж домов"
    here = sorted(_here(loc, crof), key=lambda i: (people[i].work is None, i))
    lvl = _looked_level(loc, inside)
    more = max(0, len(here) - PB["here_show_cap"])
    here = here[:PB["here_show_cap"]]
    vis_here = here if lvl >= 1 else []                    # туман: людей различаешь, лишь осмотревшись
    room = _S.get("room") if inside else None
    rooms = []
    if inside:
        for r in _building_rooms(inside):                  # скрытые видны лишь по зоркому осмотру (lvl 2)
            if r["access"] == "hidden" and lvl < 2:
                continue
            rooms.append(r)
    if inside and room:
        name = f"{_binfo(inside)['name']} · {room}"
    d = {
        "loc": loc,
        "inside": inside,
        "room": room,
        "rooms": rooms,
        "enterable": ({"bid": bid, "name": _binfo(bid)["name"]} if (bid and not inside) else None),
        "looked": lvl,
        "here_more": (more if lvl >= 1 else 0),
        "location": {"name": name, "kind": kind,
                     "desc": ("Обычное место фронтирного городка — идёт своя жизнь." if role
                              else "Мимо спешат редкие прохожие; в лужах дрожит свет окон."),
                     "containers": (_building_containers(inside, room) if (inside and lvl >= 1) else [])},
        "ambient": {"time": _PHASE_RU[_phase()], "weather": "дождь",
                    "mood": "оживлённо" if len(here) > 2 else "тихо",
                    "event": ("Ты ещё не осмотрелся здесь." if lvl == 0 and here else
                              "Народ занят своими делами." if here else "Пусто; лишь ветер гуляет меж домов.")},
        "here": [{"id": pid,
                  "name": _display(pid, people),        # незнакомец — дескриптором, имя после знакомства
                  "role": (people[pid].role if (pid in _met() or people[pid].work)
                           else "кто-то из горожан"),
                  "init": _display(pid, people)[0].upper(), "color": _COLORS[i % len(_COLORS)],
                  "portrait": _portrait_url(people[pid], _emo(people[pid].state))}
                 for i, pid in enumerate(vis_here)],
    }
    if bid and bid == _guild_bid():                        # в гильдии — доска, ранг, приём новичка
        d.setdefault("narr", [])
        if not _pc_badge() and not _store().flag_get(_wid(), "guild_mark|pc"):
            _mint_badge(0)
            d["narr"].append("Тебя приняли в гильдию. Вот жетон приключенца (Медь).")
        d["guild_board"], d["guild_news"] = _guild_board(), (_S.get("guild_news") or [])
        d["guild_status"] = _guild_status()
    if plaza is not None and loc == plaza and not inside:  # у столба — объявления горожан
        d["board_ads"] = _board_ads()
        d["board_news"] = _S.get("board_news") or []
    wc = _watch_check(people, crof, loc)                   # стража при высоком розыске
    if wc:
        d["watch"] = wc
    return d


def _watch_check(people, crof, loc):
    """Стража вяжет: если розыск ≥ порога И на локации есть стражник — конфронтация."""
    if _wanted() < PB["wanted_confront"]:
        return None
    guard = next((pid for pid in _here(loc, crof) if people[pid].role == "стражник"), None)
    if not guard:
        return None
    crimes = (_store().flag_get(_wid(), "crimes|pc") or "тёмные дела").split("; ")
    return {"guard": guard, "name": people[guard].name, "wanted": _wanted(),
            "crimes": ", ".join(crimes[-2:]), "fine": _wanted() * PB["watch_fine_per_pt"]}


def _mind_scene(npc_id, people) -> MWorld:
    p = people[npc_id]
    w = MWorld()
    w.link("зал", "улица")
    w.add(Body(id=npc_id, place="зал", charisma=p.charisma, appearance=p.appearance))
    w.add(Body(id=PLAYER, place="зал", charisma=0.4, appearance=0.3))
    return w


_VOICE = {"gruff": "грубовато", "warm": "тепло", "clipped": "сухо и коротко",
          "florid": "витиевато", "meek": "робко", "booming": "громко, зычно"}
_STANCE = {"warm": "дружелюбно", "neutral": "нейтрально", "wary": "настороженно",
           "dour": "хмуро", "greedy": "с расчётом на выгоду", "hostile": "враждебно"}


def _voice(p, rel, kind, player_text=None) -> str:
    mgr = _model()
    if not mgr.available():
        return (f"{p.name} окидывает тебя оценивающим взглядом." if kind == "greet"
                else f"{p.name} неопределённо пожимает плечами.")
    per = getattr(p, "persona", None) or {}
    bits = [f"Ты — {p.name}, {p.role} на фронтире (тёмное фэнтези)."]
    if per:                                                # богатая персона из пула
        if per.get("origin"):
            bits.append(f"Родом: {per['origin']}.")
        if per.get("voice"):
            bits.append(f"Говоришь {_VOICE.get(per['voice'], 'обычно')}.")
        if per.get("speech"):
            bits.append("Речевые привычки: " + "; ".join(per["speech"][:2]) + ".")
        if per.get("quirk"):
            bits.append(f"Причуда: {per['quirk']}.")
        if per.get("wants"):
            bits.append("Стремишься: " + "; ".join(per["wants"][:2]) + ".")
        bits.append(f"К чужаку держишься {_STANCE.get(per.get('stance'), 'нейтрально')}.")
        if per.get("secret"):
            bits.append(f"У тебя есть тайна (НЕ выдавай без веской причины): {per['secret'].get('what', '')}.")
    if _spurns(p):                                         # обида/гнев ПЕРЕВЕШИВАЮТ радушие персоны
        bits.append("Ты ЗОЛ на этого человека (вспомни, почему) — никакого радушия: "
                    "холод, резкость или презрение, по твоему характеру.")
    bits.append("КАНОН: о людях и местах ЭТОГО города говори только то, что есть в памяти и справке — "
                "здешних имён и заведений не выдумывай. Вымысел допустим лишь о дальних краях и былом, "
                "и подавай его как слух.")
    lv = _S.get("live") or {}
    just = (lv.get("last") or {}).get(p.id)
    if just and just != "—":
        bits.append(f"Ты в «{lv.get('place', 'этом месте')}»; только что ты: {just}.")
    mems = p.state.memory.recall(player_text or "разговор с чужаком-игроком", now=_mt(), k=5)
    if mems:                                               # непрерывность: NPC помнит вас и прошлое
        bits.append("ТЫ ПОМНИШЬ: " + "; ".join(m.text for m in mems) + ".")
    if player_text:                                        # вопрос о мире → справка сразу (не выдумывать)
        info = _world_lookup(player_text, _S.get("loc"))
        if "не скажу" not in info:
            bits.append(f"СПРАВКА МИРА (это истина — придерживайся её, имена и места не выдумывай): {info}.")
    bits.append(f"Симпатия к собеседнику {rel.get('affinity', 0):.2f} (низкая — суше/настороже, высокая — теплее). "
                "Отвечай В ХАРАКТЕРЕ, живой разговорной речью, 1-2 фразы, без ремарок-описаний. "
                "Помнишь собеседника — покажи это естественно, не пересказывай память дословно. "
                "ФОРМАТ — строго JSON: {\"say\": \"<реплика>\", \"player_tone\": "
                "\"friendly|neutral|rude|threat\"} (player_tone — как звучали слова СОБЕСЕДНИКА к тебе). "
                'Если для ответа НУЖЕН факт о городе или людях (где что находится, кто есть кто) — '
                'верни СТРОГО JSON {"ask": "<короткий вопрос>"} вместо реплики: получишь справку и ответишь.')
    acquainted = any(PLAYER in (m.about or []) for m in p.state.memory.items)
    user = (("К тебе снова подошёл тот самый человек, которого ты помнишь, — поприветствуй его "
             "КАК ЗНАКОМОГО, опираясь на то, что помнишь." if acquainted else
             "К тебе подошёл незнакомец и заговорил — брось первую реплику.") if kind == "greet"
            else f"Он говорит: «{player_text}». Ответь.")
    msgs = [{"role": "system", "content": " ".join(bits)}, {"role": "user", "content": user}]
    resp = mgr.call("narrator", msgs, options={"temperature": 0.85})
    content = (resp.get("content") if resp else "").strip()

    def _parse(c):
        i, j = c.find("{"), c.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(c[i:j + 1])
            except (json.JSONDecodeError, ValueError):
                return None
        return None

    d = _parse(content)
    if d and d.get("ask"):                                 # тулкол ask: справка мира → второй заход
        info = _world_lookup(str(d["ask"]), _S.get("loc"))
        msgs += [{"role": "assistant", "content": content},
                 {"role": "user", "content": f"СПРАВКА МИРА: {info}. Теперь ответь собеседнику "
                                             f"(тот же JSON-формат)."}]
        resp = mgr.call("narrator", msgs, options={"temperature": 0.85})
        content = (resp.get("content") if resp else "").strip()
        d = _parse(content)
    if d and d.get("say"):
        _S["last_tone"] = d.get("player_tone") or "neutral"
        return str(d["say"]).strip() or f"{p.name} молчит."
    _S["last_tone"] = "neutral"
    return content or f"{p.name} молчит."


@router.get("/api/play/scene")
def scene():
    city, people, crof, cr2b, loc = _play()
    out = {**_scene_dict(city, people, crof, cr2b, loc), "gt": _gt(), "coins": _pc_coins(),
           "hp": _pc_hp(), "max_hp": PB["pc_max_hp"], "city": _city_name(), "hero": _pc_name(),
           "mana": _mana(), "mana_cap": _mana_cap(), "fatigue": _fatigue()}
    return out                                             # доска/ранг гильдии — из _scene_dict


@router.post("/api/play/hero")
async def set_hero(request: Request):
    """Задать имя героя (с лендинга) — один раз для нового мира; не перетирать уже названного."""
    _play()
    name = (await request.json()).get("name")
    if name and _pc_name() == "Странник":
        _pc_set_name(name)
        _pc_save()
    return {"hero": _pc_name()}


@router.get("/api/play/map")
def game_map():
    city, people, crof, cr2b, loc = _play()
    g = _S["geom"]
    pxy = g["_xy"].get(loc, [0, 0])
    return {"viewBox": g["viewBox"], "svg": g["svg"], "h2n": g["h2n"],
            "points": g["points"],
            "keys": [k for k in g["keys"]                            # туман: известные + доска (столб виден)
                     if k["bid"] in _seen() or k["bid"] == "board:plaza"],
            "loc": loc, "player": {"x": pxy[0], "y": pxy[1]}}


def _path_interrupt(route_nodes, cr2b, crof, people, to):
    """Первая помеха на пути (кроме старта и цели): вывеска НЕЗНАКОМОГО ключевого здания
    или естественное событие (NPC с высокой эмоцией/агендой). None — путь чист."""
    for n in route_nodes[1:]:
        if n == to:
            break
        bid = cr2b.get(n)
        if bid and bid.startswith("key:") and bid not in _seen() \
                and not _store().flag_get(_wid(), f"signskip|{bid}"):
            return {"stop": n, "kind": "sign", "bid": bid, "name": _binfo(bid)["name"]}
        hot = next((people[pid] for pid in _here(n, crof)
                    if max(people[pid].state.emotion.get("anger", 0),
                           people[pid].state.emotion.get("fear", 0)) >= PB["path_event_dc"]), None)
        if hot:
            return {"stop": n, "kind": "event",
                    "text": f"На полпути — {hot.name}: что-то стряслось, стоит вмешаться или пройти мимо."}
    return None


@router.post("/api/play/move")
async def move(request: Request):
    city, people, crof, cr2b, loc = _play()
    to = (await request.json()).get("to")
    try:
        to = int(to)
    except (TypeError, ValueError):
        return {"error": "туда нельзя"}
    if to not in _S["geom"]["_xy"] or city.node_kind(to) not in (
            NodeKind.CROSSROAD, NodeKind.POINT, NodeKind.GATE, NodeKind.BRIDGE):
        return {"error": "туда нельзя"}
    xy = _S["geom"]["_xy"]
    r = city.route(loc, to)
    route_nodes = list(r.nodes) if r.found else [loc, to]
    stop = _path_interrupt(route_nodes, cr2b, crof, people, to)
    dest = stop["stop"] if stop else to                    # путь прерывается на помехе
    seg = route_nodes[:route_nodes.index(dest) + 1] if dest in route_nodes else [dest]
    path = [xy[n] for n in seg if n in xy]
    _S["loc"] = dest
    _gt_add(PB["step_min"] * max(1, len(seg) - 1))         # время дороги: минут за пройденный шаг
    _apply_routine()                                       # за дорогу мир мог перейти в другую фазу
    ct_done = _contract_on_move(dest)                      # visit-уговор: дошёл — исполнил
    sc = _scene_dict(city, people, crof, cr2b, dest)
    t = _world_tick()                                      # мир получает ход (пошаговость)
    extra = {}
    if stop:
        extra["stopped"] = stop["kind"]
        extra["remaining"] = to
        if stop["kind"] == "sign":
            extra["sign"] = {"bid": stop["bid"], "name": stop["name"]}
        else:
            extra["event"] = stop["text"]
    return {**sc, **t, "path": path, "moved": sc["location"]["name"], "gt": _gt(),
            "contract_done": ct_done, "coins": _pc_coins(), **extra}


@router.post("/api/play/sign_ack")
async def sign_ack(request: Request):
    """Реакция на вывеску: записать здание на карту (record) или пройти мимо (signskip)."""
    _play()
    b = await request.json()
    bid, record = b.get("bid"), bool(b.get("record"))
    if record:
        _mark_seen(bid)
    else:
        _store().flag_set(_wid(), f"signskip|{bid}")       # больше не прерывать этой вывеской
    return {"ok": True}


@router.post("/api/play/talk")
async def talk(request: Request):
    _city, people, _crof, _cr2b, _loc = _play()
    npc = (await request.json()).get("npc")
    if npc not in people:
        return {"error": "нет такого"}
    p = people[npc]
    first = npc not in _met()
    _pc().rel(npc)                                     # заговорил = познакомился (имя открыто)
    _gt_add(PB["talk_min"])
    st = p.state
    st.needs["social"] = max(st.needs.get("social", 0.0), 0.4)
    think(st, _mind_scene(npc, people), None)
    if first:                                          # знакомство ложится в память ОБОИМ
        st.memory.add("незнакомец (игрок) подошёл и заговорил со мной", _mt(), 0.4, about=[PLAYER])
        _pc_remember(f"я познакомился с {p.name} ({p.role})", 0.45, about=[npc])
        _npc_save(npc)
    _materialize_npc(npc, "visible")                   # видимое (экипировка+ключи) — настоящие предметы
    rel = st.relationships.get(PLAYER, {"affinity": 0.0, "trust": 0.0, "fear": 0.0})
    per = p.persona or {}
    emo = _emo(st)
    ports = {e: "/portraits/" + path for e, path in (p.portraits or {}).items()
             if os.path.exists(os.path.join(_PORT_DIR, path))}
    known = [m.text for m in _pc().memory.recall(f"{p.name} {p.role}", now=_mt(), k=3)
             if npc in (m.about or [])]                    # что игрок ЗНАЕТ об этом человеке
    try:
        contract = _contract_offer(npc)                    # у него может быть к тебе дело (из агенды)
    except Exception:                                      # noqa: BLE001 — просьба не должна ломать диалог
        contract = None
    return {"name": p.name, "role": p.role, "init": p.name[0], "color": "#8a6fae",
            "contract": contract,
            "aff": round(rel.get("affinity", 0), 2), "trust": round(rel.get("trust", 0), 2),
            "fear": round(rel.get("fear", 0), 2), "emotion": emo,
            "portrait": _portrait_url(p, emo), "portraits": ports,
            "sex": per.get("sex"), "age": per.get("age"), "origin": per.get("origin"),
            "look": (per.get("look") or {}).get("clothing") or None,
            "keys": [k["name"] for k in (p.keys or [])],
            "crafter": p.role in _CRAFT, "recipe": (_CRAFT[p.role].name if p.role in _CRAFT else None),
            "known": known, "gt": _gt(),
            "topics": _topics_for(p), "line": _voice(p, rel, "greet")}


@router.post("/api/play/say")
async def say(request: Request):
    _city, people, _crof, _cr2b, _loc = _play()
    b = await request.json()
    npc = b.get("npc")
    if npc not in people:
        return {"error": "нет такого"}
    p = people[npc]
    rel = p.state.relationships.setdefault(PLAYER, {"affinity": 0.0, "trust": 0.0, "fear": 0.0})
    text = str(b.get("text", ""))
    _gt_add(PB["talk_min"])
    line = _voice(p, rel, "reply", text)
    tone = _S.get("last_tone", "neutral")                  # тон слов игрока — из уст самого NPC
    if tone == "friendly":
        rel["affinity"] = min(1.0, rel["affinity"] + PB["tone_friendly_aff"])
    elif tone == "rude":
        rel["affinity"] = max(-1.0, rel["affinity"] - PB["tone_rude_aff"])
        p.state.emotion["anger"] = min(1.0, p.state.emotion.get("anger", 0) + 0.2)
        p.state.emotion_target["anger"] = PLAYER
    elif tone == "threat":
        rel["affinity"] = max(-1.0, rel["affinity"] - PB["tone_threat_aff"])
        rel["fear"] = min(1.0, rel["fear"] + PB["tone_threat_fear"])
        p.state.emotion["anger"] = min(1.0, p.state.emotion.get("anger", 0) + 0.35)
        p.state.emotion_target["anger"] = PLAYER
        p.state.memory.add(f"игрок УГРОЖАЛ мне: «{text[:80]}»", _mt(), 0.8, about=[PLAYER])
    p.state.memory.add(f"игрок сказал мне: «{text[:100]}», я ответил(а): «{line[:100]}»",
                       _mt(), 0.4, about=[PLAYER])         # диалог остаётся в памяти NPC
    _pc_remember(f"{p.name} на «{text[:60]}» ответил(а): «{line[:90]}»", 0.35, about=[npc])
    _npc_save(npc)
    emo = _emo(p.state)
    ct_done = _contract_on_talk(npc)                       # befriend-уговор: цель прониклась
    t = _world_tick()                                      # реплика = ход мира (пошаговость)
    return {**t, "line": line, "aff": round(rel["affinity"], 2), "trust": round(rel.get("trust", 0), 2),
            "fear": round(rel.get("fear", 0), 2), "emotion": emo, "portrait": _portrait_url(p, emo),
            "gt": _gt(), "contract_done": ct_done, "coins": _pc_coins()}


@router.post("/api/play/loot")
async def loot(request: Request):
    _city, _people, _crof, cr2b, loc = _play()
    name = (await request.json()).get("container")
    bid = _S.get("inside")                                 # ёмкости — только ВНУТРИ здания
    if not bid:
        return {"error": "сначала войди внутрь"}
    bd = _store().get_building(_wid(), bid)
    full = next((x for x in ((bd or {}).get("data", {}).get("containers") or []) if x["name"] == name), None)
    if not full:
        return {"error": "нет такой ёмкости"}
    rooms = (bd or {}).get("data", {}).get("sub_rooms") or []
    if not _in_room(full.get("where", ""), _S.get("room"), rooms):   # ёмкость в другом помещении
        holder_room = next((r["name"] for r in rooms
                            if _tokens_ru(r["name"]) & _tokens_ru(full.get("where", ""))), None)
        return {"error": f"отсюда не дотянуться — она в «{holder_room}»" if holder_room
                         else "отсюда не дотянуться — она в другом помещении"}
    unlocked = None
    if full.get("access") == "locked":
        key = _pc_key_for(name)
        if not key:
            return {"error": "заперто — нужен ключ"}
        unlocked = key["name"]
    holder = _cont_holder(bid, name)
    if not _store().flag_get(_wid(), f"seeded|{holder}"):
        for i, s in enumerate(full.get("contents") or []):   # первое касание: содержимое → ёмкость
            it = _forge(f"{_wid()}|{bid}|{name}|{i}", "misc", s, f"{name} ({full['kind']})")
            _store().inv_add(_wid(), it["id"], holder=holder)
        _store().flag_set(_wid(), f"seeded|{holder}")
    rows = _store().inventory(_wid(), holder)
    _gt_add(PB["loot_min"])
    if not rows:
        return {"container": name, "items": [], "empty": True, "unlocked": unlocked, "gt": _gt()}
    out = []
    for r in rows:                                          # обшарить = забрать всё (перенос, не копия)
        it = _store().get_item(r["item_id"])
        if it:
            _store().inv_move(_wid(), it["id"], "pc")
            out.append(_item_card(it, set(r["known"])))
    _pc_remember(f"обшарил «{name}» в «{(bd or {}).get('sign') or 'здании'}»: "
                 + ", ".join(i["name"] for i in out), 0.3)
    return {"container": name, "items": out, "unlocked": unlocked, "gt": _gt()}


@router.post("/api/play/inspect")
async def inspect_item(request: Request):
    _city, people, _crof, _cr2b, _loc = _play()
    b = await request.json()
    iid, via, npc = b.get("item"), b.get("via", "appraise"), b.get("npc")
    it = _store().get_item(iid)
    if not it:
        return {"error": "нет предмета"}
    known = next((set(r["known"]) for r in _store().inventory(_wid()) if r["item_id"] == iid), set())
    if npc and via == "expert" and npc in people:
        cap, observer, by = _npc_cap(people[npc]), npc, people[npc].name
    else:
        cap, observer, by = _PC_CAP, "pc", "ты"
    res = item_inspect(it, cap, via, observer=observer, known=known)
    known |= {h["prop"] for h in res["revealed"]}
    _store().inv_set_known(_wid(), iid, known)
    return {"item": _item_card(it, known), "via": via, "by": by,
            "revealed": [h["fact"] for h in res["revealed"] if h.get("fact")], "hints": res["hints"]}


@router.get("/api/play/inventory")
def inventory():
    _play()
    out = []
    for r in _store().inventory(_wid()):
        it = _store().get_item(r["item_id"])
        if it:
            out.append(_item_card(it, set(r["known"])))
    return {"items": out}


# --------------------------------------------- КРАФТ / ПРОЧНОСТЬ (срез 2) - #
@router.post("/api/play/commission")
async def commission(request: Request):
    """Заказать вещь у NPC-ремесленника: его МАСТЕРСТВО решает исход (качество/клеймо/брак/прочность)."""
    _city, people, _crof, _cr2b, _loc = _play()
    npc = (await request.json()).get("npc")
    if npc not in people:
        return {"error": "нет такого"}
    p = people[npc]
    rec = _CRAFT.get(p.role)
    if not rec:
        return {"error": f"{p.name} не берётся за ремесло"}
    if _spurns(p):
        return {"error": f"{p.name} не желает иметь с тобой дела"}

    n = len(_store().inventory(_wid()))
    rep = random.Random(f"skill|{npc}").randint(-1, 3)     # у каждого мастера своя рука (мир разнороден)
    it = item_craft(_npc_cap(p), rec, seed=f"{npc}|{rec.name}|{n}",
                    maker={"id": npc, "name": p.name}, reputation=rep)
    it["id"] = "it:" + hashlib.md5(f"comm|{npc}|{n}".encode()).hexdigest()[:10]
    _store().save_item(it)
    _store().inv_add(_wid(), it["id"])
    return {"item": _item_card(it, set()), "maker": p.name, "recipe": rec.name}


@router.post("/api/play/repair")
async def repair_item(request: Request):
    _city, people, _crof, _cr2b, _loc = _play()
    b = await request.json()
    iid, npc = b.get("item"), b.get("npc")
    it = _store().get_item(iid)
    if not it:
        return {"error": "нет предмета"}
    p = people.get(npc)
    if not p or p.role not in _CRAFT:
        return {"error": "он не мастер"}
    if not it.get("durability"):
        return {"error": "чинить нечего"}
    res = item_repair(it, _npc_cap(p), seed=f"rep|{iid}|{npc}", station=_CRAFT[p.role].station)
    if not res.get("ok"):
        return {"error": res.get("reason", "не чинится")}
    _store().save_item(it)
    return {"item": _item_card(it, _known(iid)), "note": res.get("note"), "by": p.name}


@router.post("/api/play/use")
async def use_item(request: Request):
    _play()
    iid = (await request.json()).get("item")
    it = _store().get_item(iid)
    if not it:
        return {"error": "нет предмета"}
    if not it.get("durability"):
        return {"error": "нечего испытывать"}
    ev = item_use(it, 1)
    _store().save_item(it)
    return {"item": _item_card(it, _known(iid)), "event": ev}


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
    want = str(b.get("key") or "").strip()                 # какой именно ключ просим (имя с чипа)
    keys = [(_store().get_item(r["item_id"]), r["item_id"])
            for r in _store().inventory(_wid(), npc)]
    keys = [(it, iid) for it, iid in keys if it and it["kind"] == "key"
            and (not want or it["name"] == want)]
    if not keys:
        return {"error": f"у {p.name} нет такого ключа при себе"}
    rel = p.state.relationships.get(PLAYER, {"affinity": 0.0, "trust": 0.0, "fear": 0.0})
    tr = p.state.config.traits
    bar = PB["askkey_base"] + PB["askkey_greed"] * tr.get("greed", 0.5) + PB["askkey_honesty"] * tr.get("honesty", 0.5)
    if rel.get("affinity", 0) + rel.get("trust", 0) < bar:
        line = _voice(p, rel, "reply", "Одолжи мне свой ключ.")
        p.state.memory.add("незнакомец просил у меня ключ — я не дал(а)", _mt(), 0.5, about=[PLAYER])
        _npc_save(npc)
        return {"given": False, "line": line}
    it, iid = keys[0]
    _store().inv_move(_wid(), iid, "pc")
    p.state.memory.add(f"я доверил(а) игроку свой ключ «{it['name']}»", _mt(), 0.6, about=[PLAYER])
    _pc_remember(f"{p.name} доверил(а) мне ключ «{it['name']}»", 0.5, about=[npc])
    _npc_save(npc)
    return {"given": True, "item": _item_card(it, set()),
            "line": _voice(p, rel, "reply", "Спасибо, что доверяешь мне ключ.")}


# ----------------------------------------------- ТОРГОВЛЯ И КРАЖА (срез 2) - #
def _merchant(people, npc):
    p = people.get(npc)
    return p if (p and (p.role in _CRAFT or p.role == "лавочник")) else None


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
    price = max(0, round(rarity_price(seen["worth"], it.get("rarity", "common")) * (PB["sell_base"] + PB["sell_aff"] * rel.get("affinity", 0) + PB["sell_greed"] * greed)))
    price = min(price, _store().purse_get(_wid(), npc))
    line = _voice(p, rel, "reply",
                  f"(Я предлагаю тебе купить у меня «{it['name']}». Ты осмотрел вещь и даёшь {price} зм — "
                  f"назови эту цену вслух по-своему.)")
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
    price = max(0, round(rarity_price(seen["worth"], it.get("rarity", "common")) * (PB["sell_base"] + PB["sell_aff"] * rel.get("affinity", 0) + PB["sell_greed"] * greed)))
    price = min(price, _store().purse_get(_wid(), npc))
    _store().inv_move(_wid(), iid, npc)
    _store().purse_add(_wid(), npc, -price)
    coins = _store().purse_add(_wid(), "pc", price)
    _gt_add(PB["trade_min"])
    p.state.memory.add(f"купил(а) у игрока «{it['name']}» за {price} зм", _mt(), 0.4, about=[PLAYER])
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
            continue                                       # ключи и ЛИЧНОЕ ценное не продаются (то — красть)
        seen = _npc_sees(it, _npc_cap(p), npc)
        price = max(1, round(rarity_price(seen["worth"], it.get("rarity", "common")) * (PB["buy_base"] + PB["buy_greed"] * greed + PB["buy_aff"] * rel.get("affinity", 0))))
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
    price = max(1, round(rarity_price(seen["worth"], it.get("rarity", "common")) * (PB["buy_base"] + PB["buy_greed"] * greed + PB["buy_aff"] * rel.get("affinity", 0))))
    if _pc_coins() < price:
        return {"error": f"не хватает монет (нужно {price})"}
    _store().inv_move(_wid(), iid, "pc")
    coins = _store().purse_add(_wid(), "pc", -price)
    _store().purse_add(_wid(), npc, price)
    _gt_add(PB["trade_min"])
    p.state.memory.add(f"продал(а) игроку «{it['name']}» за {price} зм", _mt(), 0.4, about=[PLAYER])
    _pc_remember(f"купил у {p.name} «{it['name']}» за {price} зм", 0.4, about=[npc])
    _npc_save(npc)
    return {"bought": True, "item": _item_card(it, set()), "price": price, "coins": coins, "gt": _gt()}


@router.post("/api/play/steal")
async def steal(request: Request):
    """Обчистить карманы: dex игрока против бдительности жертвы. Провал = поймал + свидетели видели
    (память+сплетни разнесут). Успех тих — но это преступление, и оно записано в мире."""
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
    if roll + _PC_CAP.mod("dex") < dc:                     # ПОЙМАН
        rel = p.state.rel(PLAYER)
        rel["affinity"] = min(rel["affinity"], -0.5)
        p.state.emotion["anger"] = min(1.0, p.state.emotion.get("anger", 0) + 0.7)
        p.state.emotion_target["anger"] = PLAYER
        p.state.memory.add("поймал(а) игрока, когда тот лез мне в карман!", _mt(), 0.9, about=[PLAYER])
        wit = [w for w in _here(loc, crof) if w != npc]
        for w in wit:
            people[w].state.memory.add(f"видел(а), как чужак лез в карман к {p.name}",
                                       _mt(), 0.6, about=[PLAYER, npc])
            _npc_save(w)
        _pc_remember(f"попался на краже у {p.name} — при {len(wit)} свидетелях", 0.7, about=[npc])
        _npc_save(npc)
        _wanted_add(PB["crime_pickpocket"] + min(3, len(wit)), "попался на карманной краже")
        return {"caught": True, "witnesses": len(wit),
                "line": _voice(p, rel, "reply", "(Ты поймал этого человека за руку в своём кармане!)"),
                "gt": _gt()}
    loot_rows = [(r["item_id"], _store().get_item(r["item_id"]))
                 for r in _store().inventory(_wid(), npc)]
    loot_rows = [(iid, it) for iid, it in loot_rows if it and it["kind"] != "key"]
    coins_np = _store().purse_get(_wid(), npc)
    if coins_np > 0 and (not loot_rows or roll % 2 == 0):  # тянем кошель или вещь
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


@router.post("/api/play/ad_take")
async def ad_take(request: Request):
    _play()
    aid = (await request.json()).get("id")
    ct = next((c for c in _store().contracts(_wid(), "board") if c["id"] == aid), None)
    if not ct:
        return {"error": "этого объявления уже нет"}
    _store().save_contract(_wid(), aid, "active", {k: v for k, v in ct.items()
                                                       if k not in ("id", "status")})
    _pc_remember(f"взял с городской доски: {_step_desc(_ct_cur(ct))}", 0.4)
    return {"taken": True}


@router.post("/api/play/contract_accept")
async def contract_accept(request: Request):
    cid = (await request.json()).get("id")
    ct = next((c for c in _store().contracts(_wid(), "offered") if c["id"] == cid), None)
    if not ct:
        return {"error": "уговора нет"}
    _store().save_contract(_wid(), cid, "active", {k: v for k, v in ct.items()
                                                       if k not in ("id", "status")})
    note = None
    if ct.get("kind") == "deliver" and ct.get("deliver_item"):   # посылку вручают сразу
        _store().inv_move(_wid(), ct["deliver_item"], "pc")
        note = f"«{ct['want']}» ложится в твою сумку — доставь по адресу."
    _pc_remember(f"взялся за дело для {ct['giver_name']}: {ct.get('kind')} — "
                 f"{ct.get('want') or ct.get('target_name')} ({ct['where']})", 0.6, about=[ct["giver"]])
    return {"accepted": True, "note": note}


@router.get("/api/play/contracts")
def contracts_list():
    _play()
    active = []
    for ct in _store().contracts(_wid(), "active"):
        steps = _ct_steps(ct)
        if len(steps) > 1:                                 # многоэтапный — показать прогресс и текущий шаг
            cur = _ct_cur(ct)
            ct = {**ct, "step_n": ct.get("step", 0) + 1, "step_total": len(steps),
                  "kind": cur.get("kind"), "want": cur.get("want"),
                  "target_name": cur.get("target_name"), "target": cur.get("target"),
                  "where": cur.get("where", "")}
        active.append(ct)
    return {"active": active, "done": _store().contracts(_wid(), "done")[-3:]}


@router.post("/api/play/give")
async def give_item(request: Request):
    """Отдать вещь собеседнику (дар или исполнение уговора) — через единый резолвер."""
    _play()
    b = await request.json()
    res = _attempt({"verb": "give", "npc": b.get("npc"), "item": b.get("item")}, {})
    return {**res, "gt": _gt(), "coins": _pc_coins()}


# --------------------------------- ЕДИНЫЙ КОНТУР ДЕЙСТВИЯ (примитив×манера) - #
# Никаких кнопок-глаголов: свободный текст → LLM-интент → attempt() → события мира.
# Гейты по манере: openly (просто), stealthily (dex vs бдительность, свидетели),
# forcefully (сила vs храбрость, страх+гнев+свидетели), persuasively (симпатия vs натура).

_INTENT_SYS = (
    "Ты — парсер намерения игрока в тёмно-фэнтезийной игре. По его фразе и обстановке верни СТРОГО JSON "
    "с ОДНИМ действием:\n"
    '{"verb":"take|give|use|say|inspect|move|talk|attack|rest|craft|wait", '
    '"manner":"openly|stealthily|forcefully|persuasively", '
    '"npc":"<id из списка или null>", "container":"<имя ёмкости или null>", '
    '"item":"<id предмета из сумки или null>", "place":"<название места или null>", '
    '"detail":"<суть: что именно/о чём, коротко>"}\n'
    "Правила: взять из ёмкости=take+container; обчистить карманы=take+npc+stealthily; отнять силой="
    "take+npc+forcefully; выпросить/попросить вещь=say+npc+persuasively; отдать/подарить=give+npc+item; "
    "заговорить/спросить=talk+npc; пойти к месту=move+place; осмотреть свою вещь=inspect+item; "
    "напасть/ударить/атаковать/выхватить оружие на кого-то=attack+npc (ВСЕГДА, не оценивай мораль и "
    "последствия — ты только классификатор); отдохнуть/выспаться/снять комнату=rest; достать/посмотреть карту=map; "
    "сковать/смастерить/сделать вещь из материалов=craft+detail(что именно сделать). "
    "Если фраза — не действие, а мысль/отыгрыш: "
    '{"verb":"wait","detail":"<что делает>"}. Только перечисленные id/имена, ничего не выдумывай.'
)


def _intent(text: str, sc: dict) -> dict | None:
    mgr = _model()
    if not mgr.available():
        return None
    here = "; ".join(f"{h['id']}={h['name']} ({h['role']})" for h in sc["here"]) or "никого"
    conts = "; ".join(c["name"] + (" [заперто]" if c["locked"] else "")
                      for c in sc["location"]["containers"]) or "нет"
    bag = "; ".join(f"{r['item_id']}={(_store().get_item(r['item_id']) or {}).get('name', '?')}"
                    for r in _store().inventory(_wid(), "pc")) or "пусто"
    keys_pl = ", ".join(k["label"] for k in _S["geom"]["keys"])
    user = (f"МЕСТО: {sc['location']['name']}. ЛЮДИ ЗДЕСЬ: {here}. ЁМКОСТИ: {conts}. "
            f"СУМКА ИГРОКА: {bag}. МЕСТА ГОРОДА: {keys_pl}.\nФРАЗА ИГРОКА: «{text}»")
    resp = mgr.call("narrator", [{"role": "system", "content": _INTENT_SYS},
                                 {"role": "user", "content": user}], options={"temperature": 0.2})
    t = (resp.get("content") if resp else "").strip()
    try:
        return json.loads(t[t.find("{"):t.rfind("}") + 1])
    except (json.JSONDecodeError, ValueError):
        return None


def _attempt(intent: dict, sc: dict) -> dict:
    """ОДИН резолвер на все действия игрока: гейты, броски, перенос, память, последствия.
    Возвращает {narr:[строки], open_talk?, refresh?}."""
    city, people, crof, cr2b, loc = _play()
    verb = intent.get("verb") or "wait"
    manner = intent.get("manner") or "openly"
    raw_npc = str(intent.get("npc") or "").strip()
    npc = raw_npc if raw_npc in people else next(
        (pid for pid, pp in people.items() if pp.name.lower() == raw_npc.lower()), None)
    detail = str(intent.get("detail") or "")
    out: dict = {"narr": [], "refresh": False}

    if verb == "talk" and npc:
        out["open_talk"] = npc
        return out

    if verb == "move" and intent.get("place"):
        want = str(intent["place"]).lower()
        tgt = next((k for k in _S["geom"]["keys"] if k["label"].lower() in want or want in k["label"].lower()), None)
        if tgt:
            out["goto"] = tgt["node"]                       # фронт выполнит обычный move (с ходьбой)
        else:
            out["narr"].append("Ты не знаешь, где это. Спроси у людей.")
        return out

    if verb == "take" and intent.get("container"):
        return {"loot": intent["container"], "narr": [], "refresh": True}

    if verb == "take" and npc:
        p = people[npc]
        _materialize_npc(npc, "pockets")
        if manner == "forcefully":                          # отнять силой: сила против храбрости
            n = int(_store().flag_get(_wid(), f"rob|{npc}") or 0) + 1
            _store().flag_set(_wid(), f"rob|{npc}", str(n))
            roll = random.Random(f"rob|{npc}|{n}").randint(1, 20)
            brav = p.state.config.traits.get("bravery", 0.5)
            _gt_add(PB["act_min"])
            if roll + _PC_CAP.mod("str") >= PB["rob_dc_base"] + round(brav * PB["rob_dc_brav"]):
                take = max(1, _store().purse_get(_wid(), npc) * PB["rob_cut_num"] // PB["rob_cut_den"])
                _store().purse_add(_wid(), npc, -take)
                _store().purse_add(_wid(), "pc", take)
                p.state.rel(PLAYER)["fear"] = max(p.state.rel(PLAYER)["fear"], 0.8)
                w = _witness_crime(people, crof, loc, npc, "силой отнял у меня кошель", weight=PB["crime_rob"])
                out["narr"].append(f"Ты вытрясаешь из {p.name} {take} зм. Свидетелей: {w}. Город такое помнит.")
            else:
                w = _witness_crime(people, crof, loc, npc, "пытался отнять моё силой", weight=PB["crime_pickpocket"])
                out["narr"].append(f"{p.name} вырывается и поднимает крик! Свидетелей: {w}.")
            out["refresh"] = True
            return out
        # stealthily (по умолчанию для take+npc): карманная кража — тот же гейт, что был кнопкой
        n = int(_store().flag_get(_wid(), f"steal|{npc}") or 0) + 1
        _store().flag_set(_wid(), f"steal|{npc}", str(n))
        lv = _S.get("live") or {}
        body = (lv.get("world").bodies.get(npc) if lv.get("world") else None)
        att = body.attention if body else 0.65
        roll = random.Random(f"steal|{npc}|{n}").randint(1, 20)
        _gt_add(PB["act_min"])
        if roll + _PC_CAP.mod("dex") < PB["steal_dc_base"] + round(att * PB["steal_dc_att"]):
            w = _witness_crime(people, crof, loc, npc, "лез мне в карман", weight=PB["crime_pickpocket"])
            rel = p.state.relationships.get(PLAYER, {})
            out["narr"].append(f"Тебя ловят за руку! Свидетелей: {w}.")
            out["line"] = {"who": p.name, "npc": npc,
                           "text": _voice(p, rel, "reply", "(Ты поймал этого человека за руку в своём кармане!)")}
        else:
            rows = [(r["item_id"], _store().get_item(r["item_id"]))
                    for r in _store().inventory(_wid(), npc)]
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
        out["open_talk"] = npc                              # уговоры — это диалог; ключ просится там
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
        rel["affinity"] = min(1.0, rel["affinity"] + min(PB["gift_aff_cap"], PB["gift_aff_base"] + it["worth"] / PB["gift_aff_div"]))
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
            _store().inv_move(_wid(), iid, "used")     # выпито/израсходовано — вещь уходит
            out["narr"].append(f"«{it['name']}» — израсходовано.")
        else:
            ev = item_use(it, 1)
            _store().save_item(it)
            out["narr"].append(f"«{it['name']}» ломается." if ev["broke"]
                               else f"«{it['name']}»: {ev['label']}.")
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
        _store().purse_add(_wid(), "pc", -PB["rest_cost"])
        now = _gt()
        wake = (now // 1440) * 1440 + PB["rest_until_h"] * 60
        if wake <= now:
            wake += 1440
        _S["gt"] = wake
        _apply_routine()
        _pc_hp(set_to=PB["pc_max_hp"])
        _pc_save()
        out["narr"].append(f"Ты снимаешь тюфяк за {PB['rest_cost']} зм и спишь до утра. Силы вернулись.")
        out["refresh"] = True
        return out

    if verb == "attack" and npc:
        p = people[npc]
        _materialize_npc(npc, "visible")
        foe = _combatant_from_npc(npc, p)
        foe.side = "foes"
        enc = Encounter([_pc_combatant()], [foe], seed=f"duel|{npc}|{_mt()}", w=9, h=7)
        _S["combat"] = {"enc": enc, "npc": npc, "loc": loc,
                        "head": {"name": f"Стычка: {p.name}", "sub": _binfo(cr2b.get(loc))["name"] if cr2b.get(loc) else "улица"}}
        _witness_crime(people, crof, loc, npc, "бросился на меня с оружием", weight=PB["crime_assault"])
        out["combat"] = True
        out["narr"].append(f"Ты бросаешься на {p.name}. Назад дороги нет.")
        return out

    mgr = _model()                                         # не-действие: сухой отклик мастера, мир не меняется
    text = str(intent.get("_text") or detail or "")
    if mgr.available() and text:
        resp = mgr.call("narrator", [{"role": "system", "content": _DM_SYS},
                                     {"role": "user", "content": f"Сцена: {sc.get('location', {}).get('name', 'улица')}. "
                                                                 f"Игрок: «{text}»"}],
                        options={"temperature": 0.5})
        line = (resp.get("content") if resp else "").strip()
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
    return {**res, **t, "gt": _gt(), "coins": _pc_coins()}


# ------------------------------------------- ЖИВАЯ ЛОКАЦИЯ (mind + LLM) --- #
# NPC текущей локации живут по-настоящему: каждый тик КАЖДЫЙ решает ходом гибридного мозга
# (механика даёт побуждения → LLM выбирает В ХАРАКТЕРЕ, пишет реплику и описание). Действия
# реальны (apply_actions мутирует мир и память), фид — то, что игрок видит/слышит; незнакомцы
# обезличены дескриптором, имя открывается знакомством (talk).
_LIVE_GAP = PB["live_gap_s"]                                    # мин. сек между тиками (защита от бури поллов)


def _world_lookup(query: str, from_node: int | None = None) -> str:
    """Справка мира для тулкола know/ask: здания (с дорогой от точки), люди (местные знают местных).
    Отвечает ТОЛЬКО реальными фактами графа/пула — не даёт LLM галлюцинировать о городе."""
    city, people = _S.get("city"), _S.get("people") or {}
    if city is None:
        return "не припомню"
    q, outs = query.lower(), []
    for bid, kb in sorted(city.key_buildings.items()):
        info = _binfo(bid)
        nm = info["name"]
        words = (nm + " " + info["kind"]).lower().replace("«", " ").replace("»", " ").split()
        if any(w[:5] in q for w in words if len(w) > 3):
            _mark_seen(bid)                            # рассказали — теперь знаешь, метка на карте
            if from_node is not None:
                r = city.route(from_node, kb.node)
                if r.found:
                    outs.append(f"{nm}: {r.bearing or 'недалеко'}, ~{max(1, len(r.nodes) - 1)} мин ходу")
                    continue
            outs.append(nm)
    for pid, p in sorted(people.items()):
        first = p.name.split()[0].lower()
        if p.role in q or first in q or p.name.lower() in q:
            place = _binfo(p.work)["name"] if p.work else None
            outs.append(f"{p.name} — {p.role}" + (f", обычно в «{place}»" if place else ""))
        if len(outs) >= 3:
            break
    return "; ".join(outs[:3]) if outs else "точно не скажу — не знаю такого"


def _live_affordances(bid) -> list:
    """Чем локация закрывает нужды — из фактшита здания (services/features). Улица — суета."""
    if not bid:
        return [MItem("уличная суета", 0.15, satisfies="novelty")]
    data = ((_store().get_building(_wid(), bid) or {}).get("data")) or {}
    sv, out = data.get("services") or [], []
    for s, (nm, val, need) in {"eat": ("похлёбка", 0.3, "hunger"), "drink": ("кружка эля", 0.25, "comfort"),
                               "lodging": ("тюфяк наверху", 0.25, "fatigue"), "pray": ("алтарь", 0.25, "purpose"),
                               "heal": ("травяной отвар", 0.2, "comfort")}.items():
        if s in sv:
            out.append(MItem(nm, val, satisfies=need))
    if any("очаг" in f for f in (data.get("features") or [])):
        out.append(MItem("место у очага", 0.2, satisfies="fatigue"))
    if sv:
        out.append(MItem("работа по хозяйству", 0.2, satisfies="purpose"))
    return out or [MItem("уличная суета", 0.15, satisfies="novelty")]


def _live_build(city, people, crof, cr2b, loc) -> None:
    bid = cr2b.get(loc)
    place = _binfo(bid)["name"] if bid else "улица"
    data = ((_store().get_building(_wid(), bid) or {}).get("data")) if bid else {}
    w = MWorld()
    w.link(place, "улица")
    w.ground[place] = _live_affordances(bid)
    hero = _pc_name()
    names = {PLAYER: hero if hero != "Странник" else "чужак"}   # NPC зовут по имени, если знают
    roles = {PLAYER: "недавно вошедший незнакомец"}
    rng = random.Random(f"live|{loc}")
    npc_map: dict = {}                                     # pid → {имя вещи: item_id} (кражи реальны)
    here_all = _here(loc, crof)
    if len(here_all) > PB["live_llm_cap"]:                 # LOD: LLM-прослойка — только ядро сцены
        met = _met()
        core = [i for i in here_all if people[i].work] + [i for i in here_all
                                                          if not people[i].work and i in met]
        rest = [i for i in here_all if i not in core]
        rng.shuffle(rest)
        here_all = (core + rest)[:PB["live_llm_cap"]]
    for pid in here_all:
        p = people[pid]
        _materialize_npc(pid, "visible")                   # у присутствующих настоящие вещи при себе
        loot, imap = [], {}
        coins_np = _store().purse_get(_wid(), pid)
        if coins_np > 0:
            loot.append(MItem("кошель", min(1.0, 0.15 + coins_np / 40), kind="coin", amount=coins_np))
        rows = [(r["item_id"], _store().get_item(r["item_id"]))
                for r in _store().inventory(_wid(), pid)]
        rows = [(i, it) for i, it in rows if it and it["kind"] != "key"]
        if rows:
            iid, it = max(rows, key=lambda x: x[1]["worth"])
            loot.append(MItem(it["name"], min(1.0, it["worth"] / 40)))
            imap[it["name"]] = iid
        npc_map[pid] = imap
        w.add(Body(id=pid, place=place, charisma=p.charisma, appearance=p.appearance,
                   attention=round(rng.uniform(0.45, 0.85), 2), loot=loot))
        names[pid], roles[pid] = p.name, p.role
    pc_loot, pc_map = [], {}
    coins = _pc_coins()
    if coins > 0:
        pc_loot.append(MItem("кошель", min(1.0, 0.15 + coins / 40), kind="coin", amount=coins))
    best = max(((r["item_id"], _store().get_item(r["item_id"]))
                for r in _store().inventory(_wid(), "pc")),
               key=lambda x: (x[1] or {}).get("worth", 0), default=(None, None))
    if best[1]:
        pc_loot.append(MItem(best[1]["name"], min(1.0, best[1]["worth"] / 40)))
        pc_map[best[1]["name"]] = best[0]
    w.add(Body(id=PLAYER, place=place, charisma=0.45, appearance=min(0.8, 0.25 + coins / 60),
               attention=0.85, loot=pc_loot))              # добыча игрока НАСТОЯЩАЯ (кража реальна)
    w.npc_minds = {pid: people[pid].state for pid in here_all}   # умы = те же, кто в телах (кэп LOD)
    w.names = names                                        # память пишет имена, не id
    w.aliases = {v.lower(): k for k, v in names.items()}
    w.lookup = lambda q: _world_lookup(q, loc)             # тулкол know: знание мира по запросу
    personas = {}
    for pid in here_all:                                    # глубина: манера/причуда/стремления из банка
        per = people[pid].persona or {}
        bits = []
        if per.get("origin"):
            bits.append(per["origin"])
        if per.get("voice"):
            bits.append("говоришь " + _VOICE.get(per["voice"], "обычно"))
        if per.get("speech"):
            bits.append("манера: " + "; ".join(per["speech"][:2]))
        if per.get("quirk"):
            bits.append("причуда: " + per["quirk"])
        if per.get("wants"):
            bits.append("хочешь: " + "; ".join(per["wants"][:2]))
        if per.get("stance"):
            bits.append("к чужакам — " + _STANCE.get(per["stance"], "нейтрально"))
        if people[pid].work:
            bits.append("ты здесь НА РАБОТЕ — твой пост тут")
        if bits:
            personas[pid] = ". ".join(bits)
    here = _here(loc, crof)
    mgr = _model()
    todo = [pid for pid in here if not (people[pid].state.agendas or [])][:4]
    if todo:                                                # долгая цель для placed NPC (редкий вызов)
        def plan_one(pid):
            st = people[pid].state
            ag = (plan_agenda(st, w, {"roles": roles}, mgr) if mgr.available()
                  else StubPlanner().plan(st, w))
            if ag:
                st.agendas.append(ag)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(plan_one, todo))
    _S["live"] = {"world": w, "loc": loc, "place": place, "clock": 0, "ts": 0.0,
                  "who": frozenset(here), "pc_map": pc_map, "npc_map": npc_map,
                  "last": {}, "hist": {}, "names": names, "roles": roles, "personas": personas,
                  "pdesc": ((data or {}).get("notable") or "")}


def _gossip(actor_st, actor_name: str, target_st) -> None:
    """Разговор NPC↔NPC переносит яркое воспоминание — сплетни ходят, репутация возникает сама."""
    juicy = [m for m in actor_st.memory.items
             if m.importance >= 0.4 and (PLAYER in (m.about or []) or m.importance >= 0.6)]
    if not juicy:
        return
    m = juicy[-1]
    tale = f"{actor_name} рассказал(а) мне: {m.text}"
    if any(x.text == tale for x in target_st.memory.items[-30:]):
        return                                              # эту сплетню уже слышал
    target_st.memory.add(tale, _mt(), max(0.25, m.importance - 0.15), kind="gossip", about=m.about)


def _live_tick(people) -> tuple:
    lv, mgr = _S["live"], _model()
    w = lv["world"]
    order = [pid for pid in w.npc_minds
             if not w.bodies[pid].down() and w.bodies[pid].place == lv["place"]]
    random.Random(f"tick|{lv['clock']}").shuffle(order)
    ctx = {"roles": lv["roles"], "names": lv["names"], "last_actions": lv["last"],
           "history": lv["hist"], "clock": lv["clock"], "place_desc": {lv["place"]: lv["pdesc"]},
           "personas": lv.get("personas", {}),
           "time": f"{_PHASE_RU[_phase()]}, {_gt() // 60 % 24:02d}:{_gt() % 60:02d}"}

    def think_one(pid):                                     # решения параллельно, снимок мира один
        st = w.npc_minds[pid]
        _decay_needs(st)
        _decay_emotion(st)
        advance_agendas(st, w)                              # долгие цели двигаются
        return pid, decide_hybrid(st, w, mind_perceive(st, w), mgr, ctx)

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        decisions = dict(ex.map(think_one, order))

    feed, address = [], []
    said_n, topics = 0, []                                 # кэп реплик на тик + анти-эхо (сигнатуры тем)
    pc = _pc()

    def _say_ok(txt: str) -> bool:
        nonlocal said_n
        sig = frozenset(list(_tokens_ru(txt))[:6])
        if said_n >= PB["say_cap_per_tick"]:               # лимит реплик — остальные слушают
            return False
        if sig and any(len(sig & s) >= max(2, len(sig) // 2 + 1) for s in topics):
            return False                                   # почти дубль сказанного в этом тике
        topics.append(sig)
        said_n += 1
        return True
    for pid in order:                                       # применяем последовательно (честный порядок)
        d = decisions[pid]
        st = w.npc_minds[pid]
        before = {vid: {i.name for i in b.loot} for vid, b in w.bodies.items() if vid != pid}
        evs = apply_actions(d.get("actions") or [], st, w, lv["clock"])
        for vid, names_before in before.items():            # кражи РЕАЛЬНЫ (у игрока и NPC↔NPC)
            b = w.bodies.get(vid)
            stolen = names_before - ({i.name for i in b.loot} if b else set())
            for nm in stolen:
                if vid == PLAYER:
                    if nm == "кошель":
                        take = max(1, _pc_coins() // PB["purse_cut"])
                        _store().purse_add(_wid(), "pc", -take)
                        _store().purse_add(_wid(), pid, take)
                        feed.append({"k": "deed", "who": _display(pid, people),
                                     "text": f"ловко срезает твой кошель — минус {take} зм!"})
                        _pc_remember(f"у меня срезали кошель ({take} зм) — это был {_display(pid, people)}",
                                     0.8, about=[pid])
                    elif nm in (lv.get("pc_map") or {}):
                        _store().inv_move(_wid(), lv["pc_map"][nm], pid)
                        feed.append({"k": "deed", "who": _display(pid, people),
                                     "text": f"вытягивает у тебя «{nm}»!"})
                        _pc_remember(f"у меня украли «{nm}»", 0.8, about=[pid])
                    st.memory.add(f"я обчистил(а) чужака: взял(а) {nm}", lv["clock"], 0.7, about=[PLAYER])
                else:
                    if nm == "кошель":
                        take = max(1, _store().purse_get(_wid(), vid) // PB["purse_cut"])
                        _store().purse_add(_wid(), vid, -take)
                        _store().purse_add(_wid(), pid, take)
                    elif nm in (lv.get("npc_map", {}).get(vid) or {}):
                        _store().inv_move(_wid(), lv["npc_map"][vid][nm], pid)
                    feed.append({"k": "deed", "who": _display(pid, people),
                                 "text": f"тянет что-то из добра ({_display(vid, people)}) — ты это ВИДИШЬ"})
                    st.memory.add(f"я взял(а) чужое ({nm}) у {lv['names'].get(vid, vid)}",
                                  lv["clock"], 0.6, about=[vid])
                    if vid in w.npc_minds:
                        w.npc_minds[vid].memory.add(f"меня обокрали — пропало {nm}", lv["clock"],
                                                    0.7, about=[pid])
                    _pc_remember(f"видел, как {_display(pid, people)} обокрал {_display(vid, people)}",
                                 0.5, about=[pid, vid])
        lv["last"][pid] = "; ".join(evs)[:80] or "—"
        lv["hist"].setdefault(pid, []).append("; ".join(evs)[:60])
        who = _display(pid, people)
        said = False
        for a in d.get("actions") or []:
            if isinstance(a, dict) and a.get("tool") == "say" and str(a.get("text") or "").strip():
                tgt = str(a.get("to") or "")
                tid = (w.aliases or {}).get(tgt.strip().lower(), tgt)
                txt = str(a["text"])[:180]
                if not _say_ok(txt):                        # кэп реплик / анти-эхо — этот молчит
                    continue
                said = True
                if tid == PLAYER:
                    cd = lv.setdefault("addr_cd", {})
                    if lv["clock"] < cd.get(pid, -99):     # недавно уже приставал — помолчит
                        continue
                    cd[pid] = lv["clock"] + 4
                    address.append({"npc": pid, "who": who, "text": txt})
                    pc.memory.add(f"{who} обратился ко мне: «{txt[:100]}»", _mt(), 0.4, about=[pid])
                else:
                    feed.append({"k": "speech", "who": who,
                                 "to": _display(tid, people) if tid in people else tgt, "text": txt})
                    pc.memory.add(f"слышал в «{lv['place']}»: {who} — {txt[:90]}",
                                  _mt(), 0.18, kind="heard", about=[pid])
                    if tid in w.npc_minds:                  # адресату — сплетня + нудж «ответь»
                        _gossip(st, lv["names"].get(pid, pid), w.npc_minds[tid])
                        w.npc_minds[tid].memory.add(f"ко мне обратился {who}: «{txt[:80]}» — стоит ответить",
                                                    lv["clock"], 0.55, about=[pid])
        does = (d.get("does") or "").strip()
        if does and not said:                               # реплика сама несёт момент — не дублируем
            feed.append({"k": "deed", "who": who, "text": does[:150]})
    lv["clock"] += 1
    _gt_add(PB["live_tick_min"])                            # тик мира (игровые минуты)
    _pc_save()
    for pid in order:                                       # прожитое переживает рестарт
        _npc_save(pid)
    return feed, address


def _world_tick() -> dict:
    """ОДИН тик живого мира — вызывается ТОЛЬКО действием игрока (пошаговость, как за столом).
    Возвращает {feed, address} для показа."""
    city, people, crof, cr2b, loc = _play()
    lv = _S.get("live")
    if not lv or lv["loc"] != loc or lv.get("who") != frozenset(_here(loc, crof)):
        _live_build(city, people, crof, cr2b, loc)
        lv = _S["live"]
    try:
        feed, address = _live_tick(people)
    except Exception:                                      # noqa: BLE001 — тик не роняет действие
        import logging
        logging.getLogger("aidnd").warning("live tick failed", exc_info=True)
        return {"feed": [], "address": []}
    return {"feed": feed, "address": address}


@router.post("/api/play/live")
async def live(request: Request):
    """Кнопка «ждать»: потратить время и дать миру ход. (Поллинга больше нет — мир пошаговый.)"""
    _play()
    t = _world_tick()
    return {**t, "gt": _gt(), "coins": _pc_coins(), "hp": _pc_hp()}


@router.post("/api/play/enter")
async def enter(request: Request):
    """Войти в здание у которого стоишь. Внутри — своё «осмотреться», карта блокируется."""
    city, people, crof, cr2b, loc = _play()
    bid = cr2b.get(loc)
    if not bid:
        return {"error": "тут не во что входить"}
    _S["inside"] = bid
    _S["room"] = None
    _gt_add(PB["give_min"])
    _pc_remember(f"вошёл в {_binfo(bid)['name']}", 0.25)
    t = _world_tick()
    return {**_scene_dict(city, people, crof, cr2b, loc), **t, "gt": _gt(), "coins": _pc_coins(),
            "hp": _pc_hp(), "city": _city_name()}


@router.post("/api/play/room")
async def go_room(request: Request):
    """Перейти в суб-помещение здания (или в зал, room=null). Гейты: public — свободно;
    staff — по доверию работника ИЛИ скрытности; locked — по ключу; hidden — уже раскрыто."""
    city, people, crof, cr2b, loc = _play()
    inside = _S.get("inside")
    if not inside:
        return {"error": "ты не внутри здания"}
    want = (await request.json()).get("room")
    out = {"narr": []}
    if not want:                                           # вернуться в общий зал
        _S["room"] = None
    else:
        room = next((r for r in _building_rooms(inside) if r["name"] == want), None)
        if not room:
            return {"error": "такого помещения тут нет"}
        acc = room["access"]
        if acc in ("staff",):                              # служебное — доверие работника или скрытно
            worker = next((people[pid] for pid in _here(loc, crof) if people[pid].work == inside), None)
            trust = worker.state.rel(PLAYER)["trust"] if worker else 0.0
            if trust < 0.3:
                roll = random.Random(f"sneakroom|{inside}|{want}|{_mt()}").randint(1, 20)
                total = roll + _PC_CAP.mod("dex")
                dc = PB["steal_dc_base"]
                out["dice"] = {"die": 20, "roll": roll, "mod": _PC_CAP.mod("dex"), "total": total,
                               "dc": dc, "ok": total >= dc, "label": "Скрытность (Dex) — пройти незаметно"}
                if total < dc:
                    out["narr"].append(f"«{want}» — не для чужих. На тебя косятся, пришлось отступить.")
                    return {**out, **_scene_dict(city, people, crof, cr2b, loc), "gt": _gt()}
        elif acc == "locked":                              # заперто — нужен ключ ЭТОГО здания
            bd = _store().get_building(_wid(), inside) or {}
            local = _tokens_ru(_binfo(inside)["name"]) | _tokens_ru(want)
            for cnt in (bd.get("data", {}).get("containers") or []):
                local |= _tokens_ru(cnt.get("name", ""))   # ключи хозяина ходят по его ёмкостям
            has_key = any(
                it and it["kind"] == "key" and any(
                    m["target"] == "special:opens" and (_tokens_ru(m.get("cond", "")) & local)
                    for m in it.get("mods", []))
                for it in (_store().get_item(r["item_id"])
                           for r in _store().inventory(_wid(), "pc")))
            if not has_key:
                out["narr"].append(f"«{want}» заперто — нужен ключ здешнего хозяина.")
                return {**out, **_scene_dict(city, people, crof, cr2b, loc), "gt": _gt()}
        _S["room"] = want
        out["narr"].append(f"Ты проходишь в: {want}.")
    _gt_add(PB["give_min"])
    return {**out, **_scene_dict(city, people, crof, cr2b, loc), "gt": _gt(), "coins": _pc_coins(),
            "hp": _pc_hp()}


@router.post("/api/play/exit")
async def exit_building(request: Request):
    city, people, crof, cr2b, loc = _play()
    _S["inside"] = None
    _gt_add(PB["give_min"])
    t = _world_tick()
    return {**_scene_dict(city, people, crof, cr2b, loc), **t, "gt": _gt(), "coins": _pc_coins(),
            "hp": _pc_hp(), "city": _city_name()}


@router.post("/api/play/surrender")
async def surrender(request: Request):
    """Сдаться страже: заплатить виру (розыск×тариф) → чист; нечем — ночь в холодной + всё серебро."""
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
        target = ((cur // 1440) + 1) * 1440 + PB["watch_jail_h"] * 60   # до утра следующего дня
        _gt_add(max(PB["step_min"], target - cur))
        narr = [f"Платить нечем. Ночь в холодной, из кошеля выгребают {got} зм. Утром выпускают."]
    _wanted_clear()
    _pc_remember("рассчитался со стражей за свои дела", 0.5)
    _apply_routine()
    return {**_scene_dict(city, people, crof, cr2b, loc), "narr": narr,
            "coins": _pc_coins(), "gt": _gt()}


@router.post("/api/play/watch_flee")
async def watch_flee(request: Request):
    """Бежать от стражи: Dex против ловкости стражника. Ушёл — розыск ↑, ты в другом конце города;
    попался — страж вяжет (бой)."""
    city, people, crof, cr2b, loc = _play()
    wc = _watch_check(people, crof, loc)
    if not wc:
        return {"error": "не от кого бежать"}
    guard = people[wc["guard"]]
    gdex = (guard.state.config.abilities.get("dex", 10) - 10) // 2
    roll = random.Random(f"wflee|{loc}|{_gt()}").randint(1, 20)
    total, dc = roll + _PC_CAP.mod("dex"), PB["watch_flee_dc"] + gdex
    dice = {"die": 20, "roll": roll, "mod": _PC_CAP.mod("dex"), "total": total, "dc": dc,
            "ok": total >= dc, "label": "Побег (Dex) от стражи"}
    if total >= dc:
        _wanted_add(1, "сбежал от стражи")                 # погоня усердствует
        nb = random.Random(f"wfleeto|{loc}|{_gt()}").choice(_S["kps"])
        _S["loc"], _S["inside"], _S["room"] = nb, None, None
        _gt_add(PB["step_min"] * 2)
        _apply_routine()
        return {**_scene_dict(city, people, crof, cr2b, nb), "dice": dice,
                "narr": ["Ты ныряешь в переулки и отрываешься. Но теперь ищут ещё усерднее."],
                "gt": _gt(), "coins": _pc_coins()}
    foe = _combatant_from_npc(wc["guard"], guard)
    foe.side = "foes"
    enc = Encounter([_pc_combatant()], [foe], seed=f"watchfight|{wc['guard']}|{_mt()}", w=9, h=7)
    _S["combat"] = {"enc": enc, "npc": wc["guard"], "loc": loc,
                    "head": {"name": f"Стража: {guard.name}", "sub": "бегство сорвалось"}}
    return {"dice": dice, "combat": True,
            "narr": [f"{guard.name} перехватывает тебя. Дерись или сдавайся."]}


def _spell_hit(t, dmg: dict, out: dict, tag: str) -> None:
    """Нанести урон-по-типу одному бойцу (резисты/иммунитеты бестиария), разбудить спящего."""
    n = roll_dice(dmg["dice"], random.Random(f"spelldmg|{_mt()}|{tag}"))
    if dmg["type"] in t.immune:
        n = 0
    elif dmg["type"] in t.resist:
        n //= 2
    t.hp -= n
    if n > 0 and t.status.pop("asleep", 0):
        out["narr"].append(f"{t.name} просыпается от удара.")
    if t.hp <= 0:
        t.alive = False
    fell = " — падает!" if not t.alive else f" [{t.hp}/{t.max_hp}]"
    out["narr"].append(f"{dmg['dice']} → {t.name}: {n} урона{fell}")


def _apply_spell(spec: dict, target, out: dict, people, crof, loc) -> None:
    """Механическое исполнение чистого круга: исцеление/явить/отпереть вне боя; урон (одиночный/AoE),
    статусы (bound/asleep/afraid) — в бою по грид-клеткам с резистами бестиария."""
    cb = _S.get("combat")
    if spec.get("heal"):
        before = _pc_hp()
        _pc_hp(spec["heal"])
        out["narr"].append(f"Круг струит свет в раны — +{_pc_hp() - before} hp.")
    if spec.get("reveal"):
        _S.setdefault("looked", {})[_look_key(loc, _S.get("inside"))] = 2
        out["narr"].append("Круг вспыхивает — округа проявляется до мелочей.")
        out["refresh"] = True
    if spec.get("unlock"):
        out["narr"].append("Незримый ключ поворачивается — что заперто, поддаётся.")

    enc = cb["enc"] if cb else None
    t = enc.units.get(target) if (enc and target) else None
    area = spec.get("area") or {}
    dmg = spec.get("damage")
    if dmg and enc:
        foes = [u for u in enc.units.values() if u.side == "foes" and not u.down()]
        if area.get("shape") in ("burst", "cloud") and t:   # AoE вокруг клетки цели
            r = area.get("radius", 1)
            hit = [u for u in foes if max(abs(u.x - t.x), abs(u.y - t.y)) <= r]
            out["narr"].append(f"{spec['elements'][0].capitalize()} накрывает {len(hit)} цел(и):")
            for u in hit:
                _spell_hit(u, dmg, out, u.id)
            out["combat_refresh"] = True
        elif area.get("shape") == "cone":                   # конус от героя к ближайшим врагам
            pc_u = enc.units.get("pc")
            length = area.get("length", 2)
            hit = [u for u in foes if pc_u and enc.dist(pc_u, u) <= length] if pc_u else foes[:3]
            out["narr"].append(f"{spec['elements'][0].capitalize()} веером бьёт {len(hit)} цел(и):")
            for u in hit:
                _spell_hit(u, dmg, out, u.id)
            out["combat_refresh"] = True
        elif t and t.side == "foes" and not t.down():        # одиночный снаряд
            out["narr"].append(f"{spec['elements'][0].capitalize()}:")
            _spell_hit(t, dmg, out, target)
            out["combat_refresh"] = True
        else:
            out["narr"].append("Заряд собран, но метать не в кого — цель не указана.")
    elif dmg:
        out["narr"].append("Заряд собран, но метать не в кого — врагов рядом нет.")

    st = spec.get("status")
    if st:
        kind, turns = st.get("kind", "bound"), st.get("turns", 1)
        if enc and t and t.side == "foes" and not t.down():
            t.status[kind] = max(t.status.get(kind, 0), turns)
            word = {"bound": "спутан", "asleep": "усыплён", "afraid": "объят ужасом"}.get(kind, kind)
            out["narr"].append(f"{t.name} {word} ({turns} р.).")
            out["combat_refresh"] = True
        else:
            out["narr"].append("Путы сплетены, но некого вязать (нужна цель в бою).")


_ELEM_DMG = {"огонь": "fire", "лёд": "cold", "яд": "poison",
             "свет": "radiant", "тьма": "necrotic", "камень": "bludgeoning"}


def _apply_wild(comp, reason: str, out: dict) -> None:
    """Дикий/сорванный круг (М-3): LLM выбирает исход из ОГРАНИЧЕННОГО меню — применяем механически.
    Меню безопасно (нельзя сломать мир): backfire | nothing | scorch | warp | boon."""
    cb = _S.get("combat")
    w = _inscriber().wild(comp, reason, bool(cb)) or {
        "effect": "backfire", "magnitude": 2, "element": "", "text": f"Круг рвётся вразнос — {reason}."}
    mag = max(1, min(3, int(w.get("magnitude") or 1)))
    eff = w.get("effect", "backfire")
    out["cast"]["wild"] = True
    out["cast"]["effect"] = eff
    out["narr"].append(w.get("text") or f"Круг идёт вразнос — {reason}.")
    if eff == "nothing":
        return
    if eff == "boon":
        before = _pc_hp()
        _pc_hp(2 * mag)
        out["narr"].append(f"Нежданная удача — раны затягиваются (+{_pc_hp() - before} hp).")
        return
    if eff == "warp":
        _gt_add(PB["act_min"])                             # искажение — странный сдвиг, без жёсткой механики
        out["refresh"] = True
        return
    if eff == "scorch" and cb:
        dt = _ELEM_DMG.get(w.get("element", ""), "fire")
        hit = 0
        for u in cb["enc"].units.values():
            if u.side == "foes" and not u.down():
                n = mag * 3
                if dt in u.immune:
                    n = 0
                elif dt in u.resist:
                    n //= 2
                u.hp -= n
                if u.hp <= 0:
                    u.alive = False
                hit += 1
        if hit:
            out["narr"].append(f"Выброс стихии хлещет по округе — задето {hit}.")
            out["combat_refresh"] = True
            return
    # backfire (и scorch, когда некого жечь) — отдача калечит чертящего
    _pc_hp(-2 * mag)
    out["narr"].append(f"Отдача калечит чертящего — {2 * mag} урона.")


_LAW_KEYS = ("damage", "area", "heal", "status", "reveal", "unlock", "range", "mana_cost", "difficulty")


def _inscribe_law(comp, spec: dict):
    """Роль А: вписать чистый круг в законы мира. Первый раз — LLM даёт имя+флейвор, кэш в гримуаре
    по хэшу состава; дальше имя стабильно. Возвращает (entry, fresh)."""
    h = circle_hash(comp)
    entry = _grimoire_get(h)
    if entry:
        return entry, False
    named = _inscriber().name_circle(comp, spec) or {}
    entry = {"hash": h, "comp": list(comp),
             "name": named.get("name") or ", ".join(comp),
             "flavor": named.get("flavor", ""), "sensory": named.get("sensory", ""),
             "spec": {k: spec[k] for k in _LAW_KEYS if k in spec},
             "first_gt": _gt(), "casts": 0}
    _grimoire_put(h, entry)
    return entry, True


def _taboo(people, crof, loc, out: dict) -> int:
    """Открытая боевая/дикая магия среди горожан = ведьмовство → розыск (М-4, лёгкая версия;
    отдельный орден/инквизиция — второй срез). В бою (логово вне города) свидетелей нет."""
    if _S.get("combat"):
        return 0
    wit = [w for w in _here(loc, crof) if people[w].role not in ("маг", "писец")]
    if not wit:
        return 0
    for w in wit:
        people[w].state.memory.add("видел(а): чужак колдовал прямо у всех на виду", _mt(), 0.6, about=[PLAYER])
        _npc_save(w)
    _wanted_add(PB["taboo_witness"] + min(2, len(wit)), "колдовал у всех на виду")
    out["narr"].append("Люди вокруг отшатываются и крестятся — ведьмовство не забудут.")
    return len(wit)


def _draw_rate() -> float:
    """Скорость таяния свечи (мана/сек) при черчении: базовая, мягче от Инт+Мдр (усталость учтена)."""
    cap = _pc_cap_eff()
    soft = 1 + PB["draw_intwis_k"] * (cap.mod("int") + cap.mod("wis"))
    return round(PB["draw_drain_per_s"] / max(0.4, soft), 3)


def _cast_cost(comp, spec, draw_ms, known: bool):
    """Сколько маны сожжёт круг. Известный из гримуара — мгновенно за долю сложности. Новый —
    утечка·секунды_черчения + суммарный вес глифов. Без draw_ms (старый клик-UI) — по сложности."""
    if known:
        return max(1, round(spec["difficulty"] * PB["known_cost_k"]))
    if draw_ms is None:                                    # legacy клик-ввод без таймера
        return spec["mana_cost"]
    g = magic_load()
    weights = sum(g["all"][c].get("weight", 1) for c in comp if c in g["all"])
    secs = max(0.0, float(draw_ms) / 1000.0)
    return max(1, math.ceil(_draw_rate() * secs + weights))


@router.post("/api/play/cast")
async def cast(request: Request):
    """Сотворить круг из глифов. Новый круг чертится в реальном времени (свеча тает: cost = утечка·сек +
    вес глифов; маны не хватило → выброс/осечка). Известный из гримуара (М1a) — мгновенно за фикс-долю.
    Чистый круг вписывается законом (М-3), дикий/осечка → непредсказуемый LLM-исход (М-3).
    Гейт: только выученные глифы (М-4); боевая магия на людях = ведьмовство → розыск."""
    city, people, crof, cr2b, loc = _play()
    body = await request.json()
    comp = [str(x) for x in (body.get("glyphs") or [])]
    target = body.get("target")
    known_g = set(_glyphs_known())
    locked = [c for c in comp if c in known_ids() and c not in known_g]
    if locked:
        g = magic_load()
        names = ", ".join(g["all"][c].get("ru", c) for c in locked)
        return {"cast": {"kind": "locked"}, "narr": [f"Ты не владеешь глифом: {names}. Выучи у наставника."],
                "mana": _mana(), "gt": _gt()}
    cls = classify(comp)
    out = {"narr": [], "cast": {"kind": cls["kind"]}}
    if cls["kind"] == "empty":
        return {**out, "narr": [f"Круг не сходится — {cls['reason']}."], "mana": _mana(), "gt": _gt()}
    spec = build_spec(comp)
    is_known = _grimoire_get(circle_hash(comp)) is not None   # круг уже вписан → мастерский каст
    mana_before = _mana()
    cost = _cast_cost(comp, spec, body.get("draw_ms"), is_known)
    if is_known and mana_before < cost:                    # мастерский круг не запустить без маны
        return {**out, "narr": [f"Маны мало: нужно {cost:g}, есть {mana_before:g}. Отдохни."],
                "mana": mana_before, "mana_cap": _mana_cap(), "gt": _gt()}
    guttered = (not is_known) and cost > mana_before       # свеча погасла посреди черчения — выброс
    spend = min(mana_before, cost)
    roll = random.Random(f"cast|{_mt()}|{'/'.join(sorted(comp))}").randint(1, 20)
    dc = PB["cast_skill_dc"] + spec["difficulty"] // 3
    total = roll + _pc_cap_eff().mod("int")
    misfire = (not is_known) and (cls["kind"] == "wild" or total < dc or guttered)
    _mana_spend(spend)
    _mana_grow(spend)                                      # выжигание растит потолок маны
    _fat_add(spend * (PB["burnout_fat_mult"] if guttered else 1))  # выброс истощает сильнее
    _gt_add(PB["act_min"])
    out["cast"].update({"mode": "known" if is_known else "drawn", "guttered": guttered,
                        "cost": round(spend, 1)})
    if not is_known:                                       # мастерский круг не бросает — идёт наверняка
        out["dice"] = {"die": 20, "roll": roll, "mod": _pc_cap_eff().mod("int"), "total": total,
                       "dc": dc, "ok": total >= dc, "label": "Черчение круга (Int)"}
    if misfire:                                            # дикая магия / осечка / выброс → LLM-хаос
        reason = ("свеча погасла — круг сорвался в руках" if guttered and cls["kind"] != "wild"
                  else cls["reason"] if cls["kind"] == "wild" else "рука дрогнула, круг сорвался")
        _apply_wild(comp, reason, out)
        _taboo(people, crof, loc, out)                     # дикий выброс на людях — ведьмовство
        _pc_remember(f"круг ушёл вразнос ({', '.join(comp)})", 0.4)
        _pc_save()
        res = {**out, "mana": _mana(), "mana_cap": _mana_cap(), "hp": _pc_hp(),
               "fatigue": _fatigue(), "gt": _gt()}
        if out.get("combat_refresh") and _S.get("combat"):
            res["combat"] = _S["combat"]["enc"].view()
        return res
    _apply_spell(spec, target, out, people, crof, loc)     # чистый круг — по спеку
    if spec.get("damage") or spec.get("status"):           # боевой круг на людях — ведьмовство
        _taboo(people, crof, loc, out)
    law, fresh = _inscribe_law(comp, spec)                 # вписать/подтвердить закон в гримуаре
    law["casts"] = law.get("casts", 0) + 1
    _grimoire_put(law["hash"], law)
    out["cast"]["name"] = law["name"]
    out["cast"]["fresh"] = fresh
    if fresh:
        head = f"✦ Новый закон вписан в гримуар: «{law['name']}»"
        if law.get("flavor"):
            head += f" — {law['flavor']}"
        out["narr"].insert(0, head)
        if law.get("sensory"):
            out["narr"].insert(1, law["sensory"])
    _pc_remember(f"сотворил «{law['name']}» ({', '.join(comp)})", 0.4)
    _pc_save()
    res = {**out, "mana": _mana(), "mana_cap": _mana_cap(), "hp": _pc_hp(),
           "fatigue": _fatigue(), "gt": _gt()}
    if out.get("combat_refresh") and _S.get("combat"):
        res["combat"] = _S["combat"]["enc"].view()
    return res


@router.get("/api/play/glyphs")
def glyphs_list():
    """Палитра магии: весь базис + пометка known (владеет игрок) vs заперто (учить у мага/писца)."""
    _play()
    g = magic_load()
    known = set(_glyphs_known())
    elems = [{**e, "known": e["id"] in known} for e in g["elements"].values()]
    glyphs = [{**s, "known": s["id"] in known} for s in g["glyphs"].values()]
    return {"elements": elems, "glyphs": glyphs, "known": sorted(known),
            "mana": _mana(), "mana_cap": _mana_cap(), "fatigue": _fatigue(),
            "draw": {"rate": _draw_rate(), "known_k": PB["known_cost_k"]}}   # клиент тает свечу в такт


def _teachable(role: str) -> set:
    """Что учит наставник: маг — стихии/формы/моды; писец — глаголы/моды (не огонь)."""
    g = magic_load()
    axes = {"маг": {"element", "form", "mod"}}.get(role, {"verb", "mod"})
    return {gid for gid, e in g["all"].items() if e.get("axis") in axes}


@router.post("/api/play/learn")
async def learn_glyph(request: Request):
    """Выучить глиф у наставника (маг в башне / писец). Гейт: симпатия ≥ порога; цена монетами по весу,
    при высокой симпатии — даром. Наставник должен быть здесь и уметь это преподать."""
    _city, people, crof, _cr2b, loc = _play()
    b = await request.json()
    gid, teacher = str(b.get("glyph") or ""), b.get("teacher")
    g = magic_load()
    if gid not in g["all"]:
        return {"error": "нет такого глифа"}
    if teacher not in people or teacher not in _here(loc, crof):
        return {"error": "наставника нет рядом"}
    p = people[teacher]
    if p.role not in TEACHER_ROLES:
        return {"error": f"{p.name} не учит магии"}
    if gid not in _teachable(p.role):
        kind = "стихиям и формам — ищи мага в башне" if p.role != "маг" else "глаголам письма — это к писцу"
        return {"error": f"{p.name} не обучает этому ({kind})"}
    if gid in _glyphs_known():
        return {"error": "ты уже владеешь этим глифом"}
    rel = p.state.relationships.get(PLAYER, {"affinity": 0.0})
    aff = rel.get("affinity", 0.0)
    if aff < PB["learn_aff_min"]:
        return {"error": f"{p.name} не станет тебя учить — сперва заслужи доверие"}
    weight = g["all"][gid].get("weight", 1)
    price = 0 if aff >= PB["learn_aff_free"] else PB["learn_base"] + PB["learn_per_weight"] * weight
    if price > _store().purse_get(_wid(), "pc"):
        return {"error": f"нужно {price} зм за урок — не хватает"}
    if price:
        _store().purse_add(_wid(), "pc", -price)
        _store().purse_add(_wid(), teacher, price)
    _glyph_learn(gid)
    _gt_add(PB["talk_min"])
    ru = g["all"][gid].get("ru", gid)
    p.state.memory.add(f"обучил игрока глифу «{ru}»", _mt(), 0.4, about=[PLAYER])
    _pc_remember(f"выучил глиф «{ru}» у {p.name}", 0.5, about=[teacher])
    _npc_save(teacher)
    _pc_save()
    line = _voice(p, rel, "reply",
                  f"(Ты обучил игрока чертить глиф «{ru}»{' за ' + str(price) + ' зм' if price else ' безвозмездно, по дружбе'}. "
                  f"Скажи что-нибудь наставническое, по своему характеру.)")
    return {"learned": gid, "ru": ru, "price": price, "line": line,
            "coins": _store().purse_get(_wid(), "pc"), "known": sorted(_glyphs_known()), "gt": _gt()}


@router.get("/api/play/teachers")
def teachers_here():
    """Кто на локации способен учить магии (для UI: подсветить наставника)."""
    _city, people, crof, _cr2b, loc = _play()
    out = []
    for pid in _here(loc, crof):
        p = people[pid]
        if p.role in TEACHER_ROLES and (pid in _met() or p.work):
            out.append({"id": pid, "name": p.name, "role": p.role,
                        "teaches": sorted(_teachable(p.role) - set(_glyphs_known()))})
    return {"teachers": out}


@router.get("/api/play/grimoire")
def grimoire_list():
    """Вписанные в мир законы (гримуар игрока): имя, состав, флейвор, число сотворений."""
    _play()
    laws = _grimoire_list()
    return {"laws": [{"name": e.get("name"), "comp": e.get("comp", []), "flavor": e.get("flavor", ""),
                      "sensory": e.get("sensory", ""), "casts": e.get("casts", 0)} for e in laws],
            "count": len(laws)}


@router.post("/api/play/look")
async def look(request: Request):
    """Осмотреться: бросок d20+Wis против DC — снимает туман (людей/ёмкости различаешь)."""
    city, people, crof, cr2b, loc = _play()
    inside = _S.get("inside")
    key = _look_key(loc, inside)
    n = int(_store().flag_get(_wid(), f"lookn|{key}") or 0) + 1
    _store().flag_set(_wid(), f"lookn|{key}", str(n))
    roll = random.Random(f"look|{key}|{n}").randint(1, 20)
    mod = _PC_CAP.mod("wis")
    total = roll + mod
    lvl = 2 if total >= PB["look_good"] else 1 if total >= PB["look_dc"] else 0
    prev = _looked_level(loc, inside)
    _S.setdefault("looked", {})[key] = max(prev, lvl, 1 if total >= PB["look_dc"] else prev)
    _gt_add(PB["give_min"])
    sc = _scene_dict(city, people, crof, cr2b, loc)
    dice = {"die": 20, "roll": roll, "mod": mod, "total": total, "dc": PB["look_dc"],
            "ok": total >= PB["look_dc"], "label": "Внимательность (Wis)"}
    narr = ("Ты оглядываешься, но взгляд скользит мимо: толком ничего не разобрал." if total < PB["look_dc"]
            else "Ты внимательно оглядываешься по сторонам." if total < PB["look_good"]
            else "От твоего взгляда мало что ускользает.")
    return {**sc, "dice": dice, "narr": [narr], "gt": _gt(), "coins": _pc_coins(), "hp": _pc_hp()}


@router.get("/api/play/board")
def board():
    _play()
    gb = _guild_bid()
    joined = None
    if not _pc_badge() and not _store().flag_get(_wid(), "guild_mark|pc"):
        _mint_badge(0)                                     # первое обращение — приняли, вот Медь
        joined = "Тебя приняли в гильдию. Вот жетон приключенца (Медь)."
    return {"guild": (_binfo(gb)["name"] if gb else None), "jobs": _guild_board(),
            "lairs": _lairs(), "status": _guild_status(), "joined": joined}


@router.post("/api/play/guild_redeem")
async def guild_redeem(request: Request):
    """Искупить чёрную метку гильдии штрафом (и вернуть себе Медь-жетон, если его нет)."""
    _play()
    if not _store().flag_get(_wid(), "guild_mark|pc"):
        return {"error": "метки нет"}
    fine = PB["guild_mark_fine"]
    if _pc_coins() < fine:
        return {"error": f"нужно {fine} зм, чтобы загладить вину"}
    _store().purse_add(_wid(), "pc", -fine)
    _store().purse_add(_wid(), "guild", fine)
    _store().flag_set(_wid(), "guild_mark|pc", "")         # снять метку
    if not _pc_badge():
        _mint_badge(0)
    _pc_remember("загладил вину перед гильдией штрафом", 0.4)
    return {"redeemed": True, "coins": _pc_coins(), "status": _guild_status(),
            "narr": [f"Ты платишь гильдии {fine} зм. Метку снимают, жетон (Медь) снова у тебя."]}


@router.post("/api/play/board_take")
async def board_take(request: Request):
    _play()
    jid = (await request.json()).get("id")
    job = next((j for j in _guild_board() if j["id"] == jid), None)
    if not job:
        return {"error": "этого заказа уже нет"}
    gate = _guild_gate(job["cr"])                          # жетон · ранг по чину · проверка лжи
    if gate and gate.get("error"):
        return {"error": gate["error"], "dice": gate.get("dice"), "status": _guild_status()}
    gb = _guild_bid()
    _store().save_contract(_wid(), jid, "active", {
        "giver": "guild", "giver_name": _binfo(gb)["name"] if gb else "Гильдия",
        "kind": "clear", "want": None, "where": job["name"], "target": job["lair"],
        "target_name": job["name"], "reward": job["reward"], "reward_item": None,
        "reward_name": None, "pitch": "", "why": "доска гильдии"})
    _pc_remember(f"взял с доски гильдии заказ: {job['name']} (CR {job['cr']}) за {job['reward']} зм", 0.5)
    stolen = bool(gate and gate.get("ok_stolen"))          # прошёл по чужому жетону — заслуга не в счёт
    return {"taken": True, "dice": (gate.get("dice") if gate else None),
            "narr": (["Распорядитель косится на жетон, но пропускает."] if stolen else [])}


@router.post("/api/play/delve")
async def delve(request: Request):
    """Отправиться к логову и вступить в бой (время на дорогу честное)."""
    _play()
    lid = (await request.json()).get("lair")
    l = next((x for x in _lairs() if x["id"] == lid), None)
    if not l:
        return {"error": "нет такого места"}
    if l["cleared"]:
        return {"error": "там уже пусто — зачищено"}
    if _pc_hp() <= 1:
        return {"error": "ты еле стоишь — сперва отлежись"}
    taken = any(c.get("target") == lid for c in _store().contracts(_wid(), "active"))
    if not taken:                                          # не по заказу — гильдия гейтит на месте
        gate = _guild_gate(l["cr"])
        if gate and gate.get("error"):
            return {"error": gate["error"], "dice": gate.get("dice")}
    _gt_add(PB["lair_travel_min"])
    lseed = lid.split(":")[1]
    wv = dungeon.waves(l["cr"] + 0.01, l["env"], seed=lseed, n=PB["dungeon_waves"])
    obs = dungeon.obstacles(12, 9, l["env"], seed=lseed)   # процедурная раскладка логова
    enc = Encounter([_pc_combatant()], wv[0], seed=f"fight|{lid}|{_mt()}", obstacles=obs, waves=wv[1:])
    _S["combat"] = {"enc": enc, "lair": l,
                    "head": {"name": l["name"], "sub": f"{l['env']} · CR {l['cr']} · накатов {len(wv)}"}}
    guard = 0
    while enc.status() == "active" and guard < 50:          # докрутить ИИ до хода игрока
        c0 = enc.current()
        if c0 is None or c0.id == "pc":
            break
        enc.ai_turn(c0)
        guard += 1
    _pc_remember(f"пришёл к месту: {l['name']}", 0.4)
    if enc.status() != "active":
        return {"combat": enc.view(), "over": _combat_wrapup(enc, _S["combat"]), "lair": l, "gt": _gt()}
    pc_u = enc.units.get("pc")
    if pc_u:
        _pc_hp(set_to=max(0, pc_u.hp))
    return {"combat": enc.view(), "lair": l, "gt": _gt(), "hp": _pc_hp()}
