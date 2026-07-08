"""World tick: one tick. For now — need growth + emotion decay to baseline (emotional dynamics).
NPC decisions/actions are triggered manually (debug) or by a future arbiter. Appraisal — fixed function
measurement→emotion (as discussed): feed a measurement vector, get emotion channel deltas.

Key functions
-------------
advance(state, scene, ticks, stim) -> dict : Advances NPC state by ticks, updating needs, emotions, and FSM.
appraise(state, dims, source) -> dict : Calculates emotion deltas from appraisal dimensions and updates emotion state.
"""

from __future__ import annotations

import math

from .fsm import step as fsm_step
from .model import EMOTIONS, NEEDS, NpcState, Scene

_NEED_RATE = {"fatigue": 0.015, "hunger": 0.02, "social": 0.012, "purpose": 0.01,
              "wealth": 0.006, "comfort": 0.008, "novelty": 0.014}
_HALFLIFE = {"anger": 6.0, "fear": 4.0, "joy": 8.0, "distress": 36.0}   # in ticks


def _decay_needs(state: NpcState) -> None:
    for n in NEEDS:
        state.needs[n] = min(1.0, state.needs.get(n, 0.0) + _NEED_RATE.get(n, 0.01))


def _decay_emotion(state: NpcState, dt: int = 1) -> None:
    for e in EMOTIONS:
        base = state.emotion_baseline(e)
        cur = state.emotion.get(e, 0.0)
        cur += (base - cur) * (1 - math.exp(-dt / _HALFLIFE.get(e, 6.0)))
        state.emotion[e] = max(0.0, min(1.0, cur))
        if state.emotion[e] <= base + 1e-3:
            state.emotion_target.pop(e, None)


def advance(state: NpcState, scene: Scene, ticks: int = 1, stim: dict | None = None) -> dict:
    trace = None
    for _ in range(max(1, ticks)):
        scene.clock += 1
        _decay_needs(state)                              # time passes — needs grow
        trace = fsm_step(state, scene, stim)             # decide on FRESH emotions + grown needs
        _decay_emotion(state)                            # emotions fade by next tick
        stim = None                                      # stimulus is one-time — only first tick
    return {"clock": scene.clock, "mode": state.mode, "fsm": trace,
            "needs": {k: round(v, 2) for k, v in state.needs.items()},
            "emotion": {k: round(v, 2) for k, v in state.emotion.items()}}


# ── appraisal: measurement vector → emotion deltas (fixed function, small "table") ──
def appraise(state: NpcState, dims: dict, source: str | None = None) -> dict:
    """dims: goal_impact[-1..1], intent(deliberate?), desert[-1..1], harm[0..1], control[0..1],
    norm[-1..1], revulsion[0..1]. Updates emotion channels (×gain from traits) + targeted anger
    reduction when norm>0."""
    gi = float(dims.get("goal_impact", 0.0))
    desert = float(dims.get("desert", 0.0))
    harm = float(dims.get("harm", 0.0))
    control = float(dims.get("control", 0.0))
    norm = float(dims.get("norm", 0.0))
    rev = float(dims.get("revulsion", 0.0))
    deliberate = bool(dims.get("intent") in (True, "deliberate"))
    delta = {
        "joy": max(0.0, gi),
        "distress": max(0.0, -gi) * (1 - control),
        "anger": max(0.0, -gi) * max(0.0, -desert) * (1.0 if deliberate else 0.3),
        "fear": harm * (1 - control),
        "disgust": max(0.0, rev),
    }
    for e, d in delta.items():
        if d <= 0:
            continue
        state.emotion[e] = max(0.0, min(1.0, state.emotion.get(e, 0.0) + d * state.emotion_gain(e)))
        if source:
            state.emotion_target[e] = source
    if norm > 0 and source and state.emotion.get("anger", 0.0) > 0:   # insult resolved — targeted
        state.emotion["anger"] = max(0.0, state.emotion["anger"] - norm * 0.6)
    return {"emotion": {k: round(v, 2) for k, v in state.emotion.items()}}
