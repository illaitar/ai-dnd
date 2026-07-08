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
    from ..world import _here, _live_build, _live_tick

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
