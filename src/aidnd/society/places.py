"""Места-как-удовлетворители-нужд — ДЕКЛАРАТИВНЫЙ, МОДУЛЬНЫЙ каталог. Добавить тип места, что
закрывает нужду = добавить один PlaceKind в PLACES.

Место «рекламирует» нужды (advertised actions, The Sims): sates = {нужда: скорость гашения/час}.
Куда NPC пойдёт = utility: окно суток × тяга-по-характеру × Σ(реклама × давление нужды).
`detect` связывает КАТАЛОГ с реальными зданиями мира: по типу/услугам фактшита определяем, какие
place-kind воплощает здание (и значит — какие нужды оно закрывает). Один источник истины и для
рутины (куда идти), и для сцены (что закрыть, стоя тут).
"""

from __future__ import annotations

from dataclasses import dataclass, field

PHASES = ("morning", "day", "evening", "night")


@dataclass(frozen=True)
class PlaceKind:
    """Тип места. sates — какие нужды и как быстро гасит; window — уместность по фазе суток;
    likes — тяга по характеру (черта→вес, применяется как 1+Σ вес·(черта−0.5)); detect — слова
    в типе/услугах здания, что метят это место; gate — кто вообще рассматривает (any|job|guard|
    rogue); mobile — место не привязано к зданию (улица/дозор/промысел — точка на графе)."""
    id: str
    ru: str
    sates: dict = field(default_factory=dict)
    window: dict = field(default_factory=dict)
    likes: dict = field(default_factory=dict)
    detect: tuple = ()
    gate: str = "any"
    mobile: bool = False


# ── КАТАЛОГ МЕСТ (редактируется здесь) ──
PLACES: list[PlaceKind] = [
    PlaceKind("home", "дом", sates={"fatigue": 0.16, "comfort": 0.07},
              window={"morning": 0.45, "day": 0.2, "evening": 0.6, "night": 1.0},
              likes={"sociability": -0.8}),                 # нелюдимого тянет домой
    PlaceKind("work", "работа", sates={"wealth": 0.13, "purpose": 0.08},
              window={"morning": 0.9, "day": 1.0, "evening": 0.35, "night": 0.05},
              likes={"ambition": 0.6, "lawful": 0.4}, gate="job"),
    PlaceKind("tavern", "трактир", sates={"hunger": 0.17, "social": 0.15, "comfort": 0.09},
              window={"morning": 0.25, "day": 0.45, "evening": 1.0, "night": 0.55},
              likes={"sociability": 1.0},
              detect=("трактир", "таверн", "постоял", "кабак", "eat", "drink", "lodging")),
    PlaceKind("temple", "храм", sates={"purpose": 0.13, "comfort": 0.05},
              window={"morning": 0.7, "day": 0.5, "evening": 0.3, "night": 0.1},
              likes={"loyalty": 0.7, "honesty": 0.5, "malice": -0.6},
              detect=("храм", "часовн", "свят", "алтар", "pray")),
    PlaceKind("market", "рынок", sates={"novelty": 0.11, "social": 0.06, "wealth": 0.03},
              window={"morning": 0.6, "day": 0.9, "evening": 0.4, "night": 0.05},
              likes={"curiosity": 0.8},
              detect=("лавк", "рынок", "склад", "оружейн", "кузн", "мастерск", "trade")),
    PlaceKind("street", "улица", sates={"novelty": 0.08, "social": 0.05},
              window={"morning": 0.5, "day": 0.7, "evening": 0.5, "night": 0.15},
              likes={"curiosity": 0.6}, mobile=True),
    PlaceKind("patrol", "дозор", sates={"purpose": 0.14, "wealth": 0.04},
              window={"morning": 0.7, "day": 1.0, "evening": 0.9, "night": 0.55},
              likes={"lawful": 0.6, "bravery": 0.4}, gate="guard", mobile=True),
    PlaceKind("prowl", "промысел", sates={"wealth": 0.13, "novelty": 0.08},
              window={"morning": 0.3, "day": 0.5, "evening": 0.85, "night": 1.0},
              likes={"greed": 0.7, "malice": 0.6, "honesty": -0.7}, gate="rogue", mobile=True),
]

PLACE: dict[str, PlaceKind] = {p.id: p for p in PLACES}


def _blob(building: dict) -> str:
    """Строка для матча detect: тип + имя + услуги фактшита здания."""
    d = building or {}
    return " ".join([str(d.get("type", "")), str(d.get("name", "")),
                     " ".join(d.get("services") or [])]).lower()


def kinds_of(building: dict) -> list[str]:
    """Какие place-kind воплощает здание (по detect). Пусто → не удовлетворяет специфичных нужд."""
    blob = _blob(building)
    return [p.id for p in PLACES if p.detect and any(k in blob for k in p.detect)]


def advertises(building: dict) -> dict:
    """Что здание закрывает: объединение sates всех воплощаемых им place-kind (макс. по нужде).
    ЕДИНЫЙ источник для рутины и для сцены (замена хардкода _live_affordances)."""
    out: dict = {}
    for kid in kinds_of(building):
        for need, rate in PLACE[kid].sates.items():
            out[need] = max(out.get(need, 0.0), rate)
    return out


def affinity(kind: str, traits: dict) -> float:
    """Тяга NPC к месту по характеру: 1 + Σ вес·(черта−0.5), не ниже 0.1."""
    pk = PLACE[kind]
    return max(0.1, 1.0 + sum(w * (traits.get(t, 0.5) - 0.5) for t, w in pk.likes.items()))


def score(kind: str, pressured: dict, traits: dict, phase: str) -> float:
    """Полезность пойти в место этого типа = окно суток × тяга-характера × Σ(реклама × давление)."""
    pk = PLACE[kind]
    pull = sum(rate * pressured.get(need, 0.0) for need, rate in pk.sates.items())
    return pk.window.get(phase, 0.2) * affinity(kind, traits) * pull
