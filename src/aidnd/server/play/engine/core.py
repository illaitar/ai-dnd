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

import json
import os
import random

from fastapi import APIRouter, Depends, HTTPException, Request

from aidnd import config
from aidnd.items import Capability
from aidnd.mind import NpcConfig, NpcState

from .session.config import _GT0 as _GT0
from .session.config import PB, PLAYER
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
from .session.time import _gt, _mt
from .session.time import _gt_add as _gt_add
from .session.time import _phase as _phase


async def _play_session(request: Request):
    """FastAPI dependency for all /api/play/*: user by cookie → their world → world session in contextvar.
    Dev/tests: AIDND_OPEN_PLAY=1 (or service DB is down) → shared world 1 without login."""
    uid, db_ok = None, True
    token = request.cookies.get("aidnd_session", "")
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


router = APIRouter(tags=["play"], dependencies=[Depends(_play_session)])


# ------------------------------------------------ PLAYER-AGENT (pc_state) -- #
def _pc() -> NpcState:
    """Player — same agent: NpcState with memory and relationships. Persists in store."""
    if _S.get("pc") is None:
        st = NpcState.from_config(NpcConfig(id=PLAYER, name="ты", role="странник"))
        row = _store().get_pc(_wid())
        if row:
            st.relationships = row.get("relationships") or {}
            for m in row.get("memory") or []:
                mm = st.memory.add(
                    m["text"],
                    m["t"],
                    m.get("importance", 0.3),
                    kind=m.get("kind", "observation"),
                    about=m.get("about") or [],
                )
                mm.last_access = m.get("last_access", m["t"])
        _S["pc"] = st  # don't touch time: _gt() loads from save itself
    return _S["pc"]


def _pc_hp(delta: int = 0, set_to: int | None = None) -> int:
    v = _S.get("pc_hp")
    if v is None:
        row = _store().get_pc(_wid()) or {}
        v = _S["pc_hp"] = row.get("hp", PB["pc_max_hp"])
    if set_to is not None:
        v = set_to
    v = max(0, min(PB["pc_max_hp"], v + delta))
    _S["pc_hp"] = v
    return v


def _pc_name() -> str:
    v = _S.get("pc_name")
    if v is None:
        v = _S["pc_name"] = (
            (_store().get_pc(_wid()) or {}).get("name") or "Странник"
        ).strip() or "Странник"
    return v


def _pc_set_name(name: str) -> None:
    _S["pc_name"] = str(name or "").strip()[:24] or "Странник"


_PC_CAP = Capability(abilities={"str": 10, "dex": 11, "con": 10, "int": 11, "wis": 11, "cha": 12})


# ------------------------------------------------------------ MANA (magic) --- #
def _mana_hardcap() -> float:
    return _PC_CAP.abilities.get("int", 10) * PB["mana_hardcap_per_int"]  # growth ceiling from Int


def _mana_load() -> None:
    if _S.get("mana") is None:
        row = _store().get_pc(_wid()) or {}
        _S["mana"] = float(row.get("mana", PB["mana_start"]))
        _S["mana_cap"] = float(row.get("mana_cap", PB["mana_cap_start"]))
        _S["mana_gt"] = int(row.get("mana_gt", _gt()))
        _S["fat"] = int(row.get("fat", 0))
        _S["fat_until"] = int(row.get("fat_until", 0))


def _mana_rate() -> float:
    """Mana regen per waking hour — from Int/Wis."""
    return max(0.2, PB["mana_regen_base"] + _PC_CAP.mod("int") + _PC_CAP.mod("wis"))


def _mana() -> float:
    """Current mana with LAZY regen from Int/Wis (no per-tick frame)."""
    _mana_load()
    dt_h = max(0, _gt() - _S["mana_gt"]) / 60.0
    if dt_h > 0:
        _S["mana"] = min(_S["mana_cap"], _S["mana"] + _mana_rate() * dt_h)
        _S["mana_gt"] = _gt()
    return round(_S["mana"], 2)


def _mana_sleep(hours: float) -> None:
    """Sleep fills candle faster than waking (×mana_sleep_mult): bonus on top of lazy regen."""
    _mana()  # lazy regen for time asleep — at rate ×1
    bonus = _mana_rate() * max(0.0, hours) * (PB["mana_sleep_mult"] - 1)
    _S["mana"] = min(_S["mana_cap"], _S["mana"] + bonus)


def _mana_cap() -> float:
    _mana_load()
    return round(_S["mana_cap"], 2)


def _mana_spend(amount: float) -> float:
    _S["mana"] = max(0.0, _mana() - float(amount))
    return round(_S["mana"], 2)


def _mana_grow(spent: float) -> None:
    """Cap growth from burning (magic as muscle), up to hard limit Int×N."""
    if spent <= 0:
        return
    _S["mana_cap"] = min(
        _mana_hardcap(),
        _S["mana_cap"] + round(PB["mana_grow_frac"] * spent / max(1.0, _S["mana_cap"]), 3),
    )


def _fatigue() -> int:
    """Current fatigue penalty to ALL stats (fades over time)."""
    _mana_load()
    if _gt() >= _S.get("fat_until", 0):
        _S["fat"], _S["fat_until"] = 0, 0
    return int(_S.get("fat", 0))


def _fat_add(spent: float) -> None:
    """Burnout after cast: fatigue from burned mana, lasts longer with bigger burnout."""
    pts = 1 + int(spent) // PB["fatigue_div"]
    _S["fat"] = _fatigue() + pts
    _S["fat_until"] = _gt() + pts * PB["fatigue_min_per_pt"]


# player starter glyph set (§M1e): enough for fire arrow and healing; rest must be learned
_STARTER_GLYPHS = ("огонь", "свет", "стрела", "исцелить", "больше")


def _glyphs_known() -> list:
    """Glyphs OWNED by player (persists in pc_state); others must be learned from mage."""
    if _S.get("glyphs") is None:
        row = _store().get_pc(_wid()) or {}
        g = row.get("glyphs")
        _S["glyphs"] = list(dict.fromkeys(g if g is not None else _STARTER_GLYPHS))
    return list(_S["glyphs"])


def _glyph_learn(gid: str) -> bool:
    """Add glyph to player arsenal. True — learned for first time, False — already knew."""
    known = _glyphs_known()
    if gid in known:
        return False
    _S["glyphs"] = known + [gid]
    return True


def _pc_cap_eff():
    """Player abilities WITH FATIGUE applied (for new rolls/casts) — all stats penalized."""
    fat = _fatigue()
    if not fat:
        return _PC_CAP
    from aidnd.items import Capability

    return Capability(
        abilities={k: max(1, v - fat) for k, v in _PC_CAP.abilities.items()},
        competencies=_PC_CAP.competencies,
        tools=_PC_CAP.tools,
    )


def _pc_save() -> None:
    st = _pc()
    _mana_load()
    _store().save_pc(
        _wid(),
        {
            "gt": _gt(),
            "hp": _pc_hp(),
            "name": _pc_name(),
            "relationships": st.relationships,
            "mana": round(_S["mana"], 2),
            "mana_cap": round(_S["mana_cap"], 2),
            "mana_gt": _S["mana_gt"],
            "fat": _S.get("fat", 0),
            "fat_until": _S.get("fat_until", 0),
            "glyphs": _glyphs_known(),
            "loc": _S.get("loc"),
            "inside": _S.get("inside"),
            "room": _S.get("room"),  # position survives restart
            "zone": _S.get("zone"),
            "memory": [
                {
                    "text": m.text,
                    "t": m.t,
                    "importance": m.importance,
                    "last_access": m.last_access,
                    "kind": m.kind,
                    "about": m.about,
                }
                for m in st.memory.items[-400:]
            ],
        },
    )  # tail — log doesn't grow infinitely


def _met() -> set:
    return set(_pc().relationships)


def _pc_remember(text: str, importance: float = 0.3, about=None, kind: str = "observation") -> None:
    _pc().memory.add(text, _mt(), importance, kind=kind, about=list(about or []))
    _pc_save()


def _npc_save(pid: str) -> None:
    """NPC lived experience (memory/relationships/needs) → DB: survives server restart."""
    p = (_S.get("people") or {}).get(pid)
    if not p:
        return
    st = p.state
    _store().save_npc_state(
        _wid(),
        pid,
        {
            "relationships": st.relationships,
            "needs": st.needs,
            "memory": [
                {
                    "text": m.text,
                    "t": m.t,
                    "importance": m.importance,
                    "last_access": m.last_access,
                    "kind": m.kind,
                    "about": m.about,
                }
                for m in st.memory.items[-200:]
            ],
        },
    )


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


def _seen() -> set:
    if _S.get("seen") is None:
        _S["seen"] = {k.split("|", 1)[1] for k in _store().flags_prefix(_wid(), "seen|")}
    return _S["seen"]


def _mark_seen(bid: str | None) -> None:
    """Fog of war: location becomes known (map marker) when player LEARNS it —
    came themselves or heard from people/info."""
    if bid and bid not in _seen():
        _S["seen"].add(bid)
        _store().flag_set(_wid(), f"seen|{bid}")


def _topics_for(p) -> list:
    """Conversation topics — from PERSONA (rumors/wants), not from role table."""
    per = p.persona or {}
    out = [t[:40] for t in (per.get("rumors") or [])[:2]] + [
        t[:40] for t in (per.get("wants") or [])[:1]
    ]
    return out or ["что нового?", "о городе", "о жизни здесь"]


def _spurns(p) -> bool:
    """Doesn't want to deal with you: enmity or fresh targeted anger."""
    rel = p.state.relationships.get(PLAYER) or {}
    ang = p.state.emotion.get("anger", 0)
    return rel.get("affinity", 0) < PB["hostile_aff"] or (
        ang > 0.5 and p.state.emotion_target.get("anger") == PLAYER
    )


_DM_SYS = (
    "Ты — мастер настольной игры. Игрок заявил действие, которое НЕ ИСПОЛНЯЕТСЯ механикой — "
    "мир от него НЕ изменится. Тебе дан СНИМОК живой сцены (место, время, люди и их занятия, "
    "последние реплики, предметы рядом) — это ЕДИНСТВЕННАЯ правда: опирайся на неё и вплетай её "
    "детали (кто рядом чем занят, что слышно), НИЧЕГО не выдумывай сверх снимка и не противоречь "
    "ему (если люди греются у очага — очаг горит). Ответь 1-2 фразами: 2-е лицо, настоящее время, "
    "сухо. НИКОГДА не подтверждай свершение заявленного (особенно разрушительного): покажи, почему "
    "оно не происходит или на чём останавливается — либо, для созерцательного, что игрок видит."
)


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


def _grimoire_get(h: str) -> dict | None:
    """Inscribed circle law (by composition hash) for current world — or None."""
    raw = _store().flag_get(_wid(), f"grim|{h}")
    return json.loads(raw) if raw else None


def _grimoire_put(h: str, entry: dict) -> None:
    _store().flag_set(_wid(), f"grim|{h}", json.dumps(entry, ensure_ascii=False))


def _grimoire_list() -> list:
    """All circles inscribed in world (player grimoire), in order of first creation."""
    out = []
    for v in _store().flags_prefix(_wid(), "grim|").values():
        try:
            out.append(json.loads(v))
        except (ValueError, TypeError):
            pass
    return sorted(out, key=lambda e: e.get("first_gt", 0))


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


def _here(node, spot):
    return [pid for pid, s in spot.items() if s == node]


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


_PORT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "portraits")


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
