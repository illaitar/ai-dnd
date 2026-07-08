"""Game loop — WORLD AND ORCHESTRATION: generation, scene, movement, dialogue, action, live location + HTTP endpoints.

mechanics/ layer (see docs/loop.md).
"""

from __future__ import annotations

import random

from fastapi import Request

from aidnd import society
from aidnd.citygraph import CityParams, generate, visual
from aidnd.citygraph.model import NodeKind
from aidnd.inference import LLMBadOutput, LLMUnavailable
from aidnd.mind import Body, advance_agendas
from aidnd.mind import Item as MItem
from aidnd.mind import World as MWorld
from aidnd.mind import perceive as mind_perceive
from aidnd.mind.llm_agent import apply_actions, decide_hybrid, plan_agenda
from aidnd.mind.tick import _decay_emotion, _decay_needs
from aidnd.server.play.engine.core import (
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
    _scene_descriptors,
    _store,
    _tokens_ru,
    _wanted,
    _wanted_add,
    _wid,
    router,
)
from aidnd.server.play.engine.resolve import _STANCE, _VOICE, _world_lookup
from aidnd.server.play.engine.sound import audibility, overheard_line
from aidnd.server.play.engine.worldbuild.building import (
    _building_containers as _building_containers,
)
from aidnd.server.play.engine.worldbuild.building import _building_keys as _building_keys
from aidnd.server.play.engine.worldbuild.building import _building_rooms as _building_rooms
from aidnd.server.play.engine.worldbuild.building import _res_binfo as _res_binfo
from aidnd.server.play.engine.worldbuild.geom import _build_geom as _build_geom
from aidnd.server.play.engine.worldbuild.geom import _scene_zones as _scene_zones
from aidnd.server.play.engine.worldbuild.person import _person_from_row as _person_from_row
from aidnd.server.play.engine.worldbuild.ties import _weave_locals as _weave_locals
from aidnd.server.play.engine.worldbuild.ties import _weave_ties as _weave_ties
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


def _overheard(text, player_zone, speaker_zone, zone_name, seed, boost=0):
    """(tier_int|None, display_text, mem_weight) for a conversation line the player
    overhears — spatial audibility tier drives the fidelity (docs/sound-attention.md)."""
    tier = audibility(player_zone, speaker_zone, PB["sound_voice"], boost=boost)
    if tier is None:
        return None, "", 0.0
    disp, w = overheard_line(text, tier, zone_name, seed)
    return int(tier[1]), disp, w


def _world_events() -> None:
    """Daily passive world events (once per day, morning): wanted level cools, adventurers leave
    on guild contracts, citizens post on board, random caravan brings goods. Each in its own try:
    one failure doesn't crash world."""
    if _wanted() > 0:  # wanted level cools — memory is finite
        _wanted_add(-PB["wanted_decay"])
    try:
        from aidnd.server.play.engine.incidents import gang_morning, incident_spawn
        from aidnd.server.play.mechanics.deals import _deal_jobs

        news = _npc_delves() + _deal_jobs() + incident_spawn() + gang_morning()
        if news:
            _S["guild_news"] = (_S.get("guild_news") or [])[-2:] + news
    except Exception:  # noqa: BLE001 — raid doesn't crash the world
        pass
    try:
        bn = _board_npc_fulfill() + _board_publish()
        if bn:
            _S["board_news"] = (_S.get("board_news") or [])[-3:] + bn
    except Exception:  # noqa: BLE001 — board doesn't crash the world
        pass
    try:
        if random.Random(f"caravan|{_gt() // 1440}|{_wid()}").random() < PB["caravan_chance"]:
            _merchant_restock(f"caravan|{_gt() // 1440}")
    except Exception:  # noqa: BLE001
        pass


def _apply_routine() -> None:
    """Sync passive world with current game time: idempotent, cheap — once per day phase
    (key phase+day). Routine of ALL residents built from NEEDS/character/time (society, via
    worldsim.routine_step), not hardcoded roles. At dawn — daily events."""
    key = (_gt() // 30, _gt() // 1440)               # routine step: every 30 game minutes
    if _S.get("routine_key") == key or not _S.get("people"):
        return
    _S["routine_key"] = key
    mkey = (_phase(), _gt() // 1440)                 # daily events — once at morning
    if mkey[0] == "morning" and _S.get("events_key") != mkey:
        _S["events_key"] = mkey
        _world_events()
    try:  # E1: economy — lazy catch-up for EVERY skipped day (not just 'morning')
        from aidnd.server.play.engine.economy import economy_catchup
        en = economy_catchup()
        if en:
            _S["econ_news"] = (_S.get("econ_news") or [])[-2:] + en
    except Exception:  # noqa: BLE001 — economy doesn't crash the world
        pass
    routine_step(_S["people"], _S["crof"], pin=set(_here(_S["loc"], _S["crof"])))


def _assign_key_buildings(city) -> None:
    """World created → distribute key building slots FROM POOL by slot type-hint (guild → guild).
    Written to live-DB once; re-entry reads ready data."""
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
        h = hint.split()[0].lower()  # 'Temple of Fortune' → temple
        for r in rows:  # by type first, then any
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


# Profession categories (role→needs venue vs produces at home). Data in code — small table;
# scale up later to content/professions.json.
_VENUE_NEED = {"трактирщик", "лавочник", "оружейник", "жрец", "маг"}   # no venue ⟹ day laborer
_HOME_PRODUCER = {"дубильщик", "сапожник", "мельник", "кузнец", "знахарка"}  # craft at home
_MOBILE_ROLE = {"стражник", "головорез", "бродяга", "бард", "горожанин"}
_WORKCAP = {"таверн": 6, "трактир": 6, "гильд": 6, "игорн": 4, "лавк": 3, "оружейн": 2,
            "кузн": 3, "храм": 3, "молельн": 3, "часовн": 3, "лечебн": 3, "мастерск": 3,
            "башн": 2, "магич": 2}


def _plan_jobs(city, homes: dict, roles: dict) -> dict:
    """DETERMINISTIC: who works at which venue (gravity — nearest by home) + who to reclassify.
    Returns pid → (work_bid|None, role_override|None). Pure function of (city, homes, roles) —
    same result in both settlement paths (fresh/restore)."""
    xy = {n.id: (n.x, n.y) for n in city.nodes()}

    def dist(pid, node):
        h = homes.get(pid)
        if h not in xy or node not in xy:
            return 1e9
        (ax, ay), (bx, by) = xy[h], xy[node]
        return (ax - bx) ** 2 + (ay - by) ** 2

    out: dict = {}
    assigned: set = set()
    for bid, kb in sorted(city.key_buildings.items()):  # venue recruits NEAREST by role
        want = _role_for_building(bid)
        info = (_binfo(bid)["kind"] + " " + _binfo(bid)["name"]).lower()
        cap = next((c for w, c in _WORKCAP.items() if w in info), 3)
        cand = sorted((pid for pid, r in roles.items()
                       if r == want and pid not in assigned),
                      key=lambda pid: dist(pid, kb.node))
        for pid in cand[:cap]:
            out[pid] = (bid, None)
            assigned.add(pid)
    for pid, r in roles.items():                        # remainder: home-producer / day laborer
        if pid in assigned:
            continue
        if r in _VENUE_NEED:                            # service without venue won't work — day laborer
            out[pid] = (None, "подёнщик")
        # HOME_PRODUCER and MOBILE — no override (produce at home / mobile), work=None
    return out


def _surname(name: str) -> str:
    """Surname = last name token (else empty) — same logic as pre-acquaintance kin."""
    parts = name.split()
    return parts[-1] if len(parts) > 1 else ""


def _households(rows: list, rng) -> list:
    """D1: split pool into FAMILY households — small groups of one surname (couple/siblings),
    each lives in one house. Deterministic (rng from settle|wid). Size 1-5, peak 2-3."""
    by_sur: dict = {}
    for r in rows:
        by_sur.setdefault(_surname(r["name"]) or r["id"], []).append(r["id"])
    households = []
    for sur in sorted(by_sur):
        members = sorted(by_sur[sur])
        rng.shuffle(members)
        i = 0
        while i < len(members):
            size = rng.choices([1, 2, 3, 4, 5], weights=[2, 4, 4, 2, 1])[0]
            households.append(members[i:i + size])
            i += size
    return households


def _reclass_note(p, former: str) -> None:
    """Narrative downward mobility: mark 'was once X' + former_role (for venue buyout,
    layer B3) — not silent role change."""
    p.former_role = former                            # grad student remembers craft (can buy out)
    if any("прежде был" in m.text for m in p.state.memory.items):
        return
    p.state.memory.add(f"прежде был {former}, да места не нашёл — перебиваюсь подёнщиной",
                       _mt(), 0.5)


def _restore_placed(city, placed):
    """Rebuild the SAME residents from stored placements (persisted across re-entry): drop the
    dead/captive, re-plan jobs (venue gravity may have shifted), then top up any dependents forged
    into the pool after this world was first settled. Returns (people, spot); may be empty."""
    store, by_id = _store(), {r["id"]: r for r in _pool().list_people(limit=100000)}
    dead = {k.split("|", 1)[1] for k in store.flags_prefix(_wid(), "dead|")} | \
        {k.split("|", 1)[1] for k in store.flags_prefix(_wid(), "captive|")}  # captives don't roam
    homes = {pid: pl["home"] for pid, pl in placed.items() if pid not in dead}
    roles = {pid: by_id[pid]["role"] for pid in homes if pid in by_id}
    jobs = _plan_jobs(city, homes, roles)               # venue gravity + reclassification
    people, spot = {}, {}
    for pid, pl in placed.items():
        if pid in dead or pid not in by_id:
            continue  # the dead do not return
        work, override = jobs.get(pid, (None, None))
        p = _person_from_row(by_id[pid], pl["home"], work)
        if override:
            _reclass_note(p, p.role)
            p.role = override
        people[pid] = p
        spot[pid] = pl["node"]
    _topup_dependents(city, by_id, placed, dead, homes, people, spot)
    return people, spot


def _topup_dependents(city, by_id, placed, dead, homes, people, spot):
    """D2 top-up: dependents added to the pool AFTER this world was settled — house each with its
    family head once (without disturbing placed adults); thereafter they live via placements.
    Mutates people/spot in place and persists the placement."""
    store = _store()
    for pid, row in by_id.items():
        if pid in placed or pid in dead or not (row.get("mech") or {}).get("dependent"):
            continue
        head = (row["mech"] or {}).get("head")
        home = homes.get(head) or (placed.get(head) or {}).get("home")
        if home is None:                                # head dead/unplaced — skip
            continue
        people[pid] = _person_from_row(row, home, None)
        spot[pid] = home
        store.place_person(_wid(), pid, home, home, None)


def _settle_fresh(city):
    """First settlement of a world: shuffle the pool, group adults into families (one house each),
    house each dependent with their family head, plan jobs by venue gravity, and place everyone.
    Returns (people, spot) and writes placements so re-entry restores the same people."""
    store = _store()
    rng = random.Random(f"settle|{_wid()}")
    rows = _pool().list_people(limit=100000)
    rng.shuffle(rows)
    houses = sorted({h.node for h in city.houses.values()})  # dedup by node — one family, one house
    rng.shuffle(houses)
    hi = iter(houses)
    adults = [r for r in rows if not (r.get("mech") or {}).get("dependent")]
    deps = [r for r in rows if (r.get("mech") or {}).get("dependent")]  # D2: children/elders
    home_of = {}                                         # D1: a family lives in ONE house
    for hh in _households(adults, rng):                  # split adults into families (by surname)
        home = next(hi, None) or rng.choice(houses)
        for pid in hh:
            home_of[pid] = home
    for r in deps:                                       # D2: dependent → their family head's house
        head = (r.get("mech") or {}).get("head")
        home_of[r["id"]] = home_of.get(head) or (next(hi, None) or rng.choice(houses))
    roles = {r["id"]: r["role"] for r in rows}
    jobs = _plan_jobs(city, home_of, roles)              # venue gravity + reclassification
    people, spot = {}, {}
    for r in rows:
        pid = r["id"]
        home = home_of[pid]
        work, override = jobs.get(pid, (None, None))
        node = (city.key_buildings[work].node if work else home)  # a venue worker stands there
        p = _person_from_row(r, home, work)
        if override:
            _reclass_note(p, p.role)
            p.role = override
        people[pid] = p
        spot[pid] = node
        store.place_person(_wid(), pid, node, home, work)
    return people, spot


def _fill_from_pool(city, keynode, kps):
    """Populate the crowd from the NPC BANK (worldgen.people): if the world was already settled,
    restore stored placements (re-planning jobs, topping up new dependents); otherwise settle it
    fresh. Empty bank = broken data supply → hard error (we never build a world without people)."""
    if _pool().people_count() == 0:
        raise RuntimeError("банк NPC (worlds.db:people) пуст — мир не построить; проверь поставку пулов")
    store = _store()
    placed = {pl["npc_id"]: pl for pl in store.placements_for(_wid())}
    if placed and not all(
        pl["node"] in city._xy and pl["home"] in city._xy  # noqa: SLF001
        for pl in placed.values()
    ):
        store.clear_placements(_wid())  # city graph changed — stale nodes; re-place (memory kept)
        placed = {}
    if placed:
        people, spot = _restore_placed(city, placed)
        if people:
            return people, spot
    return _settle_fresh(city)


def _play():
    if _S["city"] is None:
        params = CityParams(seed=_S["seed"], key_buildings=12, river=True, walls=True, segment=16)
        city = generate(params)
        _assign_key_buildings(city)  # user's world: buildings from POOL, no LLM
        _seed_item_pool()  # world items pool (seed-set, data)
        vis = visual(params, interactive=True)  # rich visual + clickable houses
        xy = {n.id: (n.x, n.y) for n in city.nodes()}
        keynode = {
            bid: kb.node for bid, kb in city.key_buildings.items()
        }  # building → NEAREST point (door)
        kps = city.key_points()
        people, spot = _fill_from_pool(city, keynode, kps)  # only bank; empty bank = error
        n2b = {}  # node-point → building (key before homes)
        for bid, kb in city.key_buildings.items():
            n2b.setdefault(kb.node, bid)
        for hid, ho in city.houses.items():  # residential houses also enterable (fact sheet from pool)
            n2b.setdefault(ho.node, hid)
        start = (
            next(
                (keynode.get(p.work) for p in people.values() if p.role == "трактирщик" and p.work),
                None,
            )
            or kps[0]
        )
        _weave_ties(people)  # person ties → real pool people
        _weave_locals(people)  # local-tavern regulars → mild mutual acquaintance
        row = _store().get_pc(_wid()) or {}  # player position SURVIVES restart/deploy
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
            _S["zone"] = row.get("zone")             # and place in hall — also position
    _apply_routine()  # spots = f(time): daily schedule
    return _S["city"], _S["people"], _S["crof"], _S["cr2b"], _S["loc"]


def _look_key(loc, inside) -> str:
    return f"{loc}|{inside or 'out'}"


def _looked_level(loc, inside) -> int:
    """0 = not examined (fog: can't distinguish people/containers), 1 = looked around, 2 = keen check."""
    return int((_S.setdefault("looked", {})).get(_look_key(loc, inside), 0))


def _scene_locinfo(city, loc, bid, inside, plaza):
    """Resolve the scene's display name + kind: inside a building, at its entrance, the town board
    on the plaza, a crossroad, or plain street. Returns (name, kind)."""
    if inside:
        info = _binfo(inside)
        return info["name"], info["kind"]
    if bid:
        return f"у входа: {_binfo(bid)['name']}", "снаружи"
    if plaza is not None and loc == plaza:
        return "Городская доска", "площадь · объявления горожан"
    if city.node_kind(loc) == NodeKind.CROSSROAD:
        return "Перекрёсток", "городская развилка"
    return "Улица", "мостовая меж домов"


def _scene_ambient(here, lvl):
    """Ambient line for the scene: time-of-day, weather, crowd mood, and a one-line event that
    depends on whether the player has looked around yet."""
    return {
        "time": _PHASE_RU[_phase()],
        "weather": "дождь",
        "mood": "оживлённо" if len(here) > 2 else "тихо",
        "event": ("Народ занят своими делами." if here
                  else "Пусто; лишь ветер гуляет меж домов."),
    }


def _scene_folk(vis_here, people):
    """Visible people in the scene → cards (id, display name, role, initial, colour, portrait).
    A stranger shows by descriptor until introduced."""
    return [
        {
            "id": pid,
            "name": _display(pid, people),  # stranger by descriptor, name after introduction
            "role": (
                people[pid].role if (pid in _met() or people[pid].work) else "кто-то из горожан"
            ),
            "init": _display(pid, people)[0].upper(),
            "color": _COLORS[i % len(_COLORS)],
            "portrait": _portrait_url(people[pid], _emo(people[pid].state)),
        }
        for i, pid in enumerate(vis_here)
    ]


def _scene_extras(d, bid, loc, inside, plaza, people, crof):
    """Append conditional scene sections in place: guild board/rank (minting a newcomer's badge),
    the citizens' notice board at the plaza post, and the watch when the player is highly wanted."""
    if bid and bid == _guild_bid():  # in the guild — board, rank, newcomer intake
        d.setdefault("narr", [])
        if not _pc_badge() and not _store().flag_get(_wid(), "guild_mark|pc"):
            _mint_badge(0)
            d["narr"].append("Тебя приняли в гильдию. Вот жетон приключенца (Медь).")
        d["guild_board"], d["guild_news"] = _guild_board(), (_S.get("guild_news") or [])
        d["guild_status"] = _guild_status()
    if plaza is not None and loc == plaza and not inside:  # at the post — citizens' notices
        d["board_ads"] = _board_ads()
        d["board_news"] = _S.get("board_news") or []
    wc = _watch_check(people, crof, loc)  # the watch, at a high wanted level
    if wc:
        d["watch"] = wc


def _scene_rooms(inside, lvl):
    """Rooms of the building the player is in; hidden ones show only on a keen look (lvl 2)."""
    if not inside:
        return []
    return [r for r in _building_rooms(inside) if not (r["access"] == "hidden" and lvl < 2)]


def _scene_dict(city, people, crof, cr2b, loc):
    """Assemble the full scene dict the client renders: place name/kind, fog level, rooms, the
    location block, ambient, the visible folk, and any guild/board/watch extras."""
    role = _role_at(loc, people, crof, cr2b)
    bid = cr2b.get(loc)
    inside = _S.get("inside")
    if inside and inside != bid:  # stepped away from the building → left it
        inside = _S["inside"] = None
        _S["room"] = None
    _mark_seen(bid)  # arrived — learned the place
    plaza = (_S.get("geom") or {}).get("plaza")
    name, kind = _scene_locinfo(city, loc, bid, inside, plaza)
    here = sorted(_here(loc, crof), key=lambda i: (people[i].work is None, i))
    lvl = _looked_level(loc, inside)
    more = 0  # no cap — the scene shows everyone present
    vis_here = here  # basic vision: who is in the room is ALWAYS visible; a keen look reveals HIDDEN things
    room = _S.get("room") if inside else None
    rooms = _scene_rooms(inside, lvl)
    if inside and room:
        name = f"{_binfo(inside)['name']} · {room}"
    d = {
        "loc": loc,
        "inside": inside,
        "room": room,
        "rooms": rooms,
        "enterable": ({"bid": bid, "name": _binfo(bid)["name"]} if (bid and not inside) else None),
        "looked": lvl,
        "here_more": more,
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
        "ambient": _scene_ambient(here, lvl),
        "here": _scene_folk(vis_here, people),
    }
    _scene_extras(d, bid, loc, inside, plaza, people, crof)
    return d


def _watch_check(people, crof, loc):
    """Guard binds: if wanted ≥ threshold AND guard at location — confrontation."""
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
    return out  # board/guild rank — from _scene_dict


# --------------------------------------------- CRAFTING / DURABILITY (slice 2) - #


# ----------------------------------------------- TRADE AND THEFT (slice 2) - #


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
    if ct.get("kind") == "deliver" and ct.get("deliver_item"):  # package handed immediately
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
        if len(steps) > 1:  # multi-step — show progress and current step
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


# --------------------------------- UNIFIED ACTION LOOP (primitive×manner) - #
# No verb buttons: free text → LLM intent → attempt() → world events.
# Manner gates: openly (simple), stealthily (dex vs vigilance, witnesses),
# forcefully (strength vs bravery, fear+anger+witnesses), persuasively (affinity vs nature).

# ------------------------------------------- LIVE LOCATION (mind + LLM) --- #
# NPCs at current location live realistically: each tick EACH chooses via hybrid mind
# (mechanics give drives → LLM chooses IN CHARACTER, writes line and description). Actions
# are real (apply_actions mutates world and memory), feed — what player sees/hears; strangers
# shown by descriptor, name opens via introduction (talk).
_LIVE_GAP = PB["live_gap_s"]  # min. sec between ticks (protection from poll storm)


# need → how it looks 'inside' location (flavor for scene; needs themselves — from society catalog)
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
    """What location satisfies needs — FROM UNIFIED place catalog (society.advertises per
    building fact sheet): same needs ads that bring residents here. Street — novelty/bustle."""
    if not bid:
        return [MItem("уличная суета", 0.15, satisfies="novelty")]
    data = (_store().get_building(_wid(), bid) or {}).get("data") or {}
    out = [
        MItem(_NEED_ITEM.get(need, need), min(0.4, round(rate * 1.8, 2)), satisfies=need)
        for need, rate in society.advertises(data).items()
    ]
    return out or [MItem("уличная суета", 0.15, satisfies="novelty")]


_SQUALOR_HINTS = ("оборван", "грязн", "рвань", "лохмот")  # ragged/filthy clothing tokens


def _npc_surface(p) -> dict:
    """Project a Townsperson's persona onto the visible surface the mind's appraisal reads.

    race — persona race token (default "человек"); squalor [0..1] — grime/disrepair, derived
    from visible wealth (poorer NPCs read dirtier) and bumped up if the clothing text hints at
    rags/filth; marks — visible tokens (scars, brands, insignia, ...) from persona look.
    """
    per = p.persona or {}
    look = per.get("look") if isinstance(per.get("look"), dict) else {}
    squalor = round(min(1.0, max(0.0, 0.55 - p.appearance)), 2)
    clothing = str(look.get("clothing") or "").lower()
    if any(hint in clothing for hint in _SQUALOR_HINTS):
        squalor = round(min(1.0, squalor + 0.35), 2)
    return {
        "race": str(per.get("race") or "человек").strip() or "человек",
        "squalor": squalor,
        "marks": list(look.get("marks") or []),
    }


def _live_build(city, people, crof, cr2b, loc) -> None:
    bid = cr2b.get(loc)
    place = _binfo(bid)["name"] if bid else "улица"
    data = ((_store().get_building(_wid(), bid) or {}).get("data")) if bid else {}
    from aidnd.server.play.engine.zones import assign_zones, building_zones
    from aidnd.worldgen.furnish import zones_for

    _zd, zones = building_zones(bid)
    if not zones and not bid:  # STREET — also location with zones (docs/locations.md)
        street_kind = "площадь" if loc == (_S.get("geom") or {}).get("plaza") else "улица"
        zones = zones_for(street_kind, {}, kind="street")
    ent = "у входа" if bid else "обочина"            # spawn point: door or street edge
    zone_names = {z["id"]: z["name"] for z in zones}
    zone_ids = {v: k for k, v in zone_names.items()}
    w = MWorld()
    if zones:  # WAVE 2: zones = PLACES of mind — move relocates itself, use consumes its zone's resource
        znames = list(zone_names.values())
        w.link(ent, "улица")
        for i, za in enumerate(znames):
            w.link(za, "улица")
            w.link(ent, za)
            for zb in znames[i + 1:]:
                w.link(za, zb)
        if bid:  # building furnishings = REAL items live.db (lazy, idempotent)
            from aidnd.server.play.mechanics.items import _materialize_zones, _zone_stock

            _materialize_zones(bid)
        zone_items: dict = {}                        # place → {name: iid} (loose — can take)
        zone_fixed: dict = {}                        # place → {name: iid} (nailed — can't take)
        for z in zones:
            itms = []
            src = ([(None, o) for o in (z.get("objects") or [])] if not bid
                   else _zone_stock(bid, z["id"]))
            for iid, o in src:
                aff = o.get("afford") or {}
                if aff:
                    need, rate = max(aff.items(), key=lambda kv: kv[1])
                    if need == "fatigue" and z["kind"] not in ("beds", "cell"):
                        need = "comfort"             # bench — rest, but NOT sleep: sleep in bed
                    itms.append(MItem(o["name"], min(0.5, round(rate * 2.2, 2)), satisfies=need))
                if iid:
                    tgt = zone_fixed if o.get("fixed") else zone_items
                    tgt.setdefault(zone_names[z["id"]], {})[o["name"]] = iid
            w.ground[zone_names[z["id"]]] = itms[:6]
        if _phase() == "night":                      # night: street honestly advertises home bed
            w.ground["улица"] = [MItem("путь домой, к постели", 0.55, satisfies="fatigue")]
    else:
        w.link(place, "улица")
        w.ground[place] = _live_affordances(bid)
    hero = _pc_name()
    names = {PLAYER: hero if hero != "Странник" else "чужак"}  # NPCs call by name if they know
    known_by = {
        pid
        for pid in _here(loc, crof)  # who of present ALREADY know player
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
    npc_map: dict = {}  # pid → {thing name: item_id} (thefts real)
    here_all = _here(loc, crof)  # everyone present — no LOD cap (buildings bounded by _building_cap)
    leisure = PB["leisure_social_lift"] if "tavern" in society.kinds_of(data or {}) else 0.0
    for _pid in here_all:                            # leisure venue lifts converse toward acquaintances
        people[_pid].state.venue_social = leisure
    workers = {pid for pid in here_all if people[pid].work == bid}
    zonemap = assign_zones({pid: people[pid].state for pid in here_all}, zones,
                           f"zones|{_wid()}|{bid}|{_phase()}",
                           roles={pid: people[pid].role for pid in here_all},
                           workers=workers) if zones else {}
    for pid in here_all:
        p = people[pid]
        _materialize_npc(pid, "visible")  # present NPCs have real items on them
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
        surf = _npc_surface(p)
        w.add(
            Body(
                id=pid,
                place=(zone_names.get(zonemap.get(pid)) or ent) if zones else place,
                charisma=p.charisma,
                appearance=p.appearance,
                attention=round(rng.uniform(0.45, 0.85), 2),
                loot=loot,
                race=surf["race"],
                squalor=surf["squalor"],
                marks=surf["marks"],
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
    pc_row = _store().get_pc(_wid()) or {}
    w.add(
        Body(
            id=PLAYER,
            place=(zone_names.get(_S.get("zone")) or ent) if zones else place,
            charisma=0.45,
            appearance=min(0.8, 0.25 + coins / 60),
            attention=0.85,
            loot=pc_loot,
            race="человек",
            squalor=float(pc_row.get("squalor") or 0.0),
            marks=[],
        )
    )  # player loot REAL (theft real)
    w.npc_minds = {pid: people[pid].state for pid in here_all}  # minds = same as in bodies (LOD cap)
    w.names = names  # memory writes names, not ids
    w.aliases = {v.lower(): k for k, v in names.items()}
    w.lookup = lambda q: _world_lookup(q, loc)  # tool know: world knowledge on demand
    personas = {}
    for pid in here_all:  # depth: manner/quirk/wants from bank
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
        if pid in known_by:  # acquaintance survives ticks and scene rebuilds
            bits.append(
                f"с гостем ({names[PLAYER]}) вы УЖЕ ЗНАКОМЫ и уже здоровались — "
                "НЕ приветствуй заново и не спрашивай, кто он; продолжай общение по делу"
            )
        if bits:
            personas[pid] = ". ".join(bits)
    here = _here(loc, crof)
    # PRE-ACQUAINTANCE: residents of one town know each other (kin > colleagues > neighbors).
    # Seed only absent ties — lived relations untouched.
    for i, a in enumerate(here_all):
        for b in here_all[i + 1:]:
            pa, pb = people[a], people[b]
            if b in pa.state.relationships or a in pb.state.relationships:
                continue
            sur_a = pa.name.split()[-1] if len(pa.name.split()) > 1 else ""
            sur_b = pb.name.split()[-1] if len(pb.name.split()) > 1 else ""
            if sur_a and sur_a == sur_b:                       # kin
                aff, tr, note = 0.45, 0.5, f"{{}} — моя родня (мы {sur_a}ы)"
            elif pa.work and pa.work == pb.work:               # workplace colleagues
                aff, tr, note = 0.3, 0.35, "{} — работаем бок о бок"
            else:                                              # town neighbors
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
    if todo:  # long-term goal for placed NPC (rare call)

        def plan_one(pid):
            st = people[pid].state
            ag = plan_agenda(st, w, {"roles": roles}, mgr)
            if ag:
                st.agendas.append(ag)

        from concurrent.futures import ThreadPoolExecutor

        from aidnd import config
        with ThreadPoolExecutor(max_workers=config.LIVE_CONCURRENCY) as ex:
            list(ex.map(plan_one, todo))
    prev = _S.get("live") or {}
    prev_places = {pid: b.place for pid, b in (prev.get("world").bodies.items()
                                               if prev.get("world") else {}.items())}
    if zones:
        keep = set(zone_names.values()) | {ent}
        for pid in here_all:
            if prev_places.get(pid) in keep:
                w.bodies[pid].place = prev_places[pid]          # person WHERE THEY SAT, they sit there
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
    """NPC↔NPC talk carries vivid memory — gossip spreads, reputation emerges."""
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
        return  # heard this gossip already
    target_st.memory.add(tale, _mt(), max(0.25, m.importance - 0.15), kind="gossip", about=m.about)


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
    # SILENCE — also signal: hailed stranger, they didn't respond → this is world fact, NPC remembers
    awaiting = lv.get("awaiting") or []
    if awaiting and not lv.pop("pc_spoke", False):
        for pid in awaiting:
            if pid in w.npc_minds:  # kind=note → goes into 'YOUR THOUGHTS' of decisions
                w.npc_minds[pid].memory.add(
                    "я окликнул(а) чужака, но он ПРОМОЛЧАЛ — не хочет говорить, навязываться дальше стыдно",
                    lv["clock"],
                    0.55,
                    kind="note",
                    about=[PLAYER],
                )
        lv["last"][PLAYER] = "молчит — на обращения не отвечает, в разговоры не вступает"
    lv["awaiting"] = []
    # what stranger is DOING NOW — part of world: NPCs decide themselves whether to butt in (character, not timer)
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
    # WAVE 2: position = BODY in zone-place (mind moves itself via move); zonemap — derivative
    zones_l = lv.get("zones") or []
    zmap = lv.setdefault("zonemap", {})
    zone_feed = []
    if zones_l:
        pbody = w.bodies.get(PLAYER)
        if pbody is not None:  # player position — from their state (click on map/freeform)
            pbody.place = lv["zone_names"].get(_S.get("zone")) or lv.get("ent", "у входа")
        for pid in list(w.npc_minds):
            zmap[pid] = lv["zone_ids"].get(w.bodies[pid].place)
        zmap[PLAYER] = _S.get("zone")
    zname_of = {}
    if zones_l and w.bodies.get(PLAYER) and w.bodies[PLAYER].place != lv.get("ent", "у входа"):
        zname_of[PLAYER] = w.bodies[PLAYER].place
    if lv["clock"] >= 3 and "незнакомец" in str(roles.get(PLAYER, "")):
        # stranger NOTICED — scene state, not cooldown: no longer main event of hall
        roles[PLAYER] = ("чужак, который тут уже посидел — к нему пригляделись и вернулись "
                         "к своим делам; лезть к нему без причины незачем")
    if zname_of.get(PLAYER):
        roles[PLAYER] = f"{roles.get(PLAYER, 'чужак')}; он сейчас — {zname_of[PLAYER]}"
    news = [str(x) for x in ((_S.get("guild_news") or []) + (_S.get("board_news") or []))[-2:]]
    news += _deeds.town_talk(lv["names"], limit=2)     # fresh TOWN ACTS — into gossip
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

    # ── CONDUCTOR: LLM turn to those who HAVE REASON (debt > emotion > need > talk > background)
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
            imp, why = 2.6, "слово"                    # deadline reached — given promise pulls
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
    # AUTHOR DECISION (2026-07-07): ALL present go through LLM, latency
    # unimportant yet. Conductor stays ORDERED (impulse → anti-chorus waves), not selection/cap.
    actors = ranked_imp
    background: list = []
    ctx["convs"] = {pid: b for pid in actors
                    if (b := conv_block(lv, pid, lv["names"]))}
    if salient:
        ctx["event"] = salient
    ctx["oaths"] = oaths

    def think_one(pid):  # inside wave — parallel; waves see previous claims
        st = w.npc_minds[pid]
        _decay_needs(st)
        _decay_emotion(st)
        advance_agendas(st, w)  # long-term goals advance
        return pid, decide_hybrid(st, w, mind_perceive(st, w), mgr, ctx)

    def _claim(pid, d) -> str:
        """Actor's claim for next wave: what they DOING/SAYING RIGHT NOW."""
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

    from aidnd import config

    # ANTI-CHORUS: decision waves — leader (highest impulse) first, retinue sees their claim.
    # Wave 2 (the retinue) runs concurrently, LIVE_CONCURRENCY calls in flight (no client lock).
    decisions: dict = {}
    waves = [actors[:1], actors[1:]] if len(actors) > 1 else [actors]
    with ThreadPoolExecutor(max_workers=config.LIVE_CONCURRENCY) as ex:
        for wave in waves:
            if not wave:
                continue
            ctx["now"] = [c for pid_ in decisions
                          if (c := _claim(pid_, decisions[pid_]))]
            decisions.update(ex.map(think_one, wave))
    ctx.pop("now", None)

    # BACKGROUND LIVE without LLM: busy with zone item, needs close, hall sees
    bg_feed = []
    rng_bg = random.Random(f"bg|{lv['clock']}")
    busy: set = set()                                 # one poker — one stirring
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

    # ── detailed scene log (data/debug/play.log): 'why' of each NPC per tick ──
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
    topics = lv.setdefault("topics", [])  # anti-echo REMEMBERS past ticks (signature tail)
    pc = _pc()

    def _say_ok(txt: str) -> bool:
        sig = frozenset(list(_tokens_ru(txt))[:6])
        if sig and any(len(sig & s) >= max(2, len(sig) // 2 + 1) for s in topics):
            return False  # near duplicate already spoken — 'beaten topic'
        topics.append(sig)
        del topics[:-12]  # remember last ~4 talk ticks
        return True

    used_items: set = set()                           # physics: one item — one hands per tick
    for pid in actors:  # apply sequentially (honest order)
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
            if alt is not None:                       # mug taken — takes neighbor
                a["item"] = alt.name
                used_items.add((w.bodies[pid].place, alt.name.lower()))
            else:
                a["tool"] = "wait"                    # all taken — waits turn
        st = w.npc_minds[pid]
        before = {vid: {i.name for i in b.loot} for vid, b in w.bodies.items() if vid != pid}
        my_place = w.bodies[pid].place
        gr_before = {i.name for i in (w.ground.get(my_place) or [])}
        evs = apply_actions(d.get("actions") or [], st, w, lv["clock"])
        for nm in gr_before - {i.name for i in (w.ground.get(my_place) or [])}:
            iid = (lv.get("zone_items") or {}).get(my_place, {}).pop(nm, None)
            if iid:                                  # picked up venue item — it's now THEIRS
                _store().inv_move(_wid(), iid, pid)
                st.memory.add(f"прибрал(а) к рукам: {nm}", lv["clock"], 0.5)
        for vid, names_before in before.items():  # THEFTS REAL (from player and NPC↔NPC)
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
        spoke = []  # speech — also ACTION: goes into last/hist/memory
        for a in d.get("actions") or []:
            if isinstance(a, dict) and a.get("tool") == "say" and str(a.get("text") or "").strip():
                tgt = str(a.get("to") or "")
                tid = (w.aliases or {}).get(tgt.strip().lower(), tgt)
                txt = str(a["text"])[:180]
                if not _say_ok(txt):  # line cap / anti-echo — this one silent
                    continue
                said = True
                if tid == PLAYER:  # decision 'talk to stranger' — NPC's own
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
                    )  # will stranger answer — learn next tick
                else:
                    conv_note_say(lv, pid, tid, txt, w.bodies[pid].place)
                    zn_by_place = {z["name"]: z for z in zones_l}
                    sp_place = w.bodies[pid].place
                    pl_place = w.bodies[PLAYER].place if PLAYER in w.bodies else sp_place
                    ev = _S.get("eaves") or {}
                    boost = 1 if (ev.get("place") == sp_place
                                  and lv["clock"] <= ev.get("until", -1)) else 0
                    tier, disp, mw = _overheard(
                        txt, zn_by_place.get(pl_place, {"id": pl_place}),
                        zn_by_place.get(sp_place, {"id": sp_place}),
                        sp_place, f"hear|{lv['clock']}|{pid}", boost=boost)
                    if tier is None:
                        lv["murmur"] = lv.get("murmur", 0) + 1
                    else:
                        feed.append({"k": "speech", "who": who, "tier": tier,
                                     "to": _display(tid, people) if tid in people else tgt,
                                     "text": disp})
                        pc.memory.add(f"слышал в «{lv['place']}»: {who} — {disp[:90]}",
                                      _mt(), mw, kind="heard", about=[pid])
                    spoke.append(f"сказал(а) {lv['names'].get(tid, tgt)}: «{txt[:50]}»")
                    if tid in w.npc_minds and ((not zones_l)
                                               or w.bodies[tid].place == w.bodies[pid].place):
                        _gossip(st, lv["names"].get(pid, pid), w.npc_minds[tid])
                    if tid in w.npc_minds:  # address reaches through hall too (hailed)
                        w.npc_minds[tid].memory.add(
                            f"ко мне обратился {who}: «{txt[:80]}» — стоит ответить",
                            lv["clock"],
                            0.55,
                            about=[pid],
                        )
        for a in d.get("actions") or []:                 # NPC PROMISE → world obligation
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
            lv["salient"] = f"{who} бросается в драку!"     # event: hall will flinch next tick
        # FOOD NOT FREE: use food with venue worker = order with payment
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
        acted = "; ".join(evs + spoke)  # NPC REMEMBERS both acts and words — no repeat
        lv["last"][pid] = acted[:110] or "—"
        lv["hist"].setdefault(pid, []).append(acted[:80])
        does = (d.get("does") or "").strip()
        if does and not said:  # line itself carries moment — don't duplicate
            feed.append({"k": "deed", "who": who, "text": does[:150]})
    if lv.pop("murmur", 0) and lv["clock"] % 3 == 0:
        feed.append({"k": "deed", "who": "зал", "text": "за столами гудит негромкий говор"})
    if zones_l:
        for pid in order:
            zmap[pid] = lv["zone_ids"].get(w.bodies[pid].place)
    lv["clock"] += 1
    _gt_add(PB["live_tick_min"])  # world tick (game minutes)
    _pc_save()
    for pid in order:  # lived experience survives restart
        _npc_save(pid)
    return feed, address


def _world_tick() -> dict:
    """★ WORLD TICK — only point where 'world moved'. Called at end of processing ANY player
    action (turn-based, like table). Two layers:
      1) PASSIVE world — routine of ALL residents from needs/character/time + daily events
         (aidnd.society → worldsim.routine_step; sync in _play/_apply_routine,
         idempotent per day phase);
      2) LIVE scene — who's near player, think/talk/act (mind + LLM, _live_tick).

    GAME CYCLE (each @router.post /api/play/*):
        player action → _gt_add(action time) → world mutation → _world_tick() → scene response.
    """
    city, people, crof, cr2b, loc = _play()  # _play → _apply_routine: passive world synced
    lv = _S.get("live")
    if not lv or lv["loc"] != loc or lv.get("who") != frozenset(_here(loc, crof)):
        _live_build(city, people, crof, cr2b, loc)
    try:
        feed, address = _live_tick(people)  # live scene: those nearby
    except (LLMUnavailable, LLMBadOutput):  # no model won't pretend — honest error to player
        raise
    except Exception:  # noqa: BLE001 — other tick bugs don't drop the player's action
        import logging

        logging.getLogger("aidnd").warning("live tick failed", exc_info=True)
        return {"feed": [], "address": []}
    return {"feed": feed, "address": address}
