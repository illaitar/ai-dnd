"""CASTING — pure code (spec §5 Step 4). Doran motivation → contract kind (tone) + reward shape
(real purse, capped) + DC/danger from the villain's real stats. The contract STEP itself is the
Inc-1 bridge's milestone→step translation, so completion flows through the unchanged triggers."""

from __future__ import annotations

from aidnd.mind.agenda import Milestone
from aidnd.server.play.engine.quests import bridge

REWARD_CAP = 30
_DC_BASE = 10

MOTIV_KIND = {"serenity": "bring", "justice": "dead", "protection": "deliver",
              "recognition": "befriend", "curiosity": "visit"}


def _milestone(seed: dict) -> Milestone:
    g = seed["goal"]
    return Milestone(desc="", kind=g.get("kind", "acquire"), target=g.get("target"),
                     done=dict(g["done"]))


def cast(seed: dict, giver_state, villain_state, store, wid) -> dict:
    step = bridge.milestone_to_step(_milestone(seed)) or {"kind": "bring", "want": None}
    purse = store.purse_get(wid, giver_state.config.id)
    reward = min(REWARD_CAP, max(0, purse))
    malice = villain_state.config.traits.get("malice", 0.3) if villain_state else 0.3
    dc = _DC_BASE + round(malice * 10)              # code-owned; villain's real trait drives danger
    return {"step": step, "reward": reward, "dc": dc, "danger": round(malice, 2),
            "motivation": seed.get("motivation")}
