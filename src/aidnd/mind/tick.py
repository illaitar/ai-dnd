"""Ход мира: один тик. Пока — рост нужд + распад эмоций к базе (декол. дин-ка эмоций).
Решения/действия NPC дёргаются вручную (дебаг) или будущим арбитром. Апрейзал — фикс. функция
измерения→эмоции (по обсуждению): сюда подаём вектор измерений, получаем дельты каналов.
"""

from __future__ import annotations

import math

from .model import EMOTIONS, NEEDS, NpcState, Scene

_NEED_RATE = {"fatigue": 0.015, "hunger": 0.02, "social": 0.012}
_HALFLIFE = {"anger": 6.0, "fear": 4.0, "joy": 8.0, "distress": 36.0}   # в тиках


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


def advance(state: NpcState, scene: Scene, ticks: int = 1) -> dict:
    for _ in range(max(1, ticks)):
        scene.clock += 1
        _decay_needs(state)
        _decay_emotion(state)
    return {"clock": scene.clock, "needs": {k: round(v, 2) for k, v in state.needs.items()},
            "emotion": {k: round(v, 2) for k, v in state.emotion.items()}}


# ── апрейзал: вектор измерений → дельты эмоций (фикс. функция, малая «таблица») ──
def appraise(state: NpcState, dims: dict, source: str | None = None) -> dict:
    """dims: goal_impact[-1..1], intent(deliberate?), desert[-1..1], harm[0..1], control[0..1],
    norm[-1..1]. Меняет каналы эмоций (×gain из черт) + адресное снятие злости при norm>0."""
    gi = float(dims.get("goal_impact", 0.0))
    desert = float(dims.get("desert", 0.0))
    harm = float(dims.get("harm", 0.0))
    control = float(dims.get("control", 0.0))
    norm = float(dims.get("norm", 0.0))
    deliberate = bool(dims.get("intent") in (True, "deliberate"))
    delta = {
        "joy": max(0.0, gi),
        "distress": max(0.0, -gi) * (1 - control),
        "anger": max(0.0, -gi) * max(0.0, -desert) * (1.0 if deliberate else 0.3),
        "fear": harm * (1 - control),
    }
    for e, d in delta.items():
        if d <= 0:
            continue
        state.emotion[e] = max(0.0, min(1.0, state.emotion.get(e, 0.0) + d * state.emotion_gain(e)))
        if source:
            state.emotion_target[e] = source
    if norm > 0 and source and state.emotion.get("anger", 0.0) > 0:   # обида снята — адресно
        state.emotion["anger"] = max(0.0, state.emotion["anger"] - norm * 0.6)
    return {"emotion": {k: round(v, 2) for k, v in state.emotion.items()}}
