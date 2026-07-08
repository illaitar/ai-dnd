"""Player entity — hero state (name, HP, capabilities), fog-of-war, and persistence.

Key functions
-------------
_pc() -> NpcState : Get or load player state, with memory and relationships.
_pc_hp(delta, set_to) -> int : Read/adjust player HP (clamped to max).
_pc_name() -> str : Player's chosen name (cached in session, loaded from save).
_pc_set_name(name) -> None : Set player's chosen name (session only — save via _pc_save).
_pc_cap_eff() : Player abilities WITH FATIGUE applied (for rolls/casts).
_pc_save() -> None : Persist player state (hp, mana, memory, relationships) to DB.
_npc_save(pid) -> None : Persist one NPC's lived experience (memory/relationships/needs) to DB.
_mark_seen(bid) -> None : Fog of war — location becomes known once learned.
"""

from __future__ import annotations

from aidnd.items import Capability
from aidnd.mind import NpcConfig, NpcState

from ..session.config import PB, PLAYER
from ..session.persist import _store
from ..session.state import _S, _wid
from ..session.time import _gt, _mt


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


def _pc_cap_eff():
    """Player abilities WITH FATIGUE applied (for new rolls/casts) — all stats penalized."""
    from .fatigue import _fatigue  # lazy: fatigue -> mana -> hero would cycle at import time

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
    from .glyphs import _glyphs_known  # lazy: keeps hero import-time free of sibling deps
    from .mana import _mana_load  # lazy: mana imports _PC_CAP from hero — avoid an import cycle

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
