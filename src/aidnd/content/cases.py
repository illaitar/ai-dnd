"""Дознаватели и дела: подозрение к субъекту от заметных поступков и реакция стражи.

Жёсткость привязана к ХАРАКТЕРУ стражи (`watch_temperament` по seed) — в разных городах по-разному:
строгая хватается за дубинку рано, снисходительная больше грозит пальцем, продажную можно подмазать.
Темперамент задаёт и характер капитана (черты/эпитет), и пороги дел (допрос/обвинение/штраф/враждебность).

Дело живёт на `world.cases[subject] = {suspicion, deeds, day}`; подозрение копится за поступки и стихает
со временем. Состояние рантайм-зависимое → персистится явно (как quest_timeline/dungeon_status).
"""

from __future__ import annotations

from ..world.environment import day_number

# темпераменты стражи: пороги (допрос/обвинение), множитель штрафа, склонность к враждебности, подкуп
TEMPERAMENTS = [
    {"key": "strict", "label": "строгая", "traits": ["суровый", "неумолимый"], "epithet": "Железная Рука",
     "q": 0.20, "charge": 0.45, "fine": 1.4, "hostile": 0.8, "bribe": 0.0},
    {"key": "just", "label": "справедливая", "traits": ["дисциплинированный", "справедливый"], "epithet": "Справедливый",
     "q": 0.30, "charge": 0.60, "fine": 1.0, "hostile": 0.5, "bribe": 0.0},
    {"key": "lax", "label": "снисходительная", "traits": ["добродушный", "нерасторопный"], "epithet": "Мягкая Рука",
     "q": 0.45, "charge": 0.80, "fine": 0.7, "hostile": 0.2, "bribe": 0.0},
    {"key": "corrupt", "label": "продажная", "traits": ["алчный", "ушлый"], "epithet": "Мздоимец",
     "q": 0.30, "charge": 0.60, "fine": 1.2, "hostile": 0.4, "bribe": 0.6},
]

# тяжесть поступка → прирост подозрения (на свидетелях × 1.4, без — × 0.6)
DEED_SEV = {
    "attack_townsperson": 0.25, "kill_townsperson": 0.7, "brawl": 0.15,
    "theft": 0.3, "assault_guard": 0.5, "kill_guard": 0.9,
}
DEED_RU = {
    "attack_townsperson": "нападение на горожанина", "kill_townsperson": "убийство в городе",
    "brawl": "драка на улице", "theft": "кража", "assault_guard": "нападение на стражу",
    "kill_guard": "убийство стражника",
}


def watch_temperament(seed: int) -> dict:
    """Характер городской стражи по seed (детерминированно) — разный в разных городах."""
    import random

    from ..gen.seeds import subseed
    return random.Random(subseed(seed, "watch_temperament")).choice(TEMPERAMENTS)


def temperament_of(world) -> dict:
    return getattr(world, "watch_temperament", None) or TEMPERAMENTS[1]


def case_of(world, subject: str) -> dict | None:
    return getattr(world, "cases", {}).get(subject)


def suspicion_of(world, subject: str) -> float:
    c = case_of(world, subject)
    return float(c["suspicion"]) if c else 0.0


def note_deed(world, subject: str, kind: str, place: str, witnessed: bool = True) -> float:
    """Записать заметный поступок → прирост подозрения; вернуть новое подозрение."""
    if not hasattr(world, "cases") or world.cases is None:
        world.cases = {}
    sev = DEED_SEV.get(kind, 0.1) * (1.4 if witnessed else 0.6)
    c = world.cases.setdefault(subject, {"suspicion": 0.0, "deeds": [], "day": day_number(world.clock.tick)})
    c["suspicion"] = round(min(1.0, c["suspicion"] + sev), 3)
    c["deeds"].append({"kind": kind, "place": place, "day": day_number(world.clock.tick), "witnessed": witnessed})
    c["day"] = day_number(world.clock.tick)
    return c["suspicion"]


def decay_cases(world, rate: float = 0.25) -> None:
    """Со временем подозрение стихает (на день без новых дел); пустые дела закрываются."""
    cases = getattr(world, "cases", None) or {}
    today = day_number(world.clock.tick)
    for subj, c in list(cases.items()):
        idle = today - c.get("day", today)
        if idle <= 0:
            continue
        c["suspicion"] = round(max(0.0, c["suspicion"] - rate * idle), 3)
        c["day"] = today
        if c["suspicion"] <= 0.02:
            cases.pop(subj, None)


def wanted_status(world, subject: str) -> str:
    """clear | suspect (под подозрением) | wanted (в розыске) — по порогам темперамента."""
    s = suspicion_of(world, subject)
    t = temperament_of(world)
    if s >= t["charge"]:
        return "wanted"
    if s >= t["q"]:
        return "suspect"
    return "clear"


def confront_action(world, subject: str) -> str:
    """Что делает дознаватель/стража при встрече: none | question | fine | hostile."""
    st = wanted_status(world, subject)
    if st == "clear":
        return "none"
    if st == "suspect":
        return "question"
    t = temperament_of(world)                              # wanted: штраф или враждебность по характеру
    import random

    from ..gen.seeds import subseed
    roll = random.Random(subseed(world.seed, "confront", subject, day_number(world.clock.tick))).random()
    return "hostile" if roll < t["hostile"] else "fine"


def fine_amount(world, subject: str) -> int:
    """Штраф (в зм) за дело — по тяжести дел и множителю темперамента."""
    c = case_of(world, subject)
    if not c:
        return 0
    base = sum(DEED_SEV.get(d["kind"], 0.1) for d in c["deeds"]) * 40
    return max(5, int(base * temperament_of(world)["fine"]))


def clear_case(world, subject: str, drop: float = 1.0) -> None:
    """Снять/смягчить дело (оплата штрафа, оправдание): drop=1.0 закрыть полностью."""
    cases = getattr(world, "cases", None) or {}
    c = cases.get(subject)
    if not c:
        return
    c["suspicion"] = round(max(0.0, c["suspicion"] * (1.0 - drop)), 3)
    if c["suspicion"] <= 0.02:
        cases.pop(subject, None)
