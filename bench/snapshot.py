"""Deep, read-only reflection over a benchmark world's backend state (bench/).

`core._S` is a contextvar-backed session that, in-process, only resolves through the FastAPI
dependency during a request — outside a request it falls back to the shared `_SESS[1]` dict
(open-play world), which starts EMPTY right after `bench.harness.bench_world()` (`city=None`).
Verified empirically: after a `Harness.act()` HTTP turn, `core._S` IS visible from the calling
thread too, because the request thread mutates that same `_SESS[1]` dict object in place rather
than replacing it — but `snapshot()` must also work with NO prior turn. So it calls `world._play()`
itself first, exactly like the `tests/play/test_economy.py` fixture does: idempotent (only
regenerates the city if `core._S["city"]` is still None), otherwise just re-syncs NPC routine
positions to the current game clock. Never touches player-facing/LLM-prompt behavior.

Key functions
-------------
snapshot() -> dict : full state dump — session/npcs/live/economy/crof — for the CURRENT world.
"""

from __future__ import annotations

from aidnd.server.play.engine import core
from aidnd.server.play.engine import economy as ec
from aidnd.server.play.engine.world import _play


def snapshot() -> dict:
    """Load/refresh the current benchmark world's session, then dump every read-only layer."""
    _play()
    ec.ensure()
    return {
        "session": _session(),
        "npcs": _npcs(),
        "live": _live(),
        "economy": _econ(),
        "crof": dict(core._S.get("crof") or {}),
    }


def _session() -> dict:
    """Player/session state: position, clock, wanted, purse, HP/mana/fatigue, world flags."""
    return {
        "loc": core._S.get("loc"),
        "inside": core._S.get("inside"),
        "room": core._S.get("room"),
        "zone": core._S.get("zone"),
        "gt": core._gt(),
        "wanted": core._wanted(),
        "coins": core._store().purse_get(core._wid(), core.PLAYER),
        "hp": core._pc_hp(),
        "max_hp": core.PB["pc_max_hp"],
        "mana": core._mana(),
        "mana_cap": core._mana_cap(),
        "fatigue": core._fatigue(),
        "glyphs": core._glyphs_known(),
        "flags": core._store().flags_prefix(core._wid(), ""),
    }


def _npcs() -> dict:
    """NPCs present at the player's location: needs/emotion/relationships/memory/agenda."""
    people = core._S.get("people") or {}
    crof = core._S.get("crof") or {}
    out = {}
    for pid in core._here(core._S.get("loc"), crof):
        p = people.get(pid)
        if p is None:
            continue
        st = p.state
        out[pid] = {
            "name": p.name,
            "role": p.role,
            "needs": dict(st.needs),
            "emotion": dict(st.emotion),
            "relationships": st.relationships,
            "memory_size": len(st.memory.items),
            "agenda": [a.view() for a in (st.agendas or [])],
            "plan": st.plan.view() if st.plan else None,
        }
    return out


def _live() -> dict:
    """live.db rows for the player: inventory, purse, deeds log, contracts."""
    store, wid = core._store(), core._wid()
    return {
        "inventory": store.inventory(wid, core.PLAYER),
        "purse": store.purse_get(wid, core.PLAYER),
        "deeds": store.deeds(wid, limit=20),
        "contracts": store.contracts(wid),
    }


def _econ() -> dict:
    """Money-supply invariant + named supply-chain diagnostics (docs/citysim.md §B)."""
    return {
        "money_supply": ec.money_supply(),
        "chains": ec.chains_view(),
    }
