"""Рутина: НУЖДЫ + характер + время → куда пойти. Эмерджентно, БЕЗ хардкода ролей.

Один шаг NPC: (1) нужды эволюционировали за прошедшее время, гасясь тем местом, где он стоял;
(2) из доступных ему мест (Candidate) выбираем по utility (places.score); близкие по счёту —
разыгрываем сидированным rng (живая вариативность, но воспроизводимость мира без игрока).

Место-агностично: candidates строит адаптер (server/play/worldsim), зная здания мира. Здесь —
чистая логика выбора. Ни сервера, ни БД.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import needs as _needs
from . import places as _places


@dataclass
class Candidate:
    """Доступное NPC место: тип (place-kind) + узел графа, куда идти.
    window_kind — чьё ОКНО суток применять (работник таверны живёт её вечерним окном)."""
    kind: str
    node: int
    window_kind: str | None = None


def step(state, candidates: list, phase: str, minutes: float, here_kind: str | None, rng,
         stay: int | None = None):
    """Продвинуть нужды NPC и вернуть (узел, вид-занятия), куда он направляется.
    state — NpcState (нужды в .needs, черты в .config.traits); here_kind — тип места, где он
    стоял (гасил нужды); candidates — куда он МОЖЕТ пойти; stay — узел, где стоял (инерция)."""
    traits = state.config.traits
    sated = _places.PLACE[here_kind].sates if here_kind in _places.PLACE else {}
    _needs.advance(state.needs, minutes, sated)
    c = choose_c(state.needs, traits, candidates, phase, rng, stay=stay)
    return (c.node, c.kind) if c is not None else (None, None)


def choose_c(needs: dict, traits: dict, candidates: list, phase: str, rng, stay: int | None = None):
    """Выбрать КАНДИДАТА по полезности (близкие — жребием). stay — узел, где стоял: лёгкая
    инерция против дёрганья между равными местами (урок Sims)."""
    pressured = _needs.pressure(needs, traits)
    scored = sorted(((_places.score(c.kind, pressured, traits, phase,
                                    window_kind=c.window_kind)
                      * (1.12 if stay is not None and c.node == stay else 1.0), c)
                     for c in candidates if c.node is not None),
                    key=lambda x: x[0], reverse=True)
    if not scored:
        return None
    best = scored[0][0]
    close = [c for s, c in scored if s >= best * 0.85] or [scored[0][1]]
    return rng.choice(close) if len(close) > 1 else scored[0][1]


def choose(needs: dict, traits: dict, candidates: list, phase: str, rng, stay: int | None = None):
    """Узел лучшего кандидата (обратная совместимость)."""
    c = choose_c(needs, traits, candidates, phase, rng, stay=stay)
    return c.node if c is not None else None


def explain(needs: dict, traits: dict, candidates: list, phase: str) -> list:
    """Диагностика (для /minddebug и тестов): [(kind, score)] по убыванию — почему пошёл туда."""
    pressured = _needs.pressure(needs, traits)
    return sorted(((c.kind, round(_places.score(c.kind, pressured, traits, phase), 3))
                   for c in candidates if c.node is not None), key=lambda x: x[1], reverse=True)
