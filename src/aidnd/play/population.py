"""Население городка на новом стеке: обобщённые фэнтези-жители (имена/роли/черты), у каждого —
мозг (mind.NpcState), размещённые на карте citygraph (ключевые здания = места работы, дома = жильё).
Никакого Фэндалина: роли и имена — родовые для фронтира. Детерминировано по seed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from ..mind import TRAITS, NpcConfig, NpcState

_MALE = ["Бран", "Горм", "Освин", "Тэд", "Ральф", "Кедрик", "Дунн", "Обер", "Хальд", "Ветл",
         "Сим", "Рэн", "Тол", "Ланн", "Ход", "Мерек"]
_FEMALE = ["Мара", "Сельма", "Лия", "Нэлл", "Гвен", "Ода", "Ирма", "Хельга", "Бета", "Юна",
           "Аля", "Мойра", "Тира", "Роза", "Виль", "Эмса"]
_SURN = ["Камнехват", "Тихвуд", "Долинный", "Пивовар", "Кожемяка", "Рыжий", "с Холма",
         "Вересковый", "Косой", "Быстрый", "Медовар", "Тёмный", "Полынь", "Овражный"]

# роли ключевых зданий (по кругу) — родовой набор фронтирного городка
KEY_ROLES = ["трактирщик", "кузнец", "лавочник", "стражник", "жрец", "знахарка",
             "бард", "мельник", "дубильщик", "сапожник"]

ROLE_TRAITS: dict[str, dict[str, float]] = {
    "трактирщик": {"sociability": .8, "honesty": .6, "greed": .55},
    "кузнец": {"honesty": .6, "pride": .6, "bravery": .6},
    "лавочник": {"greed": .72, "sociability": .6, "honesty": .5},
    "стражник": {"lawful": .85, "loyalty": .8, "bravery": .8, "honesty": .7, "malice": .05},
    "жрец": {"honesty": .85, "loyalty": .7, "lawful": .7, "malice": .0},
    "знахарка": {"honesty": .85, "sociability": .7, "loyalty": .7},
    "бард": {"sociability": .9, "curiosity": .7, "pride": .6},
    "мельник": {"honesty": .55, "greed": .55},
    "дубильщик": {"honesty": .55, "bravery": .45},
    "сапожник": {"honesty": .6, "sociability": .55},
    "горожанин": {"honesty": .55, "bravery": .45},
    "бродяга": {"greed": .85, "honesty": .12, "lawful": .15, "bravery": .4},        # мелкий вор
    "головорез": {"greed": .7, "bravery": .8, "honesty": .25, "lawful": .2, "malice": .4},
}
_CHA = {"бард": .85, "трактирщик": .7, "знахарка": .6, "жрец": .55, "лавочник": .5}
_WEALTH = {"лавочник": .6, "трактирщик": .5, "кузнец": .45, "мельник": .5, "жрец": .35}


@dataclass
class Townsperson:
    id: str
    name: str
    role: str
    home: int                       # узел-жильё (citygraph)
    work: str | None                # id ключевого здания (место работы) / None
    charisma: float
    appearance: float               # видимое богатство
    state: NpcState = field(default=None)

    def view(self) -> dict:
        return {"id": self.id, "name": self.name, "role": self.role, "home": self.home,
                "work": self.work, "charisma": round(self.charisma, 2),
                "appearance": round(self.appearance, 2)}


def _name(rng: random.Random) -> str:
    first = rng.choice(_MALE if rng.random() < 0.5 else _FEMALE)
    return f"{first} {rng.choice(_SURN)}"


def _traits(role: str, rng: random.Random) -> dict:
    t = {k: 0.5 for k in TRAITS}
    for k, v in ROLE_TRAITS.get(role, {}).items():
        t[k] = v
    for k in t:
        t[k] = min(1.0, max(0.0, t[k] + rng.uniform(-0.08, 0.08)))
    return t


def _person(pid: str, role: str, home: int, work: str | None, rng: random.Random) -> Townsperson:
    name = _name(rng)
    cfg = NpcConfig(id=pid, name=name, role=role, traits=_traits(role, rng))
    st = NpcState.from_config(cfg)
    for n in st.needs:                              # лёгкий фон нужд
        st.needs[n] = round(rng.uniform(0.1, 0.35), 2)
    cha = min(1.0, max(0.1, _CHA.get(role, 0.3) + rng.uniform(-0.1, 0.1)))
    app = min(1.0, max(0.1, _WEALTH.get(role, 0.25) + rng.uniform(-0.08, 0.08)))
    return Townsperson(pid, name, role, home, work, cha, app, st)


def populate(city, seed: int = 1, commoners: int = 12, deviants: int = 2) -> dict:
    """Заселить городок: работники ключевых зданий + горожане по домам + пара отклонений."""
    rng = random.Random(f"pop|{seed}")
    houses = [h.node for h in city.houses.values()]
    rng.shuffle(houses)
    hi = iter(houses)
    people: dict[str, Townsperson] = {}

    for i, (bid, kb) in enumerate(sorted(city.key_buildings.items())):
        role = KEY_ROLES[i % len(KEY_ROLES)]
        p = _person(f"npc:key{i}", role, next(hi, kb.interior), bid, rng)
        people[p.id] = p

    for i in range(commoners):
        p = _person(f"npc:town{i}", "горожанин", next(hi, 0), None, rng)
        people[p.id] = p

    for i in range(deviants):
        role = "бродяга" if i % 2 == 0 else "головорез"
        p = _person(f"npc:rogue{i}", role, next(hi, 0), None, rng)
        people[p.id] = p

    return people
