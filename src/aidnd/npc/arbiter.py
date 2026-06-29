"""Utility-арбитр с вероятностным выбором.

НЕ argmax: оценить доступные способности → отсечь по порогу РЕАЛИСТИЧНОСТИ (держим тех,
чья польза ≥ REALISM·лучшей) → взять top-k → выбрать ОДНУ по взвешенной вероятности
(softmax по полезности). Тот же NPC в том же состоянии не всегда повторяет действие, но
почти всегда остаётся в рамках разумного — заведомо плохие варианты не семплируются.

Температура (state.temp) = импульсивность: ниже → ближе к лучшему, выше → разнообразнее.
"""

from __future__ import annotations

import math
import random

from .capabilities import CAPABILITIES

REALISM = 0.55      # порог: кандидат держится, если польза ≥ REALISM · лучшей
TOPK = 3            # сколько правдоподобных вариантов оставить под жребий
FLOOR = 0.05        # ниже этого действие вообще не рассматривается


def evaluate(state, ctx, caps=None) -> list[tuple]:
    """Все доступные способности с их полезностью, по убыванию. [(Cap, utility), ...]."""
    caps = caps if caps is not None else CAPABILITIES
    out = []
    for c in caps:
        try:
            if not c.available(state, ctx):
                continue
            u = float(c.score(state, ctx))
        except Exception:
            continue
        if u > FLOOR:
            out.append((c, u))
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def shortlist(scored: list[tuple]) -> list[tuple]:
    """Top-k правдоподобных: в полосе REALISM от лучшего, не более TOPK."""
    if not scored:
        return []
    umax = scored[0][1]
    band = [cu for cu in scored if cu[1] >= REALISM * umax]
    return band[:TOPK]


def choose(state, ctx, rng=None, caps=None) -> tuple:
    """Выбрать одну способность. → (Cap | None, shortlist[(Cap, utility), ...])."""
    rng = rng or random.Random()
    scored = evaluate(state, ctx, caps)
    top = shortlist(scored)
    if not top:
        return None, []
    temp = max(0.12, state.temp)
    us = [u for _, u in top]
    m = max(us)
    weights = [math.exp((u - m) / temp) for u in us]
    total = sum(weights) or 1.0
    r = rng.random() * total
    acc = 0.0
    for (cap, _u), w in zip(top, weights):
        acc += w
        if r <= acc:
            return cap, top
    return top[-1][0], top


def choose_multi(state, ctxs, rng=None) -> tuple:
    """Выбор по НЕСКОЛЬКИМ стимулам сразу (напр. self-care «tick» + социальный «meet_npc»):
    объединить оценки (по ключу — максимум), отсечь по реалистичности, top-k, softmax-жребий.
    → (Cap | None, shortlist)."""
    rng = rng or random.Random()
    best: dict = {}
    for ctx in ctxs:
        for cap, u in evaluate(state, ctx):
            if cap.key not in best or u > best[cap.key][1]:
                best[cap.key] = (cap, u)
    merged = sorted(best.values(), key=lambda x: x[1], reverse=True)
    top = shortlist(merged)
    if not top:
        return None, []
    temp = max(0.12, state.temp)
    us = [u for _, u in top]
    m = max(us)
    weights = [math.exp((u - m) / temp) for u in us]
    total = sum(weights) or 1.0
    r = rng.random() * total
    acc = 0.0
    for (cap, _u), w in zip(top, weights):
        acc += w
        if r <= acc:
            return cap, top
    return top[-1][0], top


def distribution(state, ctx, caps=None) -> list[tuple]:
    """Вероятности выбора по shortlist (для анализа/тестов). [(key, p), ...]."""
    top = shortlist(evaluate(state, ctx, caps))
    if not top:
        return []
    temp = max(0.12, state.temp)
    m = max(u for _, u in top)
    weights = [math.exp((u - m) / temp) for _, u in top]
    total = sum(weights) or 1.0
    return [(cap.key, w / total) for (cap, _u), w in zip(top, weights)]
