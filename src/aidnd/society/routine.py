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
    """Доступное NPC место: тип (place-kind) + узел графа, куда идти."""
    kind: str
    node: int


def step(state, candidates: list, phase: str, minutes: float, here_kind: str | None, rng) -> int:
    """Продвинуть нужды NPC и вернуть узел, куда он направляется.
    state — NpcState (нужды в .needs, черты в .config.traits); here_kind — тип места, где он
    стоял (гасил нужды); candidates — куда он МОЖЕТ пойти; minutes — сколько прошло."""
    traits = state.config.traits
    sated = _places.PLACE[here_kind].sates if here_kind in _places.PLACE else {}
    _needs.advance(state.needs, minutes, sated)
    return choose(state.needs, traits, candidates, phase, rng)


def choose(needs: dict, traits: dict, candidates: list, phase: str, rng) -> int | None:
    """Выбрать узел по полезности. Возвращает node лучшего кандидата (близкие — жребием)."""
    pressured = _needs.pressure(needs, traits)
    scored = sorted(((_places.score(c.kind, pressured, traits, phase), c) for c in candidates
                     if c.node is not None), key=lambda x: x[0], reverse=True)
    if not scored:
        return None
    best = scored[0][0]
    close = [c for s, c in scored if s >= best * 0.85] or [scored[0][1]]
    return rng.choice(close).node if len(close) > 1 else scored[0][1].node


def explain(needs: dict, traits: dict, candidates: list, phase: str) -> list:
    """Диагностика (для /minddebug и тестов): [(kind, score)] по убыванию — почему пошёл туда."""
    pressured = _needs.pressure(needs, traits)
    return sorted(((c.kind, round(_places.score(c.kind, pressured, traits, phase), 3))
                   for c in candidates if c.node is not None), key=lambda x: x[1], reverse=True)
