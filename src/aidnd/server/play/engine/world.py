"""Игровой контур — МИР И ОРКЕСТРАЦИЯ: генерация, сцена, движение, диалог, действие, живая локация + HTTP-эндпоинты.

Слой mechanics/ (см. docs/loop.md).
"""

from __future__ import annotations

import json
import random

from fastapi import Request

from aidnd import society
from aidnd.citygraph import CityParams, generate, visual
from aidnd.citygraph.model import NodeKind
from aidnd.inference import LLMBadOutput, LLMUnavailable
from aidnd.mind import Body, NpcConfig, NpcState, advance_agendas
from aidnd.mind import Item as MItem
from aidnd.mind import World as MWorld
from aidnd.mind import perceive as mind_perceive
from aidnd.mind.llm_agent import apply_actions, decide_hybrid, plan_agenda
from aidnd.mind.tick import _decay_emotion, _decay_needs
from aidnd.play.population import Townsperson
from aidnd.server.play.engine.core import (
    _scene_descriptors,
    _COLORS,
    _PHASE_RU,
    _S,
    PB,
    PLAYER,
    _binfo,
    _city_name,
    _display,
    _emo,
    _fatigue,
    _gt,
    _gt_add,
    _here,
    _in_room,
    _mana,
    _mana_cap,
    _mark_seen,
    _met,
    _model,
    _mt,
    _npc_save,
    _pc,
    _pc_hp,
    _pc_name,
    _pc_remember,
    _pc_save,
    _phase,
    _pool,
    _portrait_url,
    _role_at,
    _role_for_building,
    _spurns,
    _store,
    _tokens_ru,
    _wanted,
    _wanted_add,
    _wid,
    router,
)
from aidnd.server.play.engine.worldsim import routine_step
from aidnd.server.play.mechanics.combat import (
    _guild_bid,
    _guild_board,
    _guild_status,
    _mint_badge,
    _npc_delves,
    _pc_badge,
)
from aidnd.server.play.mechanics.contracts import (
    _board_ads,
    _board_npc_fulfill,
    _board_publish,
    _ct_cur,
    _ct_steps,
    _step_desc,
)
from aidnd.server.play.mechanics.items import (
    _materialize_npc,
    _merchant_restock,
    _pc_coins,
    _seed_item_pool,
)


def _world_events() -> None:
    """Суточные события пассивного мира (раз в день, утром): розыск стынет, смелые уходят по
    заказам гильдии, горожане правят столб объявлений, случайный караван везёт товар. Каждое — в
    своём try: сбой одного не роняет мир."""
    if _wanted() > 0:  # розыск остывает — память не вечна
        _wanted_add(-PB["wanted_decay"])
    try:
        from aidnd.server.play.mechanics.deals import _deal_jobs

        news = _npc_delves() + _deal_jobs()
        if news:
            _S["guild_news"] = (_S.get("guild_news") or [])[-2:] + news
    except Exception:  # noqa: BLE001 — вылазка не роняет мир
        pass
    try:
        bn = _board_npc_fulfill() + _board_publish()
        if bn:
            _S["board_news"] = (_S.get("board_news") or [])[-3:] + bn
    except Exception:  # noqa: BLE001 — доска не роняет мир
        pass
    try:
        if random.Random(f"caravan|{_gt() // 1440}|{_wid()}").random() < PB["caravan_chance"]:
            _merchant_restock(f"caravan|{_gt() // 1440}")
    except Exception:  # noqa: BLE001
        pass


def _apply_routine() -> None:
    """Синхронизировать пассивный мир с текущим игровым временем: идемпотентно, дёшево — раз в фазу
    суток (ключ фаза+день). Рутина ВСЕХ жителей строится из НУЖД/характера/времени (society, через
    worldsim.routine_step), а не из хардкода ролей. На новой заре — суточные события."""
    key = (_gt() // 30, _gt() // 1440)               # шаг рутины: каждые 30 игровых минут
    if _S.get("routine_key") == key or not _S.get("people"):
        return
    _S["routine_key"] = key
    mkey = (_phase(), _gt() // 1440)                 # суточные события — раз на утро
    if mkey[0] == "morning" and _S.get("events_key") != mkey:
        _S["events_key"] = mkey
        _world_events()
    routine_step(_S["people"], _S["crof"])


_TIE_ROLES = {
    "головорез": "головорез",
    "шайк": "головорез",
    "стражн": "стражник",
    "лавочн": "лавочник",
    "куп": "лавочник",
    "трактир": "трактирщик",
    "жрец": "жрец",
    "знахар": "знахарка",
    "кузнец": "кузнец",
    "мельник": "мельник",
    "бард": "бард",
    "бродя": "бродяга",
    "сапожн": "сапожник",
    "дубильщ": "дубильщик",
    "стар": "жрец",
}


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
            continue  # уже вязан (в т.ч. восстановлен из npc_state)
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
            if hostile:  # настоящая вражда — обоюдно негатив
                ar["fear"] = max(ar["fear"], 0.3)
                ar["affinity"] = min(ar["affinity"], -0.2)
                br["affinity"] = min(br["affinity"], -0.1)
            elif debt:  # долг — обязательство, НЕ ненависть
                ar["fear"] = max(ar["fear"], 0.2)  # должник слегка опасается кредитора
            elif fear:  # страх без вражды — симпатия нейтральна
                ar["fear"] = max(ar["fear"], 0.35)
            else:  # доброе знакомство/родство
                ar["affinity"] = max(ar["affinity"], 0.4)
                ar["trust"] = max(ar["trust"], 0.3)
                br["affinity"] = max(br["affinity"], 0.3)
            st.memory.add(f"{tie} — это про {o.name}", _mt(), 0.5, kind="fact", about=[oid])
            o.state.memory.add(
                f"{p.name}: {tie[:90]} — нас связывает", _mt(), 0.4, kind="fact", about=[pid]
            )


def _person_from_row(row: dict, home: int, work: str | None) -> Townsperson:
    """Готовый NPC из банка → Townsperson с мозгом (mind) + богатой персоной/портретами."""
    mech = row.get("mech") or {}
    cfg = NpcConfig(
        id=row["id"],
        name=row["name"],
        role=row["role"],
        traits=mech.get("traits") or {},
        abilities=mech.get("abilities") or {},
    )
    st = NpcState.from_config(cfg)
    r = random.Random(row["id"])  # лёгкий фон нужд, детерминированно
    for n in st.needs:
        st.needs[n] = round(r.uniform(0.1, 0.35), 2)
    saved = _store().get_npc_state(_wid(), row["id"])  # прожитое переживает рестарт
    if saved:
        st.relationships = saved.get("relationships") or {}
        st.needs.update(saved.get("needs") or {})
        for m in saved.get("memory") or []:
            mm = st.memory.add(
                m["text"],
                m["t"],
                m.get("importance", 0.3),
                kind=m.get("kind", "observation"),
                about=m.get("about") or [],
            )
            mm.last_access = m.get("last_access", m["t"])
    tp = Townsperson(
        id=row["id"],
        name=row["name"],
        role=row["role"],
        home=home,
        work=work,
        charisma=row["charisma"],
        appearance=row["appearance"],
        state=st,
        persona=row.get("persona"),
        portraits=row.get("portraits") or {},
    )
    if work:  # владелец здания → ключи от его закрытых ёмкостей
        tp.keys = _building_keys(work)
    return tp


def _building_keys(bid: str) -> list:
    """Ключи-открывашки от LOCKED-ёмкостей здания (для владельца)."""
    bd = _store().get_building(_wid(), bid)
    if not bd:
        return []
    return [
        {"name": c["key"]["name"], "opens": c["name"], "where": c.get("where", "")}
        for c in (bd["data"].get("containers") or [])
        if c.get("access") == "locked" and c.get("key")
    ]


def _building_rooms(bid: str) -> list:
    """Суб-помещения здания (мини-граф): name/kind/access/hidden (скрытое видно лишь по зоркому осмотру)."""
    bd = _store().get_building(_wid(), bid)
    if not bd:
        return []
    return [
        {"name": s["name"], "kind": s.get("kind", "backroom"), "access": s.get("access", "public")}
        for s in (bd["data"].get("sub_rooms") or [])
    ]


def _building_containers(bid: str, room: str | None = None) -> list:
    """Ёмкости ТЕКУЩЕГО помещения (без содержимого — вскрывается взаимодействием)."""
    bd = _store().get_building(_wid(), bid)
    if not bd:
        return []
    rooms = bd["data"].get("sub_rooms") or []
    return [
        {
            "name": c["name"],
            "kind": c["kind"],
            "where": c.get("where", ""),
            "locked": c.get("access") == "locked",
        }
        for c in (bd["data"].get("containers") or [])
        if _in_room(c.get("where", ""), room, rooms)
    ]


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
        h = hint.split()[0].lower()  # «Храм удачи» → храм
        for r in rows:  # сперва по типу, потом любой
            if r["id"] not in used and h in r["btype"].lower():
                used.add(r["id"])
                return r
        for r in rows:
            if r["id"] not in used:
                used.add(r["id"])
                return r
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
    Пустой банк = сломанная поставка данных → жёсткая ошибка (мир без персон не строим)."""
    store = _store()
    if _pool().people_count() == 0:
        raise RuntimeError("банк NPC (worlds.db:people) пуст — мир не построить; проверь поставку пулов")
    people, spot = {}, {}
    placed = {pl["npc_id"]: pl for pl in store.placements_for(_wid())}
    if placed and not all(
        pl["node"] in city._xy and pl["home"] in city._xy  # noqa: SLF001
        for pl in placed.values()
    ):
        store.clear_placements(_wid())  # граф города изменился — узлы протухли
        placed = {}  # пере-размещаем заново (память NPC цела)
    if placed:  # уже наполнен — восстановить тех же людей
        dead = {k.split("|", 1)[1] for k in store.flags_prefix(_wid(), "dead|")}  # 1 запрос, не N
        by_id = {r["id"]: r for r in _pool().list_people(limit=100000)}  # 1 запрос, не N
        for pid, pl in placed.items():
            if pid in dead:
                continue  # мёртвые не возвращаются
            row = by_id.get(pid)
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

    for bid, kb in sorted(city.key_buildings.items()):  # работники — по роли из типа здания
        want = _role_for_building(bid)
        cand = [r for r in by_role.get(want, []) if r["id"] not in used] or [
            r for r in rows if r["id"] not in used
        ]
        for row in cand[:2]:  # хозяин + подмастерье
            place(row, kb.node, bid, home=next(hi, kb.node))
    for row in rows:  # ВЕСЬ остальной пул — по домам города
        if row["id"] not in used:
            h = next(hi, None) or rng.choice(houses)
            place(row, h, None, home=h)
    return people, spot


def _play():
    if _S["city"] is None:
        params = CityParams(seed=_S["seed"], key_buildings=12, river=True, walls=True, segment=16)
        city = generate(params)
        _assign_key_buildings(city)  # мир юзера: здания из ПУЛА, без LLM
        _seed_item_pool()  # пул предметов мира (сид-набор, данные)
        vis = visual(params, interactive=True)  # богатый визуал + кликабельные дома
        xy = {n.id: (n.x, n.y) for n in city.nodes()}
        keynode = {
            bid: kb.node for bid, kb in city.key_buildings.items()
        }  # здание → БЛИЖАЙШАЯ точка (дверь)
        kps = city.key_points()
        people, spot = _fill_from_pool(city, keynode, kps)  # только банк; пустой банк = ошибка
        n2b = {}  # узел-точка → здание (ключевые прежде домов)
        for bid, kb in city.key_buildings.items():
            n2b.setdefault(kb.node, bid)
        for hid, ho in city.houses.items():  # жилые дома тоже входимы (фактшит из пула)
            n2b.setdefault(ho.node, hid)
        start = (
            next(
                (keynode.get(p.work) for p in people.values() if p.role == "трактирщик" and p.work),
                None,
            )
            or kps[0]
        )
        _weave_ties(people)  # связи персон → реальные люди пула
        row = _store().get_pc(_wid()) or {}  # позиция игрока ПЕРЕЖИВАЕТ рестарт/деплой
        saved_loc = row.get("loc")
        if saved_loc in xy:
            start = saved_loc
        _S.update(
            city=city,
            people=people,
            crof=spot,
            cr2b=n2b,
            loc=start,
            geom=_build_geom(city, xy, n2b, vis),
            keynode=keynode,
            kps=kps,
        )
        if saved_loc in xy and row.get("inside") in n2b.values():
            _S["inside"], _S["room"] = row["inside"], row.get("room")
            _S["zone"] = row.get("zone")             # и место в зале — тоже позиция
    _apply_routine()  # споты = f(время): распорядок дня
    return _S["city"], _S["people"], _S["crof"], _S["cr2b"], _S["loc"]


def _build_geom(city, xy, n2b, vis) -> dict:
    """Лёгкий интерактивный слой поверх богатого визуала: система координат — холст рендера 0 0 W H.
    Дома/улицы/река/стены рисует сам SVG (vis['inner']); клик по дому → его БЛИЖАЙШАЯ точка дороги
    (h2n = h.node, НЕ перекрёсток). Метки зданий подписываем поверх; _xy — узел→xy для маршрута."""
    h2n = {h.id: h.node for h in city.houses.values()}
    road = (NodeKind.CROSSROAD, NodeKind.POINT, NodeKind.BRIDGE, NodeKind.GATE)
    points = [
        {
            "id": n,
            "x": round(xy[n][0], 1),
            "y": round(xy[n][1], 1),
        }  # ВСЕ узлы дорог (не только перекрёстки)
        for n in xy
        if city.node_kind(n) in road
    ]
    keys = []
    for bid, kb in sorted(city.key_buildings.items()):
        keys.append(
            {
                "node": kb.node,
                "x": round(kb.x, 1),
                "y": round(kb.y, 1),
                "label": _binfo(bid)["label"],
                "bid": bid,
            }
        )
    cx, cy = vis["W"] / 2, vis["H"] / 2  # ДОСКА-СТОЛБ: перекрёсток ближе к центру
    cross = [n for n in xy if city.node_kind(n) == NodeKind.CROSSROAD]
    plaza = min(cross, key=lambda n: (xy[n][0] - cx) ** 2 + (xy[n][1] - cy) ** 2) if cross else None
    if plaza is not None:
        keys.append(
            {
                "node": plaza,
                "x": round(xy[plaza][0], 1),
                "y": round(xy[plaza][1], 1),
                "label": "Доска",
                "bid": "board:plaza",
            }
        )
    return {
        "viewBox": [0, 0, vis["W"], vis["H"]],
        "svg": vis["inner"],
        "h2n": h2n,
        "points": points,
        "keys": keys,
        "plaza": plaza,
        "_xy": {n: [round(xy[n][0], 1), round(xy[n][1], 1)] for n in xy},
    }


def _look_key(loc, inside) -> str:
    return f"{loc}|{inside or 'out'}"


def _looked_level(loc, inside) -> int:
    """0 = не осматривался (туман: людей/ёмкостей не различаешь), 1 = осмотрелся, 2 = зоркий бросок."""
    return int((_S.setdefault("looked", {})).get(_look_key(loc, inside), 0))


def _scene_dict(city, people, crof, cr2b, loc):
    role = _role_at(loc, people, crof, cr2b)
    bid = cr2b.get(loc)
    inside = _S.get("inside")
    if inside and inside != bid:  # отошёл от здания — значит, вышел
        inside = _S["inside"] = None
        _S["room"] = None
    _mark_seen(bid)  # пришёл — узнал место
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
    here = here[: PB["here_show_cap"]]
    vis_here = here if lvl >= 1 else []  # туман: людей различаешь, лишь осмотревшись
    room = _S.get("room") if inside else None
    rooms = []
    if inside:
        for r in _building_rooms(inside):  # скрытые видны лишь по зоркому осмотру (lvl 2)
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
        "location": {
            "name": name,
            "kind": kind,
            "desc": (
                "Обычное место фронтирного городка — идёт своя жизнь."
                if role
                else "Мимо спешат редкие прохожие; в лужах дрожит свет окон."
            ),
            "containers": (_building_containers(inside, room) if (inside and lvl >= 1) else []),
        },
        "dungeon": ({"name": (_S.get("dungeon") or {}).get("d", {}).get("name"),
                     "room": (_S.get("dungeon") or {}).get("room")}
                    if _S.get("dungeon") else None),
        "ambient": {
            "time": _PHASE_RU[_phase()],
            "weather": "дождь",
            "mood": "оживлённо" if len(here) > 2 else "тихо",
            "event": (
                "Ты ещё не осмотрелся здесь."
                if lvl == 0 and here
                else "Народ занят своими делами."
                if here
                else "Пусто; лишь ветер гуляет меж домов."
            ),
        },
        "here": [
            {
                "id": pid,
                "name": _display(pid, people),  # незнакомец — дескриптором, имя после знакомства
                "role": (
                    people[pid].role if (pid in _met() or people[pid].work) else "кто-то из горожан"
                ),
                "init": _display(pid, people)[0].upper(),
                "color": _COLORS[i % len(_COLORS)],
                "portrait": _portrait_url(people[pid], _emo(people[pid].state)),
            }
            for i, pid in enumerate(vis_here)
        ],
    }
    if bid and bid == _guild_bid():  # в гильдии — доска, ранг, приём новичка
        d.setdefault("narr", [])
        if not _pc_badge() and not _store().flag_get(_wid(), "guild_mark|pc"):
            _mint_badge(0)
            d["narr"].append("Тебя приняли в гильдию. Вот жетон приключенца (Медь).")
        d["guild_board"], d["guild_news"] = _guild_board(), (_S.get("guild_news") or [])
        d["guild_status"] = _guild_status()
    if plaza is not None and loc == plaza and not inside:  # у столба — объявления горожан
        d["board_ads"] = _board_ads()
        d["board_news"] = _S.get("board_news") or []
    wc = _watch_check(people, crof, loc)  # стража при высоком розыске
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
    return {
        "guard": guard,
        "name": people[guard].name,
        "wanted": _wanted(),
        "crimes": ", ".join(crimes[-2:]),
        "fine": _wanted() * PB["watch_fine_per_pt"],
    }


_VOICE = {
    "gruff": "грубовато",
    "warm": "тепло",
    "clipped": "сухо и коротко",
    "florid": "витиевато",
    "meek": "робко",
    "booming": "громко, зычно",
}
_STANCE = {
    "warm": "дружелюбно",
    "neutral": "нейтрально",
    "wary": "настороженно",
    "dour": "хмуро",
    "greedy": "с расчётом на выгоду",
    "hostile": "враждебно",
}


def _voice(p, rel, kind, player_text=None) -> str:
    mgr = _model()
    per = getattr(p, "persona", None) or {}
    bits = [f"Ты — {p.name}, {p.role} на фронтире (тёмное фэнтези)."]
    if per:  # богатая персона из пула
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
            bits.append(
                f"У тебя есть тайна (НЕ выдавай без веской причины): {per['secret'].get('what', '')}."
            )
    if _spurns(p):  # обида/гнев ПЕРЕВЕШИВАЮТ радушие персоны
        bits.append(
            "Ты ЗОЛ на этого человека (вспомни, почему) — никакого радушия: "
            "холод, резкость или презрение, по твоему характеру."
        )
    here_name = _binfo(_S.get("inside"))["name"] if _S.get("inside") else "улица города"
    bits.append(
        f"МЕСТО: город называется «{_city_name()}», вы сейчас — {here_name}. "
        "КАНОН: о людях и местах ЭТОГО города говори только то, что есть в памяти и справке — "
        "здешних имён и заведений не выдумывай (и город зови ТОЛЬКО его настоящим именем). "
        "Вымысел допустим лишь о дальних краях и былом, и подавай его как слух."
    )
    bits.append(
        "СОБЕСЕДНИК — чужак-путник. Его внешности, одежды и имени ты НЕ ЗНАЕШЬ, пока он сам "
        "не показал/назвал — НЕ приписывай ему одежд, черт и званий (не путай его с другими "
        "посетителями из памяти)."
    )
    lv = _S.get("live") or {}
    just = (lv.get("last") or {}).get(p.id)
    if just and just != "—":
        bits.append(f"Только что ты: {just}.")
    mems = p.state.memory.recall(player_text or "разговор с чужаком-игроком", now=_mt(), k=5)
    mine = [m for m in mems if PLAYER in (m.about or [])]
    other = [m for m in mems if PLAYER not in (m.about or [])]
    if mine:  # непрерывность: NPC помнит ИМЕННО вас
        bits.append("ТЫ ПОМНИШЬ О СОБЕСЕДНИКЕ: " + "; ".join(m.text for m in mine) + ".")
    if other:  # прочее — фон, НЕ про собеседника
        bits.append(
            "ПРОЧЕЕ ИЗ ПАМЯТИ (про ДРУГИХ людей, НЕ про собеседника — не смешивай): "
            + "; ".join(m.text for m in other)
            + "."
        )
    if player_text:  # вопрос о мире → справка сразу (не выдумывать)
        info = _world_lookup(player_text, _S.get("loc"))
        if "не скажу" not in info:
            bits.append(
                f"СПРАВКА МИРА (это истина — придерживайся её, имена и места не выдумывай): {info}."
            )
    bits.append(
        f"Симпатия к собеседнику {rel.get('affinity', 0):.2f} (низкая — суше/настороже, высокая — теплее). "
        "Отвечай В ХАРАКТЕРЕ, живой разговорной речью, 1-2 фразы, без ремарок-описаний. "
        "Помнишь собеседника — покажи это естественно, не пересказывай память дословно. "
        'ФОРМАТ — строго JSON: {"say": "<реплика>", "player_tone": '
        '"friendly|neutral|rude|threat"} (player_tone — как звучали слова СОБЕСЕДНИКА к тебе). '
        "Если для ответа НУЖЕН факт о городе или людях (где что находится, кто есть кто) — "
        'верни СТРОГО JSON {"ask": "<короткий вопрос>"} вместо реплики: получишь справку и ответишь.'
    )
    acquainted = any(PLAYER in (m.about or []) for m in p.state.memory.items)
    user = (
        (
            "К тебе снова подошёл тот самый человек, которого ты помнишь, — поприветствуй его "
            "КАК ЗНАКОМОГО, опираясь на то, что помнишь."
            if acquainted
            else "К тебе подошёл незнакомец и заговорил — брось первую реплику."
        )
        if kind == "greet"
        else f"Он говорит: «{player_text}». Ответь."
    )
    msgs = [{"role": "system", "content": " ".join(bits)}, {"role": "user", "content": user}]
    resp = mgr.call("narrator", msgs, options={"temperature": 0.85})
    content = (resp.get("content") if resp else "").strip()

    def _parse(c):
        i, j = c.find("{"), c.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(c[i : j + 1])
            except (json.JSONDecodeError, ValueError):
                return None
        return None

    d = _parse(content)
    if d and d.get("ask"):  # тулкол ask: справка мира → второй заход
        info = _world_lookup(str(d["ask"]), _S.get("loc"))
        msgs += [
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": f"СПРАВКА МИРА: {info}. Теперь ответь собеседнику (тот же JSON-формат).",
            },
        ]
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
    out = {
        **_scene_dict(city, people, crof, cr2b, loc),
        "gt": _gt(),
        "coins": _pc_coins(),
        "hp": _pc_hp(),
        "max_hp": PB["pc_max_hp"],
        "city": _city_name(),
        "hero": _pc_name(),
        "mana": _mana(),
        "mana_cap": _mana_cap(),
        "fatigue": _fatigue(),
    }
    return out  # доска/ранг гильдии — из _scene_dict


# --------------------------------------------- КРАФТ / ПРОЧНОСТЬ (срез 2) - #


# ----------------------------------------------- ТОРГОВЛЯ И КРАЖА (срез 2) - #


@router.post("/api/play/ad_take")
async def ad_take(request: Request):
    _play()
    aid = (await request.json()).get("id")
    ct = next((c for c in _store().contracts(_wid(), "board") if c["id"] == aid), None)
    if not ct:
        return {"error": "этого объявления уже нет"}
    _store().save_contract(
        _wid(), aid, "active", {k: v for k, v in ct.items() if k not in ("id", "status")}
    )
    _pc_remember(f"взял с городской доски: {_step_desc(_ct_cur(ct))}", 0.4)
    return {"taken": True}


@router.post("/api/play/contract_accept")
async def contract_accept(request: Request):
    cid = (await request.json()).get("id")
    ct = next((c for c in _store().contracts(_wid(), "offered") if c["id"] == cid), None)
    if not ct:
        return {"error": "уговора нет"}
    _store().save_contract(
        _wid(), cid, "active", {k: v for k, v in ct.items() if k not in ("id", "status")}
    )
    note = None
    if ct.get("kind") == "deliver" and ct.get("deliver_item"):  # посылку вручают сразу
        _store().inv_move(_wid(), ct["deliver_item"], "pc")
        note = f"«{ct['want']}» ложится в твою сумку — доставь по адресу."
    _pc_remember(
        f"взялся за дело для {ct['giver_name']}: {ct.get('kind')} — "
        f"{ct.get('want') or ct.get('target_name')} ({ct['where']})",
        0.6,
        about=[ct["giver"]],
    )
    return {"accepted": True, "note": note}


@router.get("/api/play/contracts")
def contracts_list():
    _play()
    active = []
    for ct in _store().contracts(_wid(), "active"):
        steps = _ct_steps(ct)
        if len(steps) > 1:  # многоэтапный — показать прогресс и текущий шаг
            cur = _ct_cur(ct)
            ct = {
                **ct,
                "step_n": ct.get("step", 0) + 1,
                "step_total": len(steps),
                "kind": cur.get("kind"),
                "want": cur.get("want"),
                "target_name": cur.get("target_name"),
                "target": cur.get("target"),
                "where": cur.get("where", ""),
            }
        active.append(ct)
    return {"active": active, "done": _store().contracts(_wid(), "done")[-3:]}


# --------------------------------- ЕДИНЫЙ КОНТУР ДЕЙСТВИЯ (примитив×манера) - #
# Никаких кнопок-глаголов: свободный текст → LLM-интент → attempt() → события мира.
# Гейты по манере: openly (просто), stealthily (dex vs бдительность, свидетели),
# forcefully (сила vs храбрость, страх+гнев+свидетели), persuasively (симпатия vs натура).

# ------------------------------------------- ЖИВАЯ ЛОКАЦИЯ (mind + LLM) --- #
# NPC текущей локации живут по-настоящему: каждый тик КАЖДЫЙ решает ходом гибридного мозга
# (механика даёт побуждения → LLM выбирает В ХАРАКТЕРЕ, пишет реплику и описание). Действия
# реальны (apply_actions мутирует мир и память), фид — то, что игрок видит/слышит; незнакомцы
# обезличены дескриптором, имя открывается знакомством (talk).
_LIVE_GAP = PB["live_gap_s"]  # мин. сек между тиками (защита от бури поллов)


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
            _mark_seen(bid)  # рассказали — теперь знаешь, метка на карте
            if from_node is not None:
                r = city.route(from_node, kb.node)
                if r.found:
                    outs.append(
                        f"{nm}: {r.bearing or 'недалеко'}, ~{max(1, len(r.nodes) - 1)} мин ходу"
                    )
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


# нужда → как это выглядит «изнутри» локации (флейвор для сцены; сами нужды — из society-каталога)
_NEED_ITEM = {
    "hunger": "горячая похлёбка",
    "comfort": "кружка эля у очага",
    "fatigue": "тюфяк наверху",
    "purpose": "дело по хозяйству",
    "social": "застольная беседа",
    "wealth": "честный заработок",
    "novelty": "новые лица",
}


def _live_affordances(bid) -> list:
    """Чем локация закрывает нужды — ИЗ ЕДИНОГО каталога мест (society.advertises по фактшиту
    здания): та же реклама нужд, по которой жители сюда и приходят. Улица — новизна/суета."""
    if not bid:
        return [MItem("уличная суета", 0.15, satisfies="novelty")]
    data = (_store().get_building(_wid(), bid) or {}).get("data") or {}
    out = [
        MItem(_NEED_ITEM.get(need, need), min(0.4, round(rate * 1.8, 2)), satisfies=need)
        for need, rate in society.advertises(data).items()
    ]
    return out or [MItem("уличная суета", 0.15, satisfies="novelty")]


def _live_build(city, people, crof, cr2b, loc) -> None:
    bid = cr2b.get(loc)
    place = _binfo(bid)["name"] if bid else "улица"
    data = ((_store().get_building(_wid(), bid) or {}).get("data")) if bid else {}
    from aidnd.server.play.engine.zones import assign_zones, building_zones
    from aidnd.worldgen.furnish import zones_for

    _zd, zones = building_zones(bid)
    if not zones and not bid:  # УЛИЦА — тоже локация с зонами (docs/locations.md)
        street_kind = "площадь" if loc == (_S.get("geom") or {}).get("plaza") else "улица"
        zones = zones_for(street_kind, {}, kind="street")
    ent = "у входа" if bid else "обочина"            # точка появления: дверь или край улицы
    zone_names = {z["id"]: z["name"] for z in zones}
    zone_ids = {v: k for k, v in zone_names.items()}
    w = MWorld()
    if zones:  # ВОЛНА 2: зоны = МЕСТА разума — move сам переезжает, use ест ресурс СВОЕЙ зоны
        znames = list(zone_names.values())
        w.link(ent, "улица")
        for i, za in enumerate(znames):
            w.link(za, "улица")
            w.link(ent, za)
            for zb in znames[i + 1:]:
                w.link(za, zb)
        if bid:  # обстановка здания = НАСТОЯЩИЕ предметы live.db (лениво, идемпотентно)
            from aidnd.server.play.mechanics.items import _materialize_zones, _zone_stock

            _materialize_zones(bid)
        zone_items: dict = {}                        # место → {имя: iid} (loose — можно взять)
        zone_fixed: dict = {}                        # место → {имя: iid} (прибито — не унести)
        for z in zones:
            itms = []
            src = ([(None, o) for o in (z.get("objects") or [])] if not bid
                   else _zone_stock(bid, z["id"]))
            for iid, o in src:
                aff = o.get("afford") or {}
                if aff:
                    need, rate = max(aff.items(), key=lambda kv: kv[1])
                    if need == "fatigue" and z["kind"] not in ("beds", "cell"):
                        need = "comfort"             # скамья — отдых, но НЕ сон: спят в постели
                    itms.append(MItem(o["name"], min(0.5, round(rate * 2.2, 2)), satisfies=need))
                if iid:
                    tgt = zone_fixed if o.get("fixed") else zone_items
                    tgt.setdefault(zone_names[z["id"]], {})[o["name"]] = iid
            w.ground[zone_names[z["id"]]] = itms[:6]
        if _phase() == "night":                      # ночь: улица честно рекламирует постель дома
            w.ground["улица"] = [MItem("путь домой, к постели", 0.55, satisfies="fatigue")]
    else:
        w.link(place, "улица")
        w.ground[place] = _live_affordances(bid)
    hero = _pc_name()
    names = {PLAYER: hero if hero != "Странник" else "чужак"}  # NPC зовут по имени, если знают
    known_by = {
        pid
        for pid in _here(loc, crof)  # кто из присутствующих УЖЕ знаком с игроком
        if PLAYER in people[pid].state.relationships
    }
    roles = {
        PLAYER: (
            "гость, которого тут уже знают"
            if known_by
            else "недавно вошедший незнакомец. К чужакам тут не лезут первыми: глазеют исподволь, "
            "шепчутся; заговаривает лишь тот, кому это К ЛИЦУ — хозяин заведения с гостем, "
            "наглец, или у кого к нему дело/любопытство пересилило"
        )
    }
    rng = random.Random(f"live|{loc}")
    npc_map: dict = {}  # pid → {имя вещи: item_id} (кражи реальны)
    here_all = _here(loc, crof)
    if len(here_all) > PB["live_llm_cap"]:  # LOD: LLM-прослойка — только ядро сцены
        met = _met()
        core = [i for i in here_all if people[i].work] + [
            i for i in here_all if not people[i].work and i in met
        ]
        rest = [i for i in here_all if i not in core]
        rng.shuffle(rest)
        here_all = (core + rest)[: PB["live_llm_cap"]]
    workers = {pid for pid in here_all if people[pid].work == bid}
    zonemap = assign_zones({pid: people[pid].state for pid in here_all}, zones,
                           f"zones|{_wid()}|{bid}|{_phase()}",
                           roles={pid: people[pid].role for pid in here_all},
                           workers=workers) if zones else {}
    for pid in here_all:
        p = people[pid]
        _materialize_npc(pid, "visible")  # у присутствующих настоящие вещи при себе
        loot, imap = [], {}
        coins_np = _store().purse_get(_wid(), pid)
        if coins_np > 0:
            loot.append(
                MItem("кошель", min(1.0, 0.15 + coins_np / 40), kind="coin", amount=coins_np)
            )
        rows = [
            (r["item_id"], _store().get_item(r["item_id"])) for r in _store().inventory(_wid(), pid)
        ]
        rows = [(i, it) for i, it in rows if it and it["kind"] != "key"]
        if rows:
            iid, it = max(rows, key=lambda x: x[1]["worth"])
            loot.append(MItem(it["name"], min(1.0, it["worth"] / 40)))
            imap[it["name"]] = iid
        npc_map[pid] = imap
        w.add(
            Body(
                id=pid,
                place=(zone_names.get(zonemap.get(pid)) or ent) if zones else place,
                charisma=p.charisma,
                appearance=p.appearance,
                attention=round(rng.uniform(0.45, 0.85), 2),
                loot=loot,
            )
        )
        names[pid], roles[pid] = p.name, p.role
    pc_loot, pc_map = [], {}
    coins = _pc_coins()
    if coins > 0:
        pc_loot.append(MItem("кошель", min(1.0, 0.15 + coins / 40), kind="coin", amount=coins))
    best = max(
        ((r["item_id"], _store().get_item(r["item_id"])) for r in _store().inventory(_wid(), "pc")),
        key=lambda x: (x[1] or {}).get("worth", 0),
        default=(None, None),
    )
    if best[1]:
        pc_loot.append(MItem(best[1]["name"], min(1.0, best[1]["worth"] / 40)))
        pc_map[best[1]["name"]] = best[0]
    w.add(
        Body(
            id=PLAYER,
            place=(zone_names.get(_S.get("zone")) or ent) if zones else place,
            charisma=0.45,
            appearance=min(0.8, 0.25 + coins / 60),
            attention=0.85,
            loot=pc_loot,
        )
    )  # добыча игрока НАСТОЯЩАЯ (кража реальна)
    w.npc_minds = {pid: people[pid].state for pid in here_all}  # умы = те же, кто в телах (кэп LOD)
    w.names = names  # память пишет имена, не id
    w.aliases = {v.lower(): k for k, v in names.items()}
    w.lookup = lambda q: _world_lookup(q, loc)  # тулкол know: знание мира по запросу
    personas = {}
    for pid in here_all:  # глубина: манера/причуда/стремления из банка
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
        if pid in known_by:  # знакомство переживает тики и перестройки сцены
            bits.append(
                f"с гостем ({names[PLAYER]}) вы УЖЕ ЗНАКОМЫ и уже здоровались — "
                "НЕ приветствуй заново и не спрашивай, кто он; продолжай общение по делу"
            )
        if bits:
            personas[pid] = ". ".join(bits)
    here = _here(loc, crof)
    # ПРЕДЗНАКОМСТВО: жители одного городка знакомы (родня > коллеги > соседи).
    # Сеем только отсутствующие связи — прожитые отношения не трогаем.
    for i, a in enumerate(here_all):
        for b in here_all[i + 1:]:
            pa, pb = people[a], people[b]
            if b in pa.state.relationships or a in pb.state.relationships:
                continue
            sur_a = pa.name.split()[-1] if len(pa.name.split()) > 1 else ""
            sur_b = pb.name.split()[-1] if len(pb.name.split()) > 1 else ""
            if sur_a and sur_a == sur_b:                       # родня
                aff, tr, note = 0.45, 0.5, f"{{}} — моя родня (мы {sur_a}ы)"
            elif pa.work and pa.work == pb.work:               # коллеги по месту
                aff, tr, note = 0.3, 0.35, "{} — работаем бок о бок"
            else:                                              # соседи по городку
                aff, tr, note = 0.15, 0.2, None
            for x, y, yid in ((pa, pb, b), (pb, pa, a)):
                rel = x.state.rel(yid)
                rel["affinity"] = max(rel.get("affinity", 0.0), aff)
                rel["trust"] = max(rel.get("trust", 0.0), tr)
                if note:
                    x.state.memory.add(note.format(y.name), _mt(), 0.5, kind="fact",
                                       about=[yid])
    mgr = _model()
    todo = [pid for pid in here_all if not (people[pid].state.agendas or [])]
    if todo:  # долгая цель для placed NPC (редкий вызов)

        def plan_one(pid):
            st = people[pid].state
            ag = plan_agenda(st, w, {"roles": roles}, mgr)
            if ag:
                st.agendas.append(ag)

        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(plan_one, todo))
    prev = _S.get("live") or {}
    prev_places = {pid: b.place for pid, b in (prev.get("world").bodies.items()
                                               if prev.get("world") else {}.items())}
    if zones:
        keep = set(zone_names.values()) | {ent}
        for pid in here_all:
            if prev_places.get(pid) in keep:
                w.bodies[pid].place = prev_places[pid]          # человек ГДЕ СИДЕЛ, там и сидит
        zonemap = {pid: zone_ids.get(w.bodies[pid].place) for pid in here_all}
    prev_convs = [c for c in (prev.get("convs") or [])
                  if sum(1 for m in c["members"] if m in here_all or m == PLAYER) >= 2]
    same_loc = prev.get("loc") == loc
    _S["live"] = {
        "world": w,
        "convs": prev_convs,
        "clock": (prev.get("clock", 0) if same_loc else 0),
        "loc": loc,
        "place": place,
        "ts": 0.0,
        "who": frozenset(here),
        "pc_map": pc_map,
        "npc_map": npc_map,
        "last": {},
        "hist": {},
        "names": names,
        "roles": roles,
        "personas": personas,
        "zones": zones,
        "zone_names": zone_names,
        "zone_ids": zone_ids,
        "zone_places": set(zone_names.values()) | {ent},
        "ent": ent,
        "zonemap": zonemap,
        "zone_items": (zone_items if zones else {}),
        "zone_fixed": (zone_fixed if zones else {}),
        "workers": workers,
        "descr": _scene_descriptors(people, here_all),
        "rumors": list(((data or {}).get("rumors") or [])[:3]),
        "pdesc": (f"Город «{_city_name()}». " + ((data or {}).get("notable") or "")).strip(),
    }
    import logging as _logging

    _slog = _logging.getLogger("aidnd.scene")
    if _slog.isEnabledFor(_logging.DEBUG):
        znm = {z["id"]: z["name"] for z in zones}
        _slog.debug("═══ СБОРКА СЦЕНЫ «%s» (%s) · зон=%d · душ=%d · работников=%d ═══",
                    place, ("зоны" if zones else "без зон"), len(zones), len(here_all), len(workers))
        for pid in here_all:
            p = people[pid]
            tr = p.state.config.traits
            hot = ", ".join(f"{k} {v:.1f}" for k, v in tr.items() if v >= 0.65 or v <= 0.3)
            _slog.debug("  • %s [%s]%s → %s | черты: %s | персона: %s",
                        p.name, p.role, " (РАБ)" if pid in workers else "",
                        znm.get(zonemap.get(pid), "—"), hot or "ровные",
                        (personas.get(pid) or "—")[:100])


def _gossip(actor_st, actor_name: str, target_st) -> None:
    """Разговор NPC↔NPC переносит яркое воспоминание — сплетни ходят, репутация возникает сама."""
    juicy = [
        m
        for m in actor_st.memory.items
        if m.importance >= 0.4 and (PLAYER in (m.about or []) or m.importance >= 0.6)
    ]
    if not juicy:
        return
    m = juicy[-1]
    tale = f"{actor_name} рассказал(а) мне: {m.text}"
    if any(x.text == tale for x in target_st.memory.items[-30:]):
        return  # эту сплетню уже слышал
    target_st.memory.add(tale, _mt(), max(0.25, m.importance - 0.15), kind="gossip", about=m.about)


def _scene_zones() -> list[dict]:
    """Зоны ТЕКУЩЕЙ позиции игрока — где бы он ни был: живая сцена (интерьер ИЛИ улица) —
    истина; без сцены — шаблон здания или уличный шаблон узла. Один источник для интента."""
    lv = _S.get("live") or {}
    if lv.get("zones") and lv.get("loc") == _S.get("loc"):
        return lv["zones"]
    from aidnd.server.play.engine.zones import building_zones
    if _S.get("inside"):
        return building_zones(_S["inside"])[1]
    bid = (_S.get("cr2b") or {}).get(_S.get("loc"))
    if bid:
        return building_zones(bid)[1]
    from aidnd.worldgen.furnish import zones_for
    kind = "площадь" if _S.get("loc") == (_S.get("geom") or {}).get("plaza") else "улица"
    return zones_for(kind, {}, kind="street")


def _dm_snapshot(sc: dict) -> str:
    """СНИМОК живой сцены для нарратора: место/время/погода, кто где и чем занят, последние
    реплики, предметы вокруг игрока. Нарратор ОПИСЫВАЕТ этот мир, а не выдумывает свой."""
    lv = _S.get("live") or {}
    amb = (sc or {}).get("ambient") or {}
    parts = [f"МЕСТО: {(sc.get('location') or {}).get('name', lv.get('place', 'улица'))}. "
             f"{lv.get('pdesc', '')}",
             f"ВРЕМЯ: {amb.get('time', _PHASE_RU[_phase()])}, {_gt() // 60 % 24:02d}:{_gt() % 60:02d}; "
             f"погода: {amb.get('weather', '—')}; в зале {amb.get('mood', '—')}."]
    w = lv.get("world")
    people = _S.get("people") or {}
    if w is not None:
        pb = w.bodies.get(PLAYER)
        if pb is not None:
            parts.append(f"ИГРОК сейчас: {pb.place}.")
            objs = [i.name for i in (w.ground.get(pb.place) or [])][:8]
            if objs:
                parts.append("Рядом с игроком: " + ", ".join(objs) + ".")
        folks = []
        for pid in list(w.npc_minds)[:8]:
            if pid == PLAYER or w.bodies[pid].down():
                continue
            folks.append(f"{_display(pid, people)} ({w.bodies[pid].place}) — "
                         f"{(lv.get('last') or {}).get(pid, 'занят собой')}")
        if folks:
            parts.append("ЛЮДИ: " + "; ".join(folks) + ".")
        lines = []
        my = (lv.get("zonemap") or {}).get(PLAYER)
        ev = _S.get("eaves") or {}
        for c in (lv.get("convs") or [])[-3:]:
            znm = (lv.get("zone_names") or {}).get(c.get("zone"))
            audible = (PLAYER in (c.get("members") or []) or c.get("zone") == my
                       or (znm and znm == ev.get("place")))
            if not audible:                          # чужой стол — нарратору не дарим
                continue
            for who, txt in c.get("log", [])[-2:]:
                lines.append(f"{lv.get('names', {}).get(who, who)}: «{txt[:70]}»")
        if lines:
            parts.append("ПОСЛЕДНИЕ РЕПЛИКИ (что игроку слышно): " + " | ".join(lines[-5:]))
    return "\n".join(parts)


def _live_tick(people) -> tuple:
    from aidnd.server.play.engine import deeds as _deeds

    lv, mgr = _S["live"], _model()
    w = lv["world"]
    inz = lv.get("zone_places")
    order = [
        pid
        for pid in w.npc_minds
        if not w.bodies[pid].down()
        and (w.bodies[pid].place in inz if inz else w.bodies[pid].place == lv["place"])
    ]
    random.Random(f"tick|{lv['clock']}").shuffle(order)
    # МОЛЧАНИЕ — тоже сигнал: окликнул чужака, а тот не ответил → это факт мира, NPC его помнит
    awaiting = lv.get("awaiting") or []
    if awaiting and not lv.pop("pc_spoke", False):
        for pid in awaiting:
            if pid in w.npc_minds:  # kind=note → попадает в «ТВОИ МЫСЛИ» решений
                w.npc_minds[pid].memory.add(
                    "я окликнул(а) чужака, но он ПРОМОЛЧАЛ — не хочет говорить, навязываться дальше стыдно",
                    lv["clock"],
                    0.55,
                    kind="note",
                    about=[PLAYER],
                )
        lv["last"][PLAYER] = "молчит — на обращения не отвечает, в разговоры не вступает"
    lv["awaiting"] = []
    # чем занят чужак ПРЯМО СЕЙЧАС — часть мира: NPC сами решают, лезть ли (характер, не таймер)
    roles = dict(lv["roles"])
    dlg = _S.get("dlg")
    if dlg and dlg in people and dlg in order:
        roles[PLAYER] = (
            f"{roles.get(PLAYER, 'чужак')} — прямо сейчас увлечён разговором "
            f"с {lv['names'].get(dlg, 'кем-то')}; встревать в чужую беседу — дело наглое"
        )
    personas = dict(lv.get("personas", {}))
    if dlg in personas or (dlg and dlg in order):
        personas[dlg] = (
            personas.get(dlg, "") + ". Ты ПРЯМО СЕЙЧАС беседуешь с чужаком — вы уже "
            "в разговоре: НЕ окликай и не приветствуй заново; отвечай на его слова, "
            "а если он молчит — не дёргай, дай ему выпить/подумать, займись делом"
        ).lstrip(". ")
    # ВОЛНА 2: позиция = ТЕЛО в зоне-месте (двигает сам разум move'ом); zonemap — производная
    zones_l = lv.get("zones") or []
    zmap = lv.setdefault("zonemap", {})
    zone_feed = []
    if zones_l:
        pbody = w.bodies.get(PLAYER)
        if pbody is not None:  # позиция игрока — из его состояния (клик по плану/фриформ)
            pbody.place = lv["zone_names"].get(_S.get("zone")) or lv.get("ent", "у входа")
        for pid in list(w.npc_minds):
            zmap[pid] = lv["zone_ids"].get(w.bodies[pid].place)
        zmap[PLAYER] = _S.get("zone")
    zname_of = {}
    if zones_l and w.bodies.get(PLAYER) and w.bodies[PLAYER].place != lv.get("ent", "у входа"):
        zname_of[PLAYER] = w.bodies[PLAYER].place
    if lv["clock"] >= 3 and "незнакомец" in str(roles.get(PLAYER, "")):
        # к чужаку ПРИГЛЯДЕЛИСЬ — состояние сцены, не кулдаун: он больше не главное событие зала
        roles[PLAYER] = ("чужак, который тут уже посидел — к нему пригляделись и вернулись "
                         "к своим делам; лезть к нему без причины незачем")
    if zname_of.get(PLAYER):
        roles[PLAYER] = f"{roles.get(PLAYER, 'чужак')}; он сейчас — {zname_of[PLAYER]}"
    news = [str(x) for x in ((_S.get("guild_news") or []) + (_S.get("board_news") or []))[-2:]]
    news += _deeds.town_talk(lv["names"], limit=2)     # свежие ДЕЛА города — в сплетни
    rums = lv.get("rumors") or []
    rumor_of = ({pid: rums[hash((pid, _gt() // 1440)) % len(rums)] for pid in order}
                if rums else {})
    ctx = {
        "roles": roles,
        "names": lv["names"],
        "last_actions": lv["last"],
        "history": lv["hist"],
        "clock": lv["clock"],
        "place_desc": ({p_: f"Это часть зала «{lv['place']}». {lv['pdesc']}"
                        for p_ in (lv.get("zone_places") or ())}
                       if zones_l else {lv["place"]: lv["pdesc"]}),
        "personas": personas,
        "zones": zname_of,
        "news": news[:3],
        "rumor_of": rumor_of,
        "sexes": {pid: ("женщина" if (people[pid].persona or {}).get("sex") == "f" else "мужчина")
                  for pid in order},
        "time": f"{_PHASE_RU[_phase()]}, {_gt() // 60 % 24:02d}:{_gt() % 60:02d}",
    }

    # ── ДИРИЖЁР: LLM-ход получает тот, кому ЕСТЬ ЗАЧЕМ (долг > эмоция > нужда > беседа > фон)
    from aidnd.server.play.engine.convo import (
        conv_block,
        conv_debt_to,
        conv_note_say,
        conv_of,
        conv_tick,
    )

    conv_tick(lv, lambda m: w.bodies[m].place if m in w.bodies else None)
    salient = lv.pop("salient", None)
    oaths, oaths_due = {}, set()
    for d_ in _deeds.promises_active():
        if d_["actor"] in w.npc_minds:
            oaths[d_["actor"]] = _deeds.promise_line(d_, lv["names"])
            if d_["data"].get("due") == _phase():
                oaths_due.add(d_["actor"])
    impulses: dict = {}
    for pid in order:
        st = w.npc_minds[pid]
        imp, why = 0.35, "фон"
        c = conv_of(lv, pid)
        if salient:
            imp, why = 3.5, "событие"
        elif conv_debt_to(lv, pid):
            imp, why = 4.0, "долг ответа"
        elif pid in oaths_due:
            imp, why = 2.6, "слово"                    # срок пришёл — данное слово тянет
        elif max(st.emotion.get("fear", 0), st.emotion.get("anger", 0)) >= 0.5:
            imp, why = 3.0, "эмоция"
        elif c is not None and c.get("quiet", 9) <= 1:
            imp, why = 1.6, "беседа"
        else:
            hot = max(st.needs.values(), default=0.0)
            if hot >= 0.65:
                imp, why = 1.2 + hot, "нужда"
            elif st.agendas:
                jit = random.Random(f"agimp|{pid}|{lv['clock']}").random()
                imp, why = 0.6 + 0.7 * jit, "агенда"
        imp += (st.config.traits.get("sociability", 0.5) - 0.5) * 0.5
        impulses[pid] = (round(imp, 2), why)
    ranked_imp = sorted(order, key=lambda p: -impulses[p][0])
    actors = [p for p in ranked_imp if impulses[p][0] >= PB["impulse_llm"]][: PB["live_llm_cap"]]
    if not actors and order:
        actors = ranked_imp[:1]                       # зал не замирает совсем
    background = [p for p in order if p not in actors]
    ctx["convs"] = {pid: b for pid in actors
                    if (b := conv_block(lv, pid, lv["names"]))}
    if salient:
        ctx["event"] = salient
    ctx["oaths"] = oaths

    def think_one(pid):  # внутри волны — параллельно; волны видят заявки предыдущих
        st = w.npc_minds[pid]
        _decay_needs(st)
        _decay_emotion(st)
        advance_agendas(st, w)  # долгие цели двигаются
        return pid, decide_hybrid(st, w, mind_perceive(st, w), mgr, ctx)

    def _claim(pid, d) -> str:
        """Заявка актёра для следующей волны: что он ПРЯМО СЕЙЧАС делает/говорит."""
        bits = []
        for a in (d.get("actions") or [])[:2]:
            if not isinstance(a, dict):
                continue
            if a.get("tool") == "say" and a.get("text"):
                bits.append(f"говорит: «{str(a['text'])[:48]}…»")
            elif a.get("tool") == "use" and a.get("item"):
                bits.append(f"занят: {a['item']}")
            elif a.get("tool") == "move" and a.get("to"):
                bits.append(f"идёт: {a['to']}")
        what = "; ".join(bits) or str(d.get("does") or "")[:60]
        return f"{lv['names'].get(pid, pid)} — {what}" if what else ""

    from concurrent.futures import ThreadPoolExecutor

    # АНТИ-ХОР: волны решений — лидер (высший импульс) первым, свита видит его заявку
    decisions: dict = {}
    waves = [actors[:1], actors[1:]] if len(actors) > 1 else [actors]
    with ThreadPoolExecutor(max_workers=8) as ex:
        for wave in waves:
            if not wave:
                continue
            ctx["now"] = [c for pid_ in decisions
                          if (c := _claim(pid_, decisions[pid_]))]
            decisions.update(ex.map(think_one, wave))
    ctx.pop("now", None)

    # фоновые ЖИВУТ без LLM: заняты предметом своей зоны, нужды закрываются, зал их видит
    bg_feed = []
    rng_bg = random.Random(f"bg|{lv['clock']}")
    busy: set = set()                                 # одна кочерга — один ворошащий
    for d_ in decisions.values():
        for a_ in d_.get("actions") or []:
            if isinstance(a_, dict) and a_.get("tool") == "use" and a_.get("item"):
                busy.add(str(a_["item"]).lower())
    for pid in background:
        st = w.npc_minds[pid]
        _decay_needs(st)
        _decay_emotion(st)
        body = w.bodies[pid]
        itms = [i for i in w.ground.get(body.place, [])
                if i.satisfies and i.satisfies != "fatigue" and i.name.lower() not in busy]
        if itms:
            it = max(itms, key=lambda i: st.needs.get(i.satisfies or "", 0.0))
            busy.add(it.name.lower())
            st.needs[it.satisfies] = max(0.35 if it.satisfies == "fatigue" else 0.0,
                                          st.needs.get(it.satisfies, 0.0) - 0.12)
            act = f"занят своим: {it.name}"
        else:
            act = "сидит, поглядывая на зал"
        lv["last"][pid] = act
        if rng_bg.random() < PB["bg_feed_p"]:
            bg_feed.append({"k": "deed", "who": _display(pid, people), "text": act})

    # ── подробный лог сцены (data/debug/play.log): «почему» каждого NPC за тик ──
    import logging as _logging

    _slog = _logging.getLogger("aidnd.scene")
    if _slog.isEnabledFor(_logging.DEBUG):
        _slog.debug("─── ТИК %s · %s · «%s» · душ=%d · LLM-актёров=%d · разговоров=%d · "
                    "игрок@%s (zone=%s) ───",
                    lv["clock"], ctx["time"], lv["place"], len(order), len(actors),
                    len(lv.get("convs") or []),
                    w.bodies[PLAYER].place if PLAYER in w.bodies else "?", _S.get("zone"))
        for pid in background:
            im, why = impulses[pid]
            _slog.debug("  · фон %s [%s] зона=%s имп=%.2f(%s) → %s",
                        lv["names"].get(pid, pid), lv["roles"].get(pid, "?"),
                        w.bodies[pid].place if zones_l else "—", im, why,
                        lv["last"].get(pid, "—"))
        for pid in actors:
            st = w.npc_minds[pid]
            d = decisions[pid]
            nm = lv["names"].get(pid, pid)
            zn = w.bodies[pid].place if zones_l else "—"
            needs = ", ".join(f"{k}:{v:.2f}" for k, v in st.needs.items() if v >= 0.35) or "норма"
            emo = ", ".join(f"{k}:{v:.2f}" for k, v in st.emotion.items() if v >= 0.2) or "спокоен"
            ag = st.agendas[0].summary if st.agendas else "—"
            acts = " | ".join(
                (a.get("tool", "?") + (f"→{a.get('to')}" if a.get("to") else "")
                 + (f":«{str(a.get('text'))[:60]}»" if a.get("text") else "")
                 + (f" item={a.get('item')}" if a.get("item") else "")
                 + (f" need={a.get('need')}={a.get('value')}" if a.get("need") else ""))
                for a in (d.get("actions") or []) if isinstance(a, dict)) or "—"
            im, why = impulses[pid]
            _slog.debug(
                "  ▸ %s [%s] зона=%s имп=%.2f(%s)\n"
                "      нужды: %s | эмоции: %s | агенда: %s\n"
                "      src=%s think=«%s» does=«%s»\n"
                "      prefs=%s\n"
                "      actions: %s",
                nm, lv["roles"].get(pid, "?"), zn, im, why, needs, emo, ag,
                d.get("src", "?"), str(d.get("think", ""))[:120], str(d.get("does", ""))[:120],
                "; ".join(f"{p[0]}({p[1]},{p[2]:.2f})" for p in (d.get("prefs") or [])[:5]),
                acts)

    feed, address = list(zone_feed) + bg_feed, []
    said_n = 0  # LOD-кэп реплик ленты
    topics = lv.setdefault("topics", [])  # анти-эхо ПОМНИТ прошлые тики (хвост сигнатур)
    pc = _pc()

    def _say_ok(txt: str) -> bool:
        nonlocal said_n
        sig = frozenset(list(_tokens_ru(txt))[:6])
        if said_n >= PB["say_cap_per_tick"]:  # лимит реплик — остальные слушают
            return False
        if sig and any(len(sig & s) >= max(2, len(sig) // 2 + 1) for s in topics):
            return False  # почти дубль уже сказанного — «заезженная тема»
        topics.append(sig)
        del topics[:-12]  # помним последние ~4 тика разговоров
        said_n += 1
        return True

    used_items: set = set()                           # физика: один предмет — одни руки за тик
    for pid in actors:  # применяем последовательно (честный порядок)
        d = decisions[pid]
        for a in d.get("actions") or []:
            if not (isinstance(a, dict) and a.get("tool") == "use" and a.get("item")):
                continue
            key = (w.bodies[pid].place, str(a["item"]).lower())
            if key not in used_items:
                used_items.add(key)
                continue
            taken = {k[1] for k in used_items if k[0] == w.bodies[pid].place}
            alt = next((i for i in w.ground.get(w.bodies[pid].place, [])
                        if i.satisfies and i.name.lower() not in taken), None)
            if alt is not None:                       # кружка занята — берёт соседнюю
                a["item"] = alt.name
                used_items.add((w.bodies[pid].place, alt.name.lower()))
            else:
                a["tool"] = "wait"                    # всё разобрано — ждёт своей очереди
        st = w.npc_minds[pid]
        before = {vid: {i.name for i in b.loot} for vid, b in w.bodies.items() if vid != pid}
        my_place = w.bodies[pid].place
        gr_before = {i.name for i in (w.ground.get(my_place) or [])}
        evs = apply_actions(d.get("actions") or [], st, w, lv["clock"])
        for nm in gr_before - {i.name for i in (w.ground.get(my_place) or [])}:
            iid = (lv.get("zone_items") or {}).get(my_place, {}).pop(nm, None)
            if iid:                                  # поднял вещь заведения — она теперь ЕГО
                _store().inv_move(_wid(), iid, pid)
                st.memory.add(f"прибрал(а) к рукам: {nm}", lv["clock"], 0.5)
        for vid, names_before in before.items():  # кражи РЕАЛЬНЫ (у игрока и NPC↔NPC)
            b = w.bodies.get(vid)
            stolen = names_before - ({i.name for i in b.loot} if b else set())
            for nm in stolen:
                if vid == PLAYER:
                    if nm == "кошель":
                        take = max(1, _pc_coins() // PB["purse_cut"])
                        _store().purse_add(_wid(), "pc", -take)
                        _store().purse_add(_wid(), pid, take)
                        feed.append(
                            {
                                "k": "deed",
                                "who": _display(pid, people),
                                "text": f"ловко срезает твой кошель — минус {take} зм!",
                            }
                        )
                        _pc_remember(
                            f"у меня срезали кошель ({take} зм) — это был {_display(pid, people)}",
                            0.8,
                            about=[pid],
                        )
                    elif nm in (lv.get("pc_map") or {}):
                        _store().inv_move(_wid(), lv["pc_map"][nm], pid)
                        feed.append(
                            {
                                "k": "deed",
                                "who": _display(pid, people),
                                "text": f"вытягивает у тебя «{nm}»!",
                            }
                        )
                        _pc_remember(f"у меня украли «{nm}»", 0.8, about=[pid])
                    st.memory.add(
                        f"я обчистил(а) чужака: взял(а) {nm}", lv["clock"], 0.7, about=[PLAYER]
                    )
                    _deeds.record(pid, "theft", obj=PLAYER, place=lv["place"],
                                  witnesses=[o for o in order
                                             if o != pid and w.bodies[o].place == w.bodies[pid].place],
                                  data={"what": nm})
                else:
                    if nm == "кошель":
                        take = max(1, _store().purse_get(_wid(), vid) // PB["purse_cut"])
                        _store().purse_add(_wid(), vid, -take)
                        _store().purse_add(_wid(), pid, take)
                    elif nm in (lv.get("npc_map", {}).get(vid) or {}):
                        _store().inv_move(_wid(), lv["npc_map"][vid][nm], pid)
                    feed.append(
                        {
                            "k": "deed",
                            "who": _display(pid, people),
                            "text": f"тянет что-то из добра ({_display(vid, people)}) — ты это ВИДИШЬ",
                        }
                    )
                    st.memory.add(
                        f"я взял(а) чужое ({nm}) у {lv['names'].get(vid, vid)}",
                        lv["clock"],
                        0.6,
                        about=[vid],
                    )
                    if vid in w.npc_minds:
                        w.npc_minds[vid].memory.add(
                            f"меня обокрали — пропало {nm}", lv["clock"], 0.7, about=[pid]
                        )
                    _deeds.record(pid, "theft", obj=vid, place=lv["place"],
                                  witnesses=[PLAYER], data={"what": nm})
                    _pc_remember(
                        f"видел, как {_display(pid, people)} обокрал {_display(vid, people)}",
                        0.5,
                        about=[pid, vid],
                    )
        who = _display(pid, people)
        said = False
        spoke = []  # речь — тоже ДЕЙСТВИЕ: попадает в last/hist/память
        for a in d.get("actions") or []:
            if isinstance(a, dict) and a.get("tool") == "say" and str(a.get("text") or "").strip():
                tgt = str(a.get("to") or "")
                tid = (w.aliases or {}).get(tgt.strip().lower(), tgt)
                txt = str(a["text"])[:180]
                if not _say_ok(txt):  # кэп реплик / анти-эхо — этот молчит
                    continue
                said = True
                if tid == PLAYER:  # решение «заговорить с чужаком» — за самим NPC
                    conv_note_say(lv, pid, PLAYER, txt, w.bodies[pid].place)
                    address.append({"npc": pid, "who": who, "text": txt})
                    pc.memory.add(f"{who} обратился ко мне: «{txt[:100]}»", _mt(), 0.4, about=[pid])
                    spoke.append(f"я сам(а) заговорил(а) с чужаком: «{txt[:60]}»")
                    st.memory.add(
                        f"я сам(а) заговорил(а) с чужаком: «{txt[:80]}»",
                        lv["clock"],
                        0.45,
                        about=[PLAYER],
                    )
                    lv.setdefault("awaiting", []).append(
                        pid
                    )  # ответит ли чужак — узнаем следующим тиком
                else:
                    conv_note_say(lv, pid, tid, txt, w.bodies[pid].place)
                    # СЛЫШИМОСТЬ (docs/locations.md): своя зона — полностью; чужая — обрывком
                    same_zone = (not zones_l) or (
                        PLAYER in w.bodies and w.bodies[pid].place == w.bodies[PLAYER].place)
                    ev = _S.get("eaves") or {}
                    eaves_on = (zones_l and not same_zone
                                and ev.get("place") == w.bodies[pid].place
                                and lv["clock"] <= ev.get("until", -1))
                    if same_zone or eaves_on:        # прослушка = честно добытый ярус слуха
                        feed.append(
                            {
                                "k": "speech",
                                "who": who,
                                "to": _display(tid, people) if tid in people else tgt,
                                "text": txt if same_zone
                                else f"(подслушано — {w.bodies[pid].place}) {txt}",
                            }
                        )
                        pc.memory.add(
                            f"слышал в «{lv['place']}»: {who} — {txt[:90]}",
                            _mt(),
                            0.18 if same_zone else 0.3,
                            kind="heard",
                            about=[pid],
                        )
                    else:
                        znm = w.bodies[pid].place
                        if random.Random(f"hear|{lv['clock']}|{pid}").random() < 0.35:
                            feed.append(
                                {
                                    "k": "speech",
                                    "who": who,
                                    "to": _display(tid, people) if tid in people else tgt,
                                    "text": f"({znm}, краем уха) …{txt[:34]}…",
                                }
                            )
                            pc.memory.add(
                                f"краем уха ({znm}): {who} о чём-то говорил — …{txt[:36]}…",
                                _mt(),
                                0.08,
                                kind="heard",
                                about=[pid],
                            )
                        else:
                            lv["murmur"] = lv.get("murmur", 0) + 1   # общий гул вместо прослушки
                    spoke.append(f"сказал(а) {lv['names'].get(tid, tgt)}: «{txt[:50]}»")
                    if tid in w.npc_minds and ((not zones_l)
                                               or w.bodies[tid].place == w.bodies[pid].place):
                        _gossip(st, lv["names"].get(pid, pid), w.npc_minds[tid])
                    if tid in w.npc_minds:  # обращение доходит и через зал (окликнули)
                        w.npc_minds[tid].memory.add(
                            f"ко мне обратился {who}: «{txt[:80]}» — стоит ответить",
                            lv["clock"],
                            0.55,
                            about=[pid],
                        )
        for a in d.get("actions") or []:                 # СЛОВО NPC → обязательство мира
            if isinstance(a, dict) and a.get("tool") == "promise" and a.get("to"):
                to_id = (w.aliases or {}).get(str(a["to"]).strip().lower(), str(a["to"]))
                wtok = _tokens_ru(str(a.get("where") or ""))
                spot = next((k for k in _S["geom"]["keys"]
                             if wtok and _tokens_ru(k["label"]) & wtok), None)
                _deeds.promise_make(pid, to_id, str(a.get("what") or ""),
                                    str(a.get("when") or ""), str(a.get("where") or ""),
                                    spot["node"] if spot else None,
                                    spot["label"] if spot else str(a.get("where") or ""),
                                    witnesses=[o for o in order if o != pid])
                feed.append({"k": "deed", "who": who,
                             "text": f"даёт слово: {str(a.get('what') or '')[:60]}"})
        if any(isinstance(a, dict) and a.get("tool") == "attack" for a in d.get("actions") or []):
            lv["salient"] = f"{who} бросается в драку!"     # событие: зал вздрогнет в след. тик
        # ЕДА НЕ БЕСПЛАТНА: use съестного при работнике заведения = заказ с оплатой
        owner = next((wk for wk in (lv.get("workers") or ()) if wk in order), None)
        if owner and owner != pid:
            for a in d.get("actions") or []:
                if isinstance(a, dict) and a.get("tool") == "use" and a.get("item"):
                    itm = next((i for i in w.ground.get(w.bodies[pid].place, [])
                                if i.name == a["item"] and i.satisfies == "hunger"), None)
                    if itm is not None and _store().purse_get(_wid(), pid) >= 2:
                        _store().purse_add(_wid(), pid, -2)
                        _store().purse_add(_wid(), owner, 2)
                        if random.Random(f"pay|{pid}|{lv['clock']}").random() < 0.3:
                            feed.append({"k": "deed", "who": _display(pid, people),
                                         "text": f"кидает пару монет за {a['item']}"})
        acted = "; ".join(evs + spoke)  # NPC ПОМНИТ и дела, и слова — не повторяется
        lv["last"][pid] = acted[:110] or "—"
        lv["hist"].setdefault(pid, []).append(acted[:80])
        does = (d.get("does") or "").strip()
        if does and not said:  # реплика сама несёт момент — не дублируем
            feed.append({"k": "deed", "who": who, "text": does[:150]})
    if lv.pop("murmur", 0) and lv["clock"] % 3 == 0:
        feed.append({"k": "deed", "who": "зал", "text": "за столами гудит негромкий говор"})
    if zones_l:
        for pid in order:
            zmap[pid] = lv["zone_ids"].get(w.bodies[pid].place)
    lv["clock"] += 1
    _gt_add(PB["live_tick_min"])  # тик мира (игровые минуты)
    _pc_save()
    for pid in order:  # прожитое переживает рестарт
        _npc_save(pid)
    return feed, address


def _world_tick() -> dict:
    """★ ТИК МИРА — единственная точка «мир сделал ход». Зовётся в конце обработки ЛЮБОГО действия
    игрока (пошаговость, как за столом). Два слоя:
      1) ПАССИВНЫЙ мир — рутина ВСЕХ жителей из нужд/характера/времени + суточные события
         (aidnd.society → worldsim.routine_step; синхронизируется в _play/_apply_routine,
         идемпотентно по фазе суток);
      2) ЖИВАЯ сцена — кто рядом с игроком, думают/говорят/действуют (mind + LLM, _live_tick).

    ИГРОВОЙ ЦИКЛ (каждый @router.post /api/play/*):
        действие игрока → _gt_add(время действия) → мутация мира → _world_tick() → сцена в ответ.
    """
    city, people, crof, cr2b, loc = _play()  # _play → _apply_routine: пассивный мир синхронен
    lv = _S.get("live")
    if not lv or lv["loc"] != loc or lv.get("who") != frozenset(_here(loc, crof)):
        _live_build(city, people, crof, cr2b, loc)
    try:
        feed, address = _live_tick(people)  # живая сцена: те, кто рядом
    except (LLMUnavailable, LLMBadOutput):  # без модели не притворяемся — честная ошибка игроку
        raise
    except Exception:  # noqa: BLE001 — прочие баги тика не роняют действие игрока
        import logging

        logging.getLogger("aidnd").warning("live tick failed", exc_info=True)
        return {"feed": [], "address": []}
    return {"feed": feed, "address": address}
