"""Состояние NPC для гибридной utility-модели агента.

NPC = состояние + способности + utility-арбитр. Здесь — детерминированные данные,
кормящие оценку полезности: нужды (динамика), черты (веса), настроение (короткие
оверлеи), отношения (граф), память, роль/фракция, кошель, импульсивность.

Значения черт — ГИБРИД: детерминированная база от профессии + джиттер по seed
(воспроизводимо, бесплатно, тесты стабильны). `tweak_from_description` — опциональный
хук LLM-правки под авторское описание; офлайн он ничего не делает (чистая база).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

# нужды — давление 0..1, растёт со временем/событиями, действие его утоляет
NEEDS = ("hunger", "fatigue", "safety", "wealth", "social", "purpose")

# черты — статические веса 0..1, масштабируют слагаемые полезности (характер)
TRAITS = ("greed", "bravery", "honesty", "curiosity", "pride",
          "loyalty", "sociability", "ambition", "lawful")

_NEUTRAL_REL = {"affinity": 0.0, "trust": 0.0, "fear": 0.0, "debt": 0}

# профессия → дельты черт от базы 0.5 (детерминированная основа гибрида)
ROLE_TRAITS: dict[str, dict[str, float]] = {
    "стражник":    {"bravery": .25, "lawful": .30, "loyalty": .15},
    "guard":       {"bravery": .25, "lawful": .30, "loyalty": .15},
    "разбойник":   {"greed": .25, "lawful": -.40, "honesty": -.25, "bravery": .10},
    "redbrand":    {"greed": .25, "lawful": -.40, "honesty": -.25, "bravery": .10},
    "торговец":    {"greed": .25, "sociability": .15, "honesty": -.10},
    "merchant":    {"greed": .25, "sociability": .15, "honesty": -.10},
    "лавочник":    {"greed": .20, "sociability": .15, "honesty": -.05},
    "трактирщик":  {"sociability": .25, "honesty": .10, "greed": .10},
    "innkeeper":   {"sociability": .25, "honesty": .10, "greed": .10},
    "жрец":        {"honesty": .20, "loyalty": .20, "lawful": .15, "bravery": .10},
    "priest":      {"honesty": .20, "loyalty": .20, "lawful": .15, "bravery": .10},
    "фермер":      {"bravery": -.15, "honesty": .10, "lawful": .10, "greed": -.05},
    "крестьянин":  {"bravery": -.15, "honesty": .10, "lawful": .10},
    "простолюдин": {"bravery": -.10, "honesty": .05, "lawful": .05},
    "мудрец":      {"curiosity": .30, "ambition": .10, "honesty": .10},
    "маг":         {"curiosity": .25, "ambition": .15, "pride": .15},
    "кузнец":      {"honesty": .10, "pride": .10, "bravery": .10},
    "лекарь":      {"honesty": .15, "loyalty": .15, "sociability": .10},
    "алхимик":     {"curiosity": .20, "greed": .10},
    "травник":     {"honesty": .10, "loyalty": .10, "sociability": .10},
    "писарь":      {"honesty": .10, "lawful": .15, "sociability": .05},
    "нищий":       {"pride": -.25, "honesty": -.10, "bravery": -.15},
    "наёмник":     {"bravery": .20, "greed": .20, "loyalty": -.10},
    "вор":         {"honesty": -.30, "lawful": -.40, "greed": .20, "bravery": -.05},
    "осведомитель":{"honesty": -.15, "greed": .20, "curiosity": .20, "sociability": .15},
    "дознаватель": {"lawful": .30, "curiosity": .25, "bravery": .15},
    "глава":       {"ambition": .35, "pride": .25, "loyalty": .15},
    "сваха":       {"sociability": .35, "curiosity": .15},
}

# профессия → набор «услуг», которые она вообще способна оказывать (гейт способностей)
ROLE_SERVICES: dict[str, set[str]] = {
    "трактирщик": {"lodging", "food"}, "innkeeper": {"lodging", "food"},
    "кузнец": {"craft"}, "оружейник": {"craft"},
    "лекарь": {"heal"}, "жрец": {"heal"}, "priest": {"heal"},
    "алхимик": {"brew", "heal"}, "травник": {"brew", "heal"},
    "писарь": {"scribe"}, "мудрец": {"scribe"},
    "наёмник": {"guide"}, "следопыт": {"guide"},
}


@dataclass
class NpcState:
    """Полное состояние одного NPC — единственный источник входов для арбитра."""

    name: str = "NPC"
    role: str = "простолюдин"
    faction: str = ""
    needs: dict[str, float] = field(default_factory=lambda: {n: 0.15 for n in NEEDS})
    traits: dict[str, float] = field(default_factory=lambda: {t: 0.5 for t in TRAITS})
    mood: set[str] = field(default_factory=set)
    relations: dict[str, dict] = field(default_factory=dict)
    memory: dict = field(default_factory=lambda: {
        "promises": [], "grudges": set(), "debts": {}, "secrets_of": set(), "witnessed": []})
    wallet: int = 20
    temp: float = 0.45                      # температура softmax — импульсивность выбора
    agenda: list = field(default_factory=list)   # шаги тайного плана (важные NPC)

    def n(self, k: str) -> float:
        return self.needs.get(k, 0.0)

    def t(self, k: str) -> float:
        return self.traits.get(k, 0.5)

    def rel(self, other: str) -> dict:
        return self.relations.get(other, _NEUTRAL_REL)

    def has_mood(self, m: str) -> bool:
        return m in self.mood

    def can_serve(self, service: str) -> bool:
        return service in ROLE_SERVICES.get(self.role, set())


def make_state(name: str = "NPC", role: str = "простолюдин", faction: str = "",
               seed: int = 0, **over) -> NpcState:
    """Собрать NPC: база черт по профессии + воспроизводимый джиттер по seed.
    `over` позволяет точечно переопределить поля (needs/traits/relations/...)."""
    rng = random.Random(f"{name}|{role}|{seed}")
    traits = {k: 0.5 for k in TRAITS}
    for k, d in ROLE_TRAITS.get(role, {}).items():
        traits[k] = traits.get(k, 0.5) + d
    for k in traits:
        traits[k] = min(1.0, max(0.0, traits[k] + rng.uniform(-0.08, 0.08)))
    s = NpcState(name=name, role=role, faction=faction, traits=traits)
    s.temp = min(0.9, max(0.2, 0.45 + rng.uniform(-0.1, 0.1)))
    for k, v in over.items():
        setattr(s, k, v)
    return s


def tweak_from_description(state: NpcState, description: str, model=None) -> NpcState:
    """Хук гибрида: при наличии LLM сдвинуть черты под авторское описание персонажа.
    Офлайн/без модели — no-op (остаётся детерминированная база). Подключается позже."""
    if not model or not description:
        return state
    try:
        from ..inference.agents import tweak_traits  # подключим при интеграции
    except Exception:
        return state
    deltas = tweak_traits(model, description, list(TRAITS)) or {}
    for k, d in deltas.items():
        if k in state.traits:
            state.traits[k] = min(1.0, max(0.0, state.traits[k] + float(d)))
    return state
