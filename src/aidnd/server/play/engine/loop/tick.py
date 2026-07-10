"""World tick — the one point where "the world moved".

Key functions
-------------
_world_tick() -> dict : Sync passive world (routine + daily events) then advance the live scene
    near the player; returns the feed/address the player sees this turn.
"""

from __future__ import annotations

from aidnd.inference import LLMBadOutput, LLMUnavailable
from aidnd.server.play.engine.core import _S
from aidnd.server.play.engine.worldbuild.assembly import _play


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
    from aidnd import config

    from ..world import _here, _live_build, _live_tick

    city, people, crof, cr2b, loc = _play()  # _play → _apply_routine: passive world synced
    lv = _S.get("live")
    if not lv or lv["loc"] != loc or lv.get("who") != frozenset(_here(loc, crof)):
        _live_build(city, people, crof, cr2b, loc)
    if config.NO_LLM_TICKS:  # debug: the hall stays quiet — no NPC decisions this turn
        return {"feed": [], "address": [], "digest": ""}
    try:
        feed, address = _live_tick(people)  # live scene: those nearby
        # end-of-tick scene narrator: weave observable events into ONE third-person account,
        # laundering raw first-person self-narration / intent out of the player-visible prose.
        digest = ""
        if feed:
            from ..narrator.scene_digest import scene_digest
            digest = scene_digest(feed, (lv or {}).get("place", loc))
    except (LLMUnavailable, LLMBadOutput):  # no model won't pretend — honest error to player
        raise
    except Exception:  # noqa: BLE001 — other tick bugs don't drop the player's action
        import logging

        logging.getLogger("aidnd").warning("live tick failed", exc_info=True)
        return {"feed": [], "address": [], "digest": ""}
    return {"feed": feed, "address": address, "digest": digest}


def _world_tick_fast() -> dict:
    """FAST half of the tick: sync the passive world and build the live scene POSITIONS
    (who's near, where they sit — NO LLM), so a move/enter shows the room instantly. The slow
    half — NPCs think/talk (_live_tick, many LLM calls) — is streamed afterwards by the client
    calling /api/play/live, so entering a crowded tavern never blocks. `live_pending` tells the
    client to fetch that reaction."""
    from ..world import _here, _live_build

    city, people, crof, cr2b, loc = _play()
    lv = _S.get("live")
    if not lv or lv["loc"] != loc or lv.get("who") != frozenset(_here(loc, crof)):
        _live_build(city, people, crof, cr2b, loc)
    return {"feed": [], "address": [], "live_pending": True}
