"""Нужды (urges) — ДЕКЛАРАТИВНЫЙ каталог. Добавить нужду = добавить одну строку в NEEDS.

Модель — «мотивы» The Sims / needs-based utility AI (Zubek; GameAIPro, гл.9 Utility Theory) +
паттерны-жизни агентных соцсимуляций (Maslow-иерархия нужд, эволюционирующих во времени):
каждая нужда = число 0..1 («насколько ХОЧУ»), само растёт со временем, гасится в местах, которые
её «рекламируют» (см. places.py). Черта характера усиливает свою нужду (жадный острее хочет денег).

Key functions
   -----------
   Need(...) -> Need : Core dataclass representing one NPC need with growth rate and trait boosting.
   fresh() -> dict : Initialize need levels (0..1) for a new NPC; returns base values.
   pressure(needs, traits) -> dict : Compute effective need pressure with trait boosting.
   advance(needs, minutes, sated) -> dict : Evolve needs over time; sated places reduce them.
   NEEDS : list[Need] : Catalog of 7 game needs with growth rates and trait associations.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Need:
    """Одна нужда. grow — естественный рост «хочу» в час; trait — черта, что усиливает нужду;
    start — базовый уровень при рождении NPC."""
    id: str
    ru: str
    grow: float
    trait: str | None = None
    start: float = 0.2
    desc: str = ""


# ── КАТАЛОГ НУЖД (редактируется здесь; те же 7 id, что в mind.NpcState.needs) ──
NEEDS: list[Need] = [
    Need("hunger",  "голод",     grow=0.055, desc="поесть — трактир, очаг, рынок"),
    Need("fatigue", "усталость", grow=0.045, desc="выспаться — дом, ночлег"),
    Need("social",  "общение",   grow=0.035, trait="sociability", desc="к людям — трактир, площадь"),
    Need("wealth",  "нужда",     grow=0.020, trait="greed",       desc="заработать — работа, промысел"),
    Need("purpose", "смысл",     grow=0.022, trait="ambition",    desc="дело/служение — работа, храм, дозор"),
    Need("comfort", "уют",       grow=0.030, desc="тепло/покой — дом, баня, эль"),
    Need("novelty", "новизна",   grow=0.025, trait="curiosity",   desc="ново — улица, рынок, промысел"),
]

NEED: dict[str, Need] = {n.id: n for n in NEEDS}


def fresh() -> dict:
    """Стартовый вектор нужд для нового NPC."""
    return {n.id: n.start for n in NEEDS}


def pressure(needs: dict, traits: dict | None = None) -> dict:
    """Давление каждой нужды = уровень × усиление чертой (жадный сильнее тянется к деньгам).
    Черта 0.5 нейтральна; 1.0 → ×1.5; 0.0 → ×0.5."""
    traits = traits or {}
    out = {}
    for n in NEEDS:
        lvl = needs.get(n.id, n.start)
        amp = 1.0 + (traits.get(n.trait, 0.5) - 0.5) if n.trait else 1.0
        out[n.id] = max(0.0, lvl * amp)
    return out


def advance(needs: dict, minutes: float, sated: dict | None = None) -> dict:
    """Эволюция нужд за `minutes`. Место, где стоит NPC, ГАСИТ рекламируемые им нужды (sated:
    {need: rate/час}); прочие — растут естественно. Мутирует и возвращает needs."""
    hours = max(0.0, minutes) / 60.0
    sated = sated or {}
    for n in NEEDS:
        cur = needs.get(n.id, n.start)
        rate = sated.get(n.id)
        cur += (-rate if rate else n.grow) * hours
        needs[n.id] = min(1.0, max(0.0, cur))
    return needs
