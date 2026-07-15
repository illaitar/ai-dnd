"""Game loop — CORE: per-user worlds, state, DB, time, player-agent, utility helpers.

Layer mechanics/ (see docs/loop.md).

Key functions
-------------
_play_session(request: Request) : FastAPI dependency for all /api/play/* endpoints.
_gt() -> int : Get current game time in minutes from world session.
_pc() -> NpcState : Get or load player state, with memory and relationships.
_store() -> WorldStore : Access runtime world database (data/live.db).
_pool() -> WorldStore : Access content pool database (data/worlds.db).
_mana() -> float : Get player's current mana with lazy Int/Wis-based regeneration.
_pc_save() -> None : Persist player state (hp, mana, memory, relationships) to DB.
_model() : Get LLM model manager instance with usage tracking.
"""

from __future__ import annotations

import os
import random

from fastapi import APIRouter, Depends, HTTPException, Request

from aidnd import config

from .narrator.voice import _DM_SYS as _DM_SYS
from .narrator.voice import _spurns as _spurns
from .narrator.voice import _topics_for as _topics_for
from .pc.fatigue import _fat_add as _fat_add
from .pc.fatigue import _fatigue as _fatigue
from .pc.glyphs import _STARTER_GLYPHS as _STARTER_GLYPHS
from .pc.glyphs import _glyph_learn as _glyph_learn
from .pc.glyphs import _glyphs_known as _glyphs_known
from .pc.glyphs import _grimoire_get as _grimoire_get
from .pc.glyphs import _grimoire_list as _grimoire_list
from .pc.glyphs import _grimoire_put as _grimoire_put
from .pc.hero import _PC_CAP as _PC_CAP
from .pc.hero import _mark_seen as _mark_seen
from .pc.hero import _met, _npc_save
from .pc.hero import _pc as _pc
from .pc.hero import _pc_cap_eff as _pc_cap_eff
from .pc.hero import _pc_hp as _pc_hp
from .pc.hero import _pc_name as _pc_name
from .pc.hero import _pc_remember as _pc_remember
from .pc.hero import _pc_save as _pc_save
from .pc.hero import _pc_set_name as _pc_set_name
from .pc.hero import _seen as _seen
from .pc.mana import _mana as _mana
from .pc.mana import _mana_cap as _mana_cap
from .pc.mana import _mana_grow as _mana_grow
from .pc.mana import _mana_hardcap as _mana_hardcap
from .pc.mana import _mana_load as _mana_load
from .pc.mana import _mana_rate as _mana_rate
from .pc.mana import _mana_restore as _mana_restore
from .pc.mana import _mana_sleep as _mana_sleep
from .pc.mana import _mana_spend as _mana_spend
from .session.config import _GT0 as _GT0
from .session.config import PB as PB
from .session.config import PLAYER
from .session.persist import _pool, _store
from .session.state import (
    _CUR,
    _S,
    _SESS,
    _UID,
    _fresh_sess,
    _wid,
)
from .session.state import _SessProxy as _SessProxy
from .session.state import current_world_id as current_world_id
from .session.time import _PHASE_RU as _PHASE_RU
from .session.time import _gt as _gt
from .session.time import _gt_add as _gt_add
from .session.time import _mt
from .session.time import _phase as _phase


async def _play_session(request: Request):
    """FastAPI dependency for all /api/play/*: user by cookie → their world → world session in contextvar.
    Dev/tests: AIDND_OPEN_PLAY=1 (or service DB is down) → shared world 1 without login."""
    uid, db_ok = None, True
    token = request.cookies.get("aidnd_session", "")
    # Prime the request body cache here (dependency shares the Request with the endpoint) so the
    # replay recorder can read the player's input from request.state without re-reading the ASGI
    # body stream in middleware (which would starve the endpoint).
    if request.method == "POST":
        try:
            request.state.replay_req = await request.json()
        except Exception:  # noqa: BLE001 — non-JSON / empty body
            request.state.replay_req = {}
    try:
        from aidnd.server.auth import user_for_token
        from aidnd.server.db import SessionLocal

        async with SessionLocal() as db:
            if token:
                u = await user_for_token(db, token)
                uid = u.id if u else None
                request.state.user = u
    except Exception:  # noqa: BLE001 — service DB is down
        db_ok = False
    if uid is None:
        if os.environ.get("AIDND_OPEN_PLAY") or not db_ok:
            if 1 not in _SESS:
                dev_seed = int(_store().flag_get(0, "dev_seed") or 1)
                _SESS[1] = _fresh_sess(1, dev_seed)  # dev/demo: shared world; seed grows after death
            _CUR.set(_SESS[1])
            request.state.wid = 1  # replay recorder: which world file to append to
            return
        raise HTTPException(401, "требуется вход")
    _UID.set(uid)
    u = getattr(request.state, "user", None)
    if u is not None and not u.unlimited and _llm_used(uid) >= config.DAILY_LLM:
        raise HTTPException(
            402, "дневной лимит рассказчика исчерпан — введи код на главной или возвращайся завтра"
        )
    row = _store().user_world(str(uid)) or _store().user_world_create(str(uid))
    wid, seed = row
    _CUR.set(_SESS.setdefault(wid, _fresh_sess(wid, seed)))
    request.state.wid = wid  # replay recorder: which world file to append to


router = APIRouter(tags=["play"], dependencies=[Depends(_play_session)])


def _llm_day_key(uid) -> str:
    import time as _t

    return f"llm|{uid}|{_t.strftime('%Y%m%d')}"


def _llm_used(uid) -> int:
    return int(_store().flag_get(0, _llm_day_key(uid)) or 0)


def _llm_hook(role, model) -> None:
    """Each LLM call in game loop — tick of user counter (limit without code)."""
    uid = _UID.get()
    if uid is not None:
        _store().flag_set(0, _llm_day_key(uid), str(_llm_used(uid) + 1))


_COLORS = ["#c98a52", "#6f8f6a", "#8a6fae", "#a86a6a", "#5f8296", "#b0894a"]


def _binfo(bid: str | None) -> dict:
    """Name/kind/label of place — from building FACTSHEET (enrichment generates name/atmosphere/type),
    not from code. Fallback — sign from DB."""
    bd = _store().get_building(_wid(), bid) if bid else None
    data = (bd or {}).get("data") or {}
    name = data.get("name") or (bd or {}).get("sign") or "Здание"
    kind = data.get("atmosphere") or data.get("type") or "постройка"
    label = (data.get("type") or "дом").split(",")[0].split()[0][:12]
    return {"name": name, "kind": kind, "label": label}


# building type (from factsheet) → worker role; data table, order = match priority
_TYPE_ROLE = (
    ("таверн", "трактирщик"),
    ("трактир", "трактирщик"),
    ("постоял", "трактирщик"),
    ("оружейн", "оружейник"),
    ("лавк", "лавочник"),
    ("склад", "лавочник"),
    ("кузн", "кузнец"),
    ("храм", "жрец"),
    ("свят", "жрец"),
    ("часовн", "жрец"),
    ("башн", "маг"),
    ("магич", "маг"),
    ("колдун", "маг"),
    ("чароде", "маг"),
    ("аркан", "маг"),
    ("обсерватор", "маг"),
    ("писц", "писец"),
    ("писар", "писец"),
    ("фолиант", "писец"),
    ("свиток", "писец"),
    ("целебн", "знахарка"),
    ("знахар", "знахарка"),
    ("травн", "знахарка"),
    ("мельниц", "мельник"),
    ("пекарн", "трактирщик"),
    ("мастерск", "сапожник"),
    ("кожевн", "дубильщик"),
    ("дубильн", "дубильщик"),
    ("конюшн", "горожанин"),
    ("усадьб", "горожанин"),
    ("гильди", "стражник"),
)

# roles that teach magic (§M-4): mage in tower — elements and glyphs; scribe — "words" of writing
TEACHER_ROLES = ("маг", "писец", "писарь")


def _role_for_building(bid: str) -> str:
    """Worker role — FROM BUILDING DATA (type/name from factsheet), not from ordinal circle."""
    info = _binfo(bid)
    t = (info["kind"] + " " + info["name"]).lower()
    return next((r for w, r in _TYPE_ROLE if w in t), "горожанин")


def _city_name() -> str:
    v = _S.get("city_name")
    if v is None:
        v = _store().flag_get(_wid(), "city_name")
        if not v:  # new world: name — from NAME POOL (no LLM)
            names = _pool().pool_buildings("city_name")
            if names:
                v = random.Random(f"cname|{_wid()}").choice(names)["data"]["name"]
                _store().flag_set(_wid(), "city_name", v)
        v = _S["city_name"] = v or "городок"
    return v


def _model():
    if _S["model"] is None:
        from aidnd.inference import ModelManager

        mgr = ModelManager()
        mgr.on_call = _llm_hook  # each call — tick of user limit
        _S["model"] = mgr
    return _S["model"]


def _inscriber():
    """Magic inscriber (role A — circle law, role B — wild chaos). LLM only — no fallbacks."""
    if _S.get("inscriber") is None:
        from aidnd.magic import LLMInscriber

        _S["inscriber"] = LLMInscriber(_model())
    return _S["inscriber"]


def _in_room(where: str, room: str | None, rooms: list) -> bool:
    """Container belongs to room: by matching room words in where (cases don't matter);
    else — common hall."""
    wt = _tokens_ru(where)
    if room:
        return bool(_tokens_ru(room) & wt)
    return not any(_tokens_ru(r["name"]) & wt for r in rooms)  # in hall — not tied to rooms


def _role_at(node, people, spot, n2b):
    bid = n2b.get(node)
    if not bid:
        return None
    return next(
        (people[pid].role for pid, s in spot.items() if s == node and people[pid].work == bid), None
    )


def _flip_arrived(spot: dict) -> None:
    """Lazy, query-shaped: any transit row past its arrive_gt flips into crof and is deleted.
    Nothing ticks — this runs only when a here-query is made."""
    tr = _S.get("transit")
    if not tr:
        return
    gt = _gt()
    for pid, row in list(tr.items()):
        if pid not in spot:      # orphan row (world rebuilt, resident gone) — compost, never a phantom
            del tr[pid]
        elif gt >= row["arrive_gt"]:
            spot[pid] = row["to"]
            del tr[pid]


def _here_settled(node, spot):
    """Occupants SETTLED at node: crof members at node MINUS anyone en route (a transit walker is
    not settled anywhere). Flips arrived walkers first. Used by the rebuild trigger / scene build so
    brief walkers never thrash a rebuild (§3.3)."""
    _flip_arrived(spot)
    tr = _S.get("transit") or {}
    return [pid for pid, s in spot.items() if s == node and pid not in tr]


def _here(node, spot):
    """Everyone AT node right now: settled occupants + walkers whose derived transit position == node."""
    out = _here_settled(node, spot)
    tr = _S.get("transit")
    if tr:
        from .worldsim import _transit_node
        gt = _gt()
        for pid, row in tr.items():
            if _transit_node(row, gt) == node and pid not in out:
                out.append(pid)
    return out


def _emo(st) -> str:
    e = st.emotion
    dom = max(e, key=e.get)
    if e[dom] < 0.15:
        return "спокойное"
    return {
        "joy": "тёплое",
        "anger": "раздражённое",
        "fear": "настороженное",
        "distress": "подавленное",
    }.get(dom, "ровное")


_PORT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "..", "data", "portraits"
)  # repo-root data/portraits — the same dir app.py mounts at /portraits


def _portrait_url(p, emo: str | None = None) -> str | None:
    """Portrait URL for NPC by emotion (static /portraits). None if file not on disk —
    so prod without uploaded images returns initials, not broken links (persona lives in DB)."""
    ports = getattr(p, "portraits", None) or {}
    if not ports:
        return None
    key = emo if emo in ports else "спокойное" if "спокойное" in ports else next(iter(ports))
    rel = ports[key]
    return "/portraits/" + rel if os.path.exists(os.path.join(_PORT_DIR, rel)) else None


def _tokens_ru(s: str) -> set:
    """Crude stem: prefix-5 (cases don't matter "медяки"↔"медяков")."""
    return {
        w[:5] for w in str(s).lower().replace("«", " ").replace("»", " ").split() if len(w) >= 4
    }


def _wanted() -> int:
    return int(_store().flag_get(_wid(), "wanted|pc") or 0)


def _wanted_add(pts: int, reason: str = "") -> None:
    """Wanted points: accumulate from witnessed crimes, decay over time."""
    _store().flag_set(_wid(), "wanted|pc", str(max(0, _wanted() + int(pts))))
    if reason and pts > 0:  # chronicle — for guard dialogue
        prior = _store().flag_get(_wid(), "crimes|pc") or ""
        _store().flag_set(
            _wid(), "crimes|pc", ((prior + "; " + reason) if prior else reason)[-240:]
        )


def _wanted_clear() -> None:
    _store().flag_set(_wid(), "wanted|pc", "0")
    _store().flag_set(_wid(), "crimes|pc", "")


def _witness_crime(people, crof, loc, npc, what: str, weight: int = 2) -> int:
    """Crime in plain sight: victim enraged, witnesses record memory (gossip spreads),
    wanted points grow (victim reports + more eyes = hotter)."""
    p = people[npc]
    rel = p.state.rel(PLAYER)
    rel["affinity"] = min(rel["affinity"], -0.5)
    p.state.emotion["anger"] = min(1.0, p.state.emotion.get("anger", 0) + 0.7)
    p.state.emotion_target["anger"] = PLAYER
    p.state.memory.add(f"чужак {what} — я этого не забуду!", _mt(), 0.9, about=[PLAYER])
    wit = [w for w in _here(loc, crof) if w != npc]
    for w in wit:
        people[w].state.memory.add(
            f"видел(а): чужак {what} ({p.name})", _mt(), 0.6, about=[PLAYER, npc]
        )
        _npc_save(w)
    _npc_save(npc)
    _wanted_add(weight + min(3, len(wit)), what)  # victim + witnesses → wanted
    from .pc.luck import _pc_karma_add  # lazy: luck→session only, avoid an import cycle
    _pc_karma_add(-PB["karma_crime"])  # a crime stains your luck
    return len(wit)


def _descriptor(p) -> str:
    """Stranger distinguished BY EYES: sex + UNIQUE mark (look.marks/hair/face from persona),
    clothing — secondary. Three "guys in cloaks" must be three different people."""
    per = p.persona or {}
    look = per.get("look") or {}
    sex = "женщина" if per.get("sex") == "f" else "мужчина"
    mark = ""
    for src in ((look.get("marks") or [None])[0], look.get("hair"), look.get("face")):
        if src and str(src).strip():
            mark = str(src).split(",")[0].strip().lower()
            break
    cloth = (look.get("clothing") or "").split(",")[0].strip()
    if mark:
        return f"{sex} — {mark}"
    return f"{sex} ({cloth})" if cloth else sex


def _scene_descriptors(people, pids) -> dict:
    """Descriptors DISTINGUISHING strangers in THIS scene: pool stamps "scar on cheek" on half
    the city — greedily pick for each a CATEGORY mark not yet taken by scene neighbors
    (mark → hair → face → clothing → build); all taken — combine two marks."""
    used: set = set()
    out: dict = {}
    for pid in sorted(pids):
        p = people.get(pid)
        per = (p.persona or {}) if p else {}
        look = per.get("look") or {}
        sex = "женщина" if per.get("sex") == "f" else "мужчина"
        cands = []
        for c in ((look.get("marks") or [None])[0], look.get("hair"), look.get("face"),
                  look.get("clothing"), per.get("build")):
            c = str(c).split(",")[0].strip().lower() if c and str(c).strip() else ""
            if c:
                cands.append(c)
        pick = None
        for c in cands:
            cat = c.split()[0][:5]                     # category = stem of first word ("scar…")
            if cat not in used:
                used.add(cat)
                pick = c
                break
        if pick is None and cands:                     # all categories taken — combine two marks
            pick = cands[0] + (", " + cands[1] if len(cands) > 1 else "")
        out[pid] = f"{sex} — {pick}" if pick else sex
    return out


def _display(pid: str, people) -> str:
    """Display name for character in narrative."""
    if pid == PLAYER:
        return "ты"
    p = people.get(pid)
    if not p:
        return "прохожий"  # unknown in this scene — but NEVER raw id
    if pid in _met():
        return p.name
    d = ((_S.get("live") or {}).get("descr") or {}).get(pid)  # scene descriptor distinguishes neighbors
    return d or _descriptor(p)
