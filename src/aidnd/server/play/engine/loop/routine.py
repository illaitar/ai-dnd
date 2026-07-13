"""Passive world routine: daily events and the residents' schedule sync.

Key functions
-------------
_world_events() -> None : Daily passive world events (wanted decay, guild/board/caravan news).
_apply_routine() -> None : Sync passive world with current game time — routine of ALL residents.
"""

from __future__ import annotations

import random

from aidnd.server.play.engine.core import _S, PB, _gt, _phase, _store, _wanted, _wanted_add, _wid
from aidnd.server.play.engine.worldsim import routine_step
from aidnd.server.play.mechanics.combat import _npc_delves
from aidnd.server.play.mechanics.contracts import _board_npc_fulfill, _board_publish
from aidnd.server.play.mechanics.items import _merchant_restock


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
        from aidnd.server.play.engine.quests.pipeline import quest_morning
        qn = quest_morning()
        if qn:
            _S["quest_news"] = (_S.get("quest_news") or [])[-3:] + qn
    except Exception:  # noqa: BLE001 — no LLM / bad output → honest absence, morning continues
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
    from ..world import _here

    key = (_gt() // 30, _gt() // 1440)               # routine step: every 30 game minutes
    if _S.get("routine_key") == key or not _S.get("people"):
        return
    _S["routine_key"] = key
    mkey = (_phase(), _gt() // 1440)                 # daily events — once at morning
    ekey = f"{mkey[0]}|{mkey[1]}"
    if (
        mkey[0] == "morning"
        and _S.get("events_key") != mkey
        and _store().flag_get(_wid(), "events_key") != ekey
    ):
        _S["events_key"] = mkey
        _store().flag_set(_wid(), "events_key", ekey)  # persist: a restart must not replay the
        _world_events()                                # day's ~8s LLM board-publish ("slow refresh")
    try:  # E1: economy — lazy catch-up for EVERY skipped day (not just 'morning')
        from aidnd.server.play.engine.economy import economy_catchup
        en = economy_catchup()
        if en:
            _S["econ_news"] = (_S.get("econ_news") or [])[-2:] + en
    except Exception:  # noqa: BLE001 — economy doesn't crash the world
        pass
    routine_step(_S["people"], _S["crof"], pin=set(_here(_S["loc"], _S["crof"])))
