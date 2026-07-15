"""Game loop — WORLD AND ORCHESTRATION: generation, scene, movement, dialogue, action, live location + HTTP endpoints.

mechanics/ layer (see docs/loop.md).
"""

from __future__ import annotations

import random

from fastapi import Request

from aidnd import society
from aidnd.mind import Body, advance_agendas
from aidnd.mind import Item as MItem
from aidnd.mind import World as MWorld
from aidnd.mind import perceive as mind_perceive
from aidnd.mind.llm_agent import apply_actions, decide_hybrid, plan_agenda
from aidnd.mind.tick import _decay_emotion, _decay_needs
from aidnd.server.play.engine.core import (
    _PHASE_RU,
    _S,
    PB,
    PLAYER,
    _binfo,
    _city_name,
    _display,
    _gt,
    _gt_add,
    _here_settled,
    _model,
    _mt,
    _npc_save,
    _pc,
    _pc_name,
    _pc_remember,
    _pc_save,
    _phase,
    _scene_descriptors,
    _store,
    _tokens_ru,
    _topics_for,
    _wid,
    router,
)
from aidnd.server.play.engine.loop.routine import _apply_routine as _apply_routine
from aidnd.server.play.engine.loop.routine import _world_events as _world_events
from aidnd.server.play.engine.loop.tick import _world_tick as _world_tick
from aidnd.server.play.engine.loop.tick import _world_tick_fast as _world_tick_fast
from aidnd.server.play.engine.resolve import _STANCE, _VOICE, _world_lookup
from aidnd.server.play.engine.scene.view import _scene_ambient as _scene_ambient
from aidnd.server.play.engine.scene.view import _scene_dict as _scene_dict
from aidnd.server.play.engine.scene.view import _scene_extras as _scene_extras
from aidnd.server.play.engine.scene.view import _scene_folk as _scene_folk
from aidnd.server.play.engine.scene.view import _scene_locinfo as _scene_locinfo
from aidnd.server.play.engine.scene.view import _scene_rooms as _scene_rooms
from aidnd.server.play.engine.scene.vision import _look_key as _look_key
from aidnd.server.play.engine.scene.vision import _looked_level as _looked_level
from aidnd.server.play.engine.scene.vision import _watch_check as _watch_check
from aidnd.server.play.engine.sound import audibility, audible_ambient, overheard_line, room_center
from aidnd.server.play.engine.worldbuild.assembly import _fill_from_pool as _fill_from_pool
from aidnd.server.play.engine.worldbuild.assembly import _play as _play
from aidnd.server.play.engine.worldbuild.assembly import _settle_fresh as _settle_fresh
from aidnd.server.play.engine.worldbuild.building import (
    _building_containers as _building_containers,
)
from aidnd.server.play.engine.worldbuild.building import _building_keys as _building_keys
from aidnd.server.play.engine.worldbuild.building import _building_rooms as _building_rooms
from aidnd.server.play.engine.worldbuild.building import _res_binfo as _res_binfo
from aidnd.server.play.engine.worldbuild.geom import _build_geom as _build_geom
from aidnd.server.play.engine.worldbuild.geom import _scene_zones as _scene_zones
from aidnd.server.play.engine.worldbuild.jobs import _WORKCAP as _WORKCAP
from aidnd.server.play.engine.worldbuild.jobs import _assign_key_buildings as _assign_key_buildings
from aidnd.server.play.engine.worldbuild.jobs import _plan_jobs as _plan_jobs
from aidnd.server.play.engine.worldbuild.person import _person_from_row as _person_from_row
from aidnd.server.play.engine.worldbuild.population import _households as _households
from aidnd.server.play.engine.worldbuild.population import _reclass_note as _reclass_note
from aidnd.server.play.engine.worldbuild.population import _restore_placed as _restore_placed
from aidnd.server.play.engine.worldbuild.population import _surname as _surname
from aidnd.server.play.engine.worldbuild.population import _topup_dependents as _topup_dependents
from aidnd.server.play.engine.worldbuild.ties import _weave_locals as _weave_locals
from aidnd.server.play.engine.worldbuild.ties import _weave_ties as _weave_ties
from aidnd.server.play.mechanics.contracts import (
    _ct_cur,
    _ct_steps,
    _step_desc,
)
from aidnd.server.play.mechanics.items import (
    _materialize_npc,
    _pc_coins,
)


def _overheard(text, player_zone, speaker_zone, zone_name, seed, boost=0):
    """(tier_int|None, display_text, mem_weight) for a conversation line the player
    overhears — spatial audibility tier drives the fidelity (docs/sound-attention.md)."""
    tier = audibility(player_zone, speaker_zone, PB["sound_voice"], boost=boost)
    if tier is None:
        return None, "", 0.0
    disp, w = overheard_line(text, tier, zone_name, seed)
    return int(tier[1]), disp, w


def _player_in_scene(zones_l, pid, w, lv) -> bool:
    """Gate: may `pid` address the player DIRECTLY ('— тебе')? Only if the player is actually
    present in the scene (inside the building, not merely approaching/at the door) AND within
    conversational proximity — same zone, or L1 (near) via the existing audibility() tiering.
    A miss doesn't silence the NPC — their line still falls through to the overheard/ambient
    path below, just not as a direct greeting."""
    if lv.get("bid") and not _S.get("inside"):
        return False  # scene is a building interior but player hasn't stepped in yet
    if PLAYER not in w.bodies:
        return False
    if not zones_l:
        return True  # no sub-zones (single-room venue/street) — one conversational space
    zn_by_place = {z["name"]: z for z in zones_l}
    p_place, s_place = w.bodies[PLAYER].place, w.bodies[pid].place
    pz = zn_by_place.get(p_place)
    if pz is None:  # no spot picked yet (still at the door) — acoustically at the room's edge,
        pz = room_center(zones_l) or {"id": p_place}  # not in a void: the host CAN come greet
    tier = audibility(pz, zn_by_place.get(s_place, {"id": s_place}), PB["sound_voice"])
    return tier == "L1"


def _idle_ambient(w, zones_l, order, zone_ids) -> str:
    """Audible soundscape around the player's CURRENT position — authored zone sources +
    occupancy crowd murmur (sound/ambient.py). Falls back to the room's average centroid when
    the player hasn't picked a spot yet. '' if nothing audible (no zones/unplaced)."""
    if not zones_l or PLAYER not in w.bodies:
        return ""
    lz = (next((z for z in zones_l if z.get("id") == zone_ids.get(w.bodies[PLAYER].place)), None)
          or room_center(zones_l))
    if lz is None:
        return ""
    occ: dict = {}
    for pid in order:
        zid = zone_ids.get(w.bodies[pid].place)
        if zid:
            occ[zid] = occ.get(zid, 0) + 1
    return "; ".join(audible_ambient(zones_l, lz, occ))


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


_KIND_RU = {  # improvised-contract kind → Russian verb (accept summary, no bare English leaking)
    "bring": "принести",
    "deliver": "доставить",
    "visit": "посетить",
    "befriend": "подружиться",
    "dead": "устранить",
}


def _accept_summary(ct: dict) -> str:
    """Russian-first accept line: emergent (sift) contracts speak through their own pitch;
    improvised ones get a Russian kind word and drop the want part when there is none
    (never leaks a bare English kind or the literal "None")."""
    giver_name = ct.get("giver_name", "")
    pitch = (ct.get("pitch") or "").strip()
    if pitch:
        return f"взялся за дело для {giver_name}: {pitch[:120]}"
    kind_ru = _KIND_RU.get(ct.get("kind"), ct.get("kind") or "")
    want = ct.get("want") or ct.get("target_name")
    where = ct.get("where") or ""
    out = f"взялся за дело для {giver_name}: {kind_ru}"
    if want:
        out += f" — {want}"
    if where:
        out += f" ({where})"
    return out


def _accept_contract(cid: str, ct: dict) -> str | None:
    """Shared accept path (offered/board): flips status→active, bumps sift arc to 'active',
    hands over an immediate delivery package, and writes the one true journal/remember line.
    Both contract_accept (private offers) and board_take (public sift postings) call this so the
    beat/journal bookkeeping never diverges between the two entry points."""
    data = {k: v for k, v in ct.items() if k not in ("id", "status")}
    if ct.get("src") == "sift":
        data["arc"] = {"beat": "active"}             # emergent: foreshadow/offered → active
    _store().save_contract(_wid(), cid, "active", data)
    note = None
    if ct.get("kind") == "deliver" and ct.get("deliver_item"):  # package handed immediately
        _store().inv_move(_wid(), ct["deliver_item"], "pc")
        note = f"«{ct['want']}» ложится в твою сумку — доставь по адресу."
    summary = _accept_summary(ct)
    _pc_remember(summary, 0.6, about=[ct["giver"]])
    from aidnd.server.play.engine.journal import j_beat
    j_beat(cid, "accept", {
        "kind": ct.get("kind"), "want": ct.get("want"), "target_name": ct.get("target_name"),
        "where": ct.get("where", ""), "reward": ct.get("reward"),
        "giver_name": ct.get("giver_name") or _S["people"][ct["giver"]].name,
    })
    return note


@router.post("/api/play/contract_accept")
async def contract_accept(request: Request):
    cid = (await request.json()).get("id")
    ct = next((c for c in _store().contracts(_wid(), "offered") if c["id"] == cid), None)
    if not ct:
        return {"error": "уговора нет"}
    note = _accept_contract(cid, ct)
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


def _work_lift(pid, workers, info: str, gt: int) -> float:
    """On-shift 'keep working' lift: a worker at their workplace during open hours (docs/sound-attention.md
    Increment 6). Returns the purpose lift magnitude, else 0.0."""
    from aidnd.server.play.engine import open_hours

    if pid in workers and open_hours.is_open(info or "", gt):
        return PB["workplace_purpose_lift"]
    return 0.0


_PC_SAID_TIER = {"L1": 1.0, "L2": 0.65, "L3": 0.4}


def _pc_said_impulse(tier: str) -> float:
    """Tier-scaled pull to react to the player's spoken line — near louder than far, and never
    above a real event/debt (so a busy NPC keeps to its business). 0.0 if unheard/unknown tier."""
    return round(PB["pc_said_impulse"] * _PC_SAID_TIER.get(tier, 0.0), 2)


def _pc_heard(pz, order, place_of, zn_by_place, zones_l) -> dict:
    """Present NPCs who hear the player's spoken line, tier by audibility. Zoneless venue (single
    conversational space) → everyone hears at 'L1'."""
    heard = {}
    for pid in order:
        if not zones_l:
            heard[pid] = "L1"
            continue
        nz = zn_by_place.get(place_of(pid), {"id": place_of(pid)})
        t = audibility(pz, nz, PB["sound_voice"]) if pz else None
        if t:
            heard[pid] = t
    return heard


def _pick_rumor(pool, seed_key, heat: dict, hot: float):
    """Rotated pick from the NON-hot subset of `pool` (a subject the room has chewed drops out).
    None if the pool is empty or every subject is hot."""
    avail = [r for r in pool if heat.get(r, 0.0) < hot]
    return avail[hash(seed_key) % len(avail)] if avail else None


def _afford_need(afford: dict, zone_kind: str, is_post: bool) -> tuple[str | None, float]:
    """(need, rate) a zone object should satisfy: at a worker's post, purpose wins over
    comfort/etc (so a hot forge surfaces WORK, not just warmth) — rate is purpose's OWN
    magnitude, not the need it beat. Else the existing max-afford rule (rate = that max),
    with fatigue remapped to comfort outside beds/cell (bench = rest, not sleep)."""
    if not afford:
        return None, 0.0
    if is_post and afford.get("purpose", 0) > 0:      # a worker's post surfaces WORK, not comfort
        return "purpose", afford["purpose"]
    need, rate = max(afford.items(), key=lambda kv: kv[1])
    if need == "fatigue" and zone_kind not in ("beds", "cell"):
        need = "comfort"
    return need, rate


_RU_COUNT = {1: "один", 2: "двое", 3: "трое", 4: "четверо", 5: "пятеро", 6: "шестеро"}


def _ru_count(n: int) -> str:
    """Small RU count word for the churn summary; fallback «N человек» past шестеро."""
    return _RU_COUNT.get(n, f"{n} человек")


def _salient(pid, people, active_givers: set, active_targets: set) -> bool:
    """Is this joiner/leaver worth a NAMED churn line? All signals are real fields (no invention):
    acquaintance (PLAYER∈relationships, same signal as _live_build known_by), an active/offered
    contract's giver or target, a guard, or a wounded person. NB: max_hp lives on the CONFIG
    (NpcState has no max_hp attr)."""
    p = people.get(pid)
    if p is None:
        return False
    st = p.state
    return (
        PLAYER in st.relationships
        or pid in active_givers
        or pid in active_targets
        or p.role == "стражник"
        or st.hp < st.config.max_hp
    )


def _churn_items(prev_who, here, people, active_givers: set, active_targets: set) -> list[dict]:
    """Diff prev occupant set vs new → feed items: NAMED for salient (capped churn_named_max per
    direction), the rest folded into ONE summary line per non-empty direction. Feed shape
    {k:'deed', who, text} — exactly what scene_digest._event_lines consumes. Pure; no LLM."""
    prev_s, here_s = set(prev_who or ()), set(here or ())
    joined = [p for p in (here_s - prev_s) if p in people]
    left = [p for p in (prev_s - here_s) if p in people]
    cap = PB["churn_named_max"]
    out: list[dict] = []
    for pids, arriving in ((joined, True), (left, False)):
        if not pids:
            continue
        sal = [q for q in pids if _salient(q, people, active_givers, active_targets)]
        named = sal[:cap]
        for q in named:
            verb = "вошёл(ла) в зал" if arriving else "поднялся(лась) и вышел(ла)"
            hint = ", ищет тебя взглядом" if (q in active_givers and arriving) else ""
            out.append({"k": "deed", "who": _display(q, people), "pid": q,
                        "text": f"{verb}{hint}"})
        rest = len(pids) - len(named)                     # background + salient over the cap
        if rest == 1:                                      # singular grammar: «вошёл»/«вышел» один
            phrase = "народ прибывает — вошёл один" if arriving else "зал редеет — вышел один"
        elif rest > 1:
            phrase = (f"народ прибывает — вошли {_ru_count(rest)}" if arriving
                      else f"зал редеет — вышли {_ru_count(rest)}")
        else:
            phrase = None
        if phrase:
            out.append({"k": "deed", "who": "зал", "text": phrase})
    return out


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
            is_post = bool(z.get("post"))
            src = ([(None, o) for o in (z.get("objects") or [])] if not bid
                   else _zone_stock(bid, z["id"]))
            for iid, o in src:
                aff = o.get("afford") or {}
                if aff:
                    need, rate = _afford_need(aff, z["kind"], is_post)
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
        for pid in _here_settled(loc, crof)  # who of present ALREADY know player (settled only)
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
    here_all = _here_settled(loc, crof)  # everyone SETTLED present — no LOD cap (buildings bounded by _building_cap)
    leisure = PB["leisure_social_lift"] if "tavern" in society.kinds_of(data or {}) else 0.0
    workers = {pid for pid in here_all if people[pid].work == bid}
    _bname = _binfo(bid)["name"] if bid else ""       # 'Кузница «…»' — matches open_hours by type substring
    _now_gt = _gt()
    for _pid in here_all:                            # leisure venue lifts converse toward acquaintances
        people[_pid].state.venue_social = leisure
        people[_pid].state.on_shift = _work_lift(_pid, workers, _bname, _now_gt) if bid else 0.0
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
    here = _here_settled(loc, crof)
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
    # NB: NPC agenda planning is NOT done here — _live_build runs on the FAST enter/move path
    # (_world_tick_fast) and must never block on LLM calls. Missing agendas are planned lazily in
    # _live_tick (the streamed /live turn, behind the "…"), so entering a building is instant.
    prev = _S.get("live") or {}
    # ── Inc1: churn as a feed QUEUE — diff prev occupant set vs now (same scene only). Never
    # assign-overwrite: undrained items from a prior rebuild (act/say never drained them — the
    # client only calls /api/play/live on live_pending) survive the rebuild; the same-loc gate
    # only gates whether NEW items get generated this rebuild. _live_tick pops the whole queue
    # atomically exactly once (line ~1151).
    churn: list = list(prev.get("churn") or [])
    if prev.get("loc") == loc and prev.get("who"):
        cs = _store().contracts(_wid(), "active") + _store().contracts(_wid(), "offered")
        givers = {c["giver"] for c in cs if c.get("giver")}
        targets = {c["target"] for c in cs if c.get("target")}
        churn.extend(_churn_items(prev["who"], frozenset(here), people, givers, targets))
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
        "bid": bid,  # the node's building mapping (ANY node tied to a building, incl. its street
                     # door) — NOT interior-only; whether the player has stepped in lives in _S["inside"]
        "place": place,
        "ts": 0.0,
        "who": frozenset(here),
        "churn": churn,          # Inc1: prepended to the feed by _live_tick, narrated by scene_digest
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


# Salience by REASON, not by a numeric threshold: these impulse-labels mean the NPC has a
# concrete reason to act THIS tick (a live event, an owed answer, a due promise, a foreshadow
# beat, a hot emotion, or overhearing the player) → it always gets an LLM turn, never rotated
# out. The rest («беседа»/«нужда»/«агенда»/«фон») join the staggered background round-robin.
_MUST_WHY = frozenset({"событие", "долг ответа", "слово", "тень дела", "эмоция", "услышал чужака"})


def _active_budget(present: int) -> int:
    """LOD: how many NPCs get an LLM decision this tick, by crowd size.
    ≤ live_full_upto → everyone; else ~ratio of the crowd, capped. (Salient actors bypass this.)"""
    import math
    if present <= PB["live_full_upto"]:
        return present
    return max(PB["live_full_upto"],
               min(PB["live_active_cap"], int(math.ceil(present * PB["live_active_ratio"]))))


def _select_actors(ranked_imp: list, impulses: dict, lv: dict) -> list:
    """Pick this tick's LLM actors (LOD layers, docs/sound-attention.md). NPCs with a concrete
    REASON to act (impulse label in _MUST_WHY — event/owed-answer/promise/foreshadow/emotion/
    overheard-player) ALWAYS think; the reasonless background crowd («беседа»/«нужда»/«агенда»/
    «фон») is staggered round-robin via lv['rot_cursor'] so nobody starves. This is
    level-of-detail rotation, NOT a behavior cap — non-selected NPCs still live via the cheap
    code path (needs/emotions/agendas advance). Returns actors in impulse order."""
    present = len(ranked_imp)
    budget = _active_budget(present)
    if present <= budget:
        return ranked_imp
    must = {p for p in ranked_imp if impulses[p][1] in _MUST_WHY}
    bg = sorted((p for p in ranked_imp if p not in must), key=str)  # stable order for fair rotation
    slots = max(0, budget - len(must))
    if bg and slots < len(bg):
        cur = lv.get("rot_cursor", 0) % len(bg)
        picked = {bg[(cur + i) % len(bg)] for i in range(slots)}
        lv["rot_cursor"] = (cur + slots) % len(bg)                 # advance — next tick rotates onward
    else:
        picked = set(bg)
    keep = must | picked
    return [p for p in ranked_imp if p in keep]                    # impulse order preserved for waves


def _gname(it) -> str:                                     # some items carry a dict/odd name — show clean
    nm = it.get("name")
    return nm if isinstance(nm, str) else (nm.get("item", "вещь") if isinstance(nm, dict) else str(nm))


def _seller_good(pid):
    """The best sellable good an NPC carries (store inventory), or None."""
    store, wid = _store(), _wid()
    rows = [(r["item_id"], store.get_item(r["item_id"])) for r in store.inventory(wid, pid)]
    goods = [(i, it) for i, it in rows if it and it.get("kind") not in ("key", "coin", "document")]
    return max(goods, key=lambda x: x[1].get("worth", 1)) if goods else None


def _market_view(order, people, lv) -> list:
    """What co-present NPCs offer for sale — fed into buyers' decisions so the mind can CHOOSE to buy."""
    out = []
    for pid in order:
        if pid not in people:
            continue
        good = _seller_good(pid)
        if not good:
            continue
        _iid, it = good
        out.append({"pid": pid, "name": lv.get("names", {}).get(pid, pid),
                    "good": _gname(it), "price": max(1, int(it.get("worth", 1)))})
    return out


def _npc_trade_step(people, order, decisions, lv, feed) -> None:
    """Emergent NPC↔NPC trade + haggle (spec: 2026-07-12-npc-trade-haggle-design).
    (1a) OPEN deals from the mind's OWN `buy` actions (intentional — the LLM chose it, that choice IS the
    want signal); (1b) a light background hum from commercial agendas keeps trade visible when minds are
    preoccupied with needs. (2) ADVANCE each open haggle one round (offers voiced as speech, converging by
    trait-driven concession) and SETTLE it in the real store, or walk. Numbers are code-owned."""
    from aidnd.server.play.mechanics.haggle import (
        concession,
        deal_corridor,
        haggle_tick,
        open_deal,
        settle,
    )

    haggles = lv.setdefault("haggle", {})
    present, store, wid = set(order), _store(), _wid()
    names = lv.get("names", {})
    name2pid = {str(names.get(p, p)).lower(): p for p in order}

    def _resolve(nm):                                      # LLM seller name → present pid (exact, else fuzzy)
        s = str(nm or "").strip().lower()
        if not s:
            return None
        return name2pid.get(s) or next((p for lbl, p in name2pid.items() if s in lbl or lbl in s), None)

    in_deal = {d["buyer"] for d in haggles.values()} | {d["seller"] for d in haggles.values()}
    for buyer in order:                                    # (1) open from the mind's own buy actions
        if buyer in in_deal or buyer not in people:
            continue
        for a in (decisions.get(buyer) or {}).get("actions") or []:
            if not (isinstance(a, dict) and a.get("tool") == "buy"):
                continue
            seller = _resolve(a.get("seller"))
            if not seller or seller == buyer or seller in in_deal or seller not in people:
                continue
            good = _seller_good(seller)
            if not good:
                continue
            iid, it = good
            stb, sts = people[buyer].state, people[seller].state
            coins = store.purse_get(wid, buyer)
            cor = deal_corridor(it.get("worth", 1), sts.needs, sts.config.traits,
                                stb.needs, stb.config.traits, PB["haggle_wants_chosen"])
            if not cor or coins < cor[0]:
                continue
            deal = open_deal(cor[0], cor[1], PB["haggle_patience"])
            deal.update({"buyer": buyer, "seller": seller, "item_id": iid, "good": _gname(it),
                         "s_conc": concession(sts.needs, sts.config.traits, "seller",
                                              PB["haggle_s_base"], PB["haggle_b_base"]),
                         "b_conc": concession(stb.needs, stb.config.traits, "buyer",
                                              PB["haggle_s_base"], PB["haggle_b_base"])})
            haggles[f"{buyer}|{seller}|{iid}"] = deal
            in_deal.update((buyer, seller))
            break                                          # one deal per buyer per tick

    for buyer in order:                                    # (1b) background hum from commercial agendas
        if buyer in in_deal or buyer not in people:
            continue
        stb = people[buyer].state
        ag = (stb.agendas[0].summary if stb.agendas else "").lower()
        if not any(k in ag for k in ("куп", "выкуп", "накоп", "монет", "долг", "лавк", "дело", "товар")):
            continue
        if random.Random(f"bgtrade|{buyer}|{lv['clock']}").random() > PB["haggle_bg_p"]:
            continue
        coins = store.purse_get(wid, buyer)
        for seller in order:
            if seller == buyer or seller in in_deal or seller not in people:
                continue
            good = _seller_good(seller)
            if not good:
                continue
            iid, it = good
            sts = people[seller].state
            cor = deal_corridor(it.get("worth", 1), sts.needs, sts.config.traits,
                                stb.needs, stb.config.traits, PB["haggle_wants"])
            if not cor or coins < cor[0]:
                continue
            deal = open_deal(cor[0], cor[1], PB["haggle_patience"])
            deal.update({"buyer": buyer, "seller": seller, "item_id": iid, "good": _gname(it),
                         "s_conc": concession(sts.needs, sts.config.traits, "seller",
                                              PB["haggle_s_base"], PB["haggle_b_base"]),
                         "b_conc": concession(stb.needs, stb.config.traits, "buyer",
                                              PB["haggle_s_base"], PB["haggle_b_base"])})
            haggles[f"{buyer}|{seller}|{iid}"] = deal
            in_deal.update((buyer, seller))
            break

    for key in list(haggles):                              # (2) advance each open deal one round
        deal = haggles[key]
        buyer, seller, iid = deal["buyer"], deal["seller"], deal["item_id"]
        if (buyer not in present or seller not in present
                or not any(r["item_id"] == iid for r in store.inventory(wid, seller))):
            del haggles[key]                               # a party left, or the good is gone → deal dies
            continue
        s_disp, b_disp = _display(seller, people), _display(buyer, people)
        feed.append({"k": "speech", "who": s_disp, "tier": 1, "to": b_disp,
                     "text": f"— За «{deal['good']}»? {int(round(deal['ask']))}."})
        feed.append({"k": "speech", "who": b_disp, "tier": 1, "to": s_disp,
                     "text": f"— {int(round(deal['bid']))}, не больше."})
        status, price = haggle_tick(deal, deal["s_conc"], deal["b_conc"], PB["haggle_gap_eps"])
        if status == "settle" and store.purse_get(wid, buyer) >= price:
            settle(store, wid, buyer, seller, iid, price)
            feed.append({"k": "deed", "who": b_disp, "pid": buyer,
                         "text": f"отсчитывает {price} зм — «{deal['good']}» переходит из рук в руки"})
            people[buyer].state.memory.add(f"купил «{deal['good']}» за {price} зм", lv["clock"], 0.5)
            people[seller].state.memory.add(f"продал «{deal['good']}» за {price} зм", lv["clock"], 0.5)
            del haggles[key]
        elif status == "settle":
            feed.append({"k": "deed", "who": b_disp, "text": "шарит по карманам — монет не хватило, сделка сорвалась"})
            del haggles[key]
        elif status == "walk":
            feed.append({"k": "deed", "who": "зал", "text": f"{b_disp} и {s_disp} не сошлись в цене — расходятся"})
            del haggles[key]


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
    # LAZY AGENDA PLANNING (moved off the fast enter/move path): present NPCs without a
    # long-term goal get one here — inside the streamed /live turn, so entering never blocks.
    todo = [pid for pid in order if not (w.npc_minds[pid].agendas or [])]
    if todo:
        from concurrent.futures import ThreadPoolExecutor

        from aidnd import config

        def _plan_one(pid):
            st = w.npc_minds[pid]
            ag = plan_agenda(st, w, {"roles": lv["roles"]}, mgr)
            if ag:
                st.agendas.append(ag)

        with ThreadPoolExecutor(max_workers=config.LIVE_CONCURRENCY) as ex:
            list(ex.map(_plan_one, todo))
    # SILENCE — also signal: hailed stranger, they didn't respond → this is world fact, NPC remembers
    awaiting = lv.get("awaiting") or []
    spoke = lv.pop("pc_spoke", False)  # consume every tick — short-circuit `and` used to leave it stale
    if awaiting and not spoke:
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
    heat = lv.setdefault("rumor_heat", {})
    for _k in list(heat):                                  # cool every subject each tick
        heat[_k] = max(0.0, heat[_k] - PB["rumor_cool"])
        if heat[_k] <= 0.0:
            del heat[_k]
    _rot = _gt() // PB["rumor_rot_min"]
    rumor_of = {}
    for _pid in order:
        _r = _pick_rumor(rums, (_pid, _rot), heat, PB["rumor_hot"])
        if _r:
            rumor_of[_pid] = _r
    news = [n for n in news if heat.get(n, 0.0) < PB["rumor_hot"]]   # hot town-talk drops out too
    for _s in set(rumor_of.values()) | set(news):          # warm every subject offered this tick
        heat[_s] = heat.get(_s, 0.0) + PB["rumor_warm"]
    ctx = {
        "player_id": PLAYER,  # mind layer is player-agnostic; thread the reserved id through so
                              # appraise_present can skip auto-seeding a relationship from mere sight
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
        "topics_of": {pid: [t for t in _topics_for(people[pid])
                            if heat.get(t, 0.0) < PB["rumor_hot"]]
                      for pid in order},
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
    if salient and "чужак" not in str(salient):  # witnessing an unusual event (not your own act/its fallout)
        from .pc.luck import _pc_inspire
        _pc_inspire()  # → a fleeting inspiration spark
    pc_said = lv.pop("pc_said", None)
    pc_heard: dict = {}
    if pc_said and PLAYER in w.bodies:
        zn_by_place = {z["name"]: z for z in zones_l} if zones_l else {}
        pz = (zn_by_place.get(w.bodies[PLAYER].place)
              or (room_center(zones_l) if zones_l else None))
        pc_heard = _pc_heard(pz, order, lambda p: w.bodies[p].place, zn_by_place, zones_l)
    oaths, oaths_due = {}, set()
    for d_ in _deeds.promises_active():
        if d_["actor"] in w.npc_minds:
            oaths[d_["actor"]] = _deeds.promise_line(d_, lv["names"])
            if d_["data"].get("due") == _phase():
                oaths_due.add(d_["actor"])
    from aidnd.server.play.engine.quests import foreshadow as _fore
    fore = _fore.lines(order)                          # {pid: line} for cast present this tick
    fore_impulse = set(fore)                            # ONLY the foreshadow beat spikes the impulse
    for _gpid, _gln in _fore.open_lines(order).items():  # offered/active givers: LINE for the whole
        fore.setdefault(_gpid, _gln)                     # open arc (no impulse spike — like oaths)
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
        elif pid in fore_impulse:
            imp, why = 2.4, "тень дела"                 # foreshadow pulls, below a live event/debt
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
        ph = _pc_said_impulse(pc_heard.get(pid, ""))
        if ph > imp:
            imp, why = ph, "услышал чужака"
        imp += (st.config.traits.get("sociability", 0.5) - 0.5) * 0.5
        impulses[pid] = (round(imp, 2), why)
    ranked_imp = sorted(order, key=lambda p: -impulses[p][0])
    # LOD LAYERS: not everyone thinks each tick. Small scenes — all; crowds — a rotating subset,
    # salient actors always (see _select_actors). Cost stays bounded; nobody starves.
    actors = _select_actors(ranked_imp, impulses, lv)
    actor_set = set(actors)
    for pid in order:  # background crowd: keep inner clock alive cheaply (NO LLM) so a
        if pid not in actor_set:  # rotated-in NPC resumes coherently next tick
            st_bg = w.npc_minds[pid]
            _decay_needs(st_bg)
            _decay_emotion(st_bg)
            advance_agendas(st_bg, w)
    ctx["convs"] = {pid: b for pid in actors
                    if (b := conv_block(lv, pid, lv["names"]))}
    if salient:
        ctx["event"] = salient
    ctx["oaths"] = oaths
    ctx["foreshadow"] = fore
    ctx["market"] = _market_view(order, people, lv)  # co-present goods for sale → buyers can choose to buy
    ctx["pc_said"] = {pid: pc_said for pid in pc_heard} if pc_said else {}

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
                tgt = str(a.get("to") or "").strip()
                tid = (w.aliases or {}).get(tgt.lower(), tgt)
                tname = "гостю" if tid == PLAYER else lv["names"].get(tid, tgt)
                bits.append(f"говорит{(' — ' + tname) if tname else ''}: «{str(a['text'])[:48]}…»")
            elif a.get("tool") == "use" and a.get("item"):
                bits.append(f"занят: {a['item']}")
            elif a.get("tool") == "move" and a.get("to"):
                bits.append(f"идёт: {a['to']}")
        what = "; ".join(bits) or str(d.get("does") or "")[:60]
        return f"{lv['names'].get(pid, pid)} — {what}" if what else ""

    from concurrent.futures import ThreadPoolExecutor

    from aidnd import config

    # ANTI-CHORUS: decision waves — leader (highest impulse) first, retinue sees their claim.
    # Three waves so the bulk of the hall sees whether someone ALREADY engaged the newcomer
    # (attention is a scene fact fed into the prompt — never a cap on who may speak).
    decisions: dict = {}
    waves = [actors[:1], actors[1:3], actors[3:]]
    with ThreadPoolExecutor(max_workers=config.LIVE_CONCURRENCY) as ex:
        for wave in waves:
            if not wave:
                continue
            ctx["now"] = [c for pid_ in decisions
                          if (c := _claim(pid_, decisions[pid_]))]
            decisions.update(ex.map(think_one, wave))
    ctx.pop("now", None)

    # ── detailed scene log (data/debug/play.log): 'why' of each NPC per tick ──
    import logging as _logging

    _slog = _logging.getLogger("aidnd.scene")
    if _slog.isEnabledFor(_logging.DEBUG):
        _slog.debug("─── ТИК %s · %s · «%s» · душ=%d · LLM-актёров=%d · разговоров=%d · "
                    "в пути=%d · игрок@%s (zone=%s) ───",
                    lv["clock"], ctx["time"], lv["place"], len(order), len(actors),
                    len(lv.get("convs") or []),
                    len(_S.get("transit") or {}),  # наблюдаемость Inc3: пешеходы в городе сейчас
                    w.bodies[PLAYER].place if PLAYER in w.bodies else "?", _S.get("zone"))
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

    feed, address = _S["live"].pop("churn", []) + list(zone_feed), []   # Inc1: door events lead the feed
    if not _S.get("inside"):    # снаружи — и улица, и площадь, и двор заведения; внутри здания
        # прохожих не видно (Inc3). NB: lv["bid"] is truthy for ANY node mapped to a building —
        # including its street-front door node — so it must NOT gate this; only _S["inside"] does.
        from .worldsim import _transit_node
        _gt_now = _gt()
        for pid, row in (_S.get("transit") or {}).items():
            if pid in people and _transit_node(row, _gt_now) == lv["loc"]:
                feed.append({"k": "deed", "who": _display(pid, people), "pid": pid,
                             "text": "проходит мимо, не задерживаясь"})
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
                                "pid": pid,
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
                                "pid": pid,
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
                            "pid": pid,
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
                if tid == PLAYER and _player_in_scene(zones_l, pid, w, lv):
                    # decision 'talk to stranger' — NPC's own, player actually in earshot
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
                    plz = zn_by_place.get(pl_place)
                    if plz is None and _S.get("inside"):
                        plz = room_center(zones_l)  # just inside the door — hall audible from its edge
                    ev = _S.get("eaves") or {}
                    boost = 1 if (ev.get("place") == sp_place
                                  and lv["clock"] <= ev.get("until", -1)) else 0
                    tier, disp, mw = _overheard(
                        txt, plz or {"id": pl_place},
                        zn_by_place.get(sp_place, {"id": sp_place}),
                        sp_place, f"hear|{lv['clock']}|{pid}", boost=boost)
                    if tier is None:
                        lv["murmur"] = lv.get("murmur", 0) + 1
                    else:
                        feed.append({"k": "speech", "who": who, "tier": tier,
                                     "to": (_display(tid, people) if tid in people
                                            else lv["names"].get(tid, tgt)),
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
                feed.append({"k": "deed", "who": who, "pid": pid,
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
                            feed.append({"k": "deed", "who": _display(pid, people), "pid": pid,
                                         "text": f"кидает пару монет за {a['item']}"})
        acted = "; ".join(evs + spoke)  # NPC REMEMBERS both acts and words — no repeat
        lv["last"][pid] = acted[:110] or "—"
        lv["hist"].setdefault(pid, []).append(acted[:80])
        does = (d.get("does") or "").strip()
        if does and not said:  # line itself carries moment — don't duplicate
            feed.append({"k": "deed", "who": who, "pid": pid, "text": does[:150]})
    _npc_trade_step(people, order, decisions, lv, feed)  # NPC↔NPC trade + haggle from `buy` intents, settled in-store
    if lv.pop("murmur", 0):  # someone spoke too far off to make out — no longer gated to every 3rd tick
        feed.append({"k": "deed", "who": "зал", "text": "за столами гудит негромкий говор"})
    if not feed:  # idle backstop: nothing surfaced this tick — soundscape fills the silence
        amb = _idle_ambient(w, zones_l, order, lv["zone_ids"])
        if amb:
            feed.append({"k": "deed", "who": "зал", "text": amb})
    if zones_l:
        for pid in order:
            zmap[pid] = lv["zone_ids"].get(w.bodies[pid].place)
    lv["clock"] += 1
    _gt_add(PB["live_tick_min"])  # world tick (game minutes)
    _pc_save()
    for pid in order:  # lived experience survives restart
        _npc_save(pid)
    return feed, address
