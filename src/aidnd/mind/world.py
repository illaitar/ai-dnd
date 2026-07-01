"""Микромир для симуляции разума: места-граф + тела-агенты + предметы.

Это ЧИСТЫЙ стенд для проверки эмерджентных сценариев — без citygraph/LLM. Тот же контур
value/act позже подключится к настоящему городу (citygraph.City как подложка мест). Здесь
ничего «про сценарий» не зашито: только тела с наблюдаемыми атрибутами и граф мест.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

ENEMY_FACTIONS = {"monster", "bandit", "outlaw"}


@dataclass
class Item:
    name: str
    value: float = 0.2          # базовая ценность [0..1] (объективная; worth субъективирует её)
    satisfies: str | None = None  # если удовлетворяет нужду: имя нужды (hunger/purpose/…)
    kind: str = "good"          # good | coin (деньги — такой же предмет)
    amount: float = 1.0         # для делимого (монеты — сумма в кошеле)


@dataclass
class Body:
    """Физическое тело агента в мире (NPC-разум ссылается на него по id)."""
    id: str
    place: str
    hp: int = 10
    max_hp: int = 10
    power: float = 1.0          # боевая сила
    appearance: float = 0.2     # видимое богатство [0..1] (богатая одежда)
    attention: float = 0.7      # бдительность [0..1] (низкая → легко обокрасть)
    faction: str = "town"
    carrying: list = field(default_factory=list)    # Item — на виду
    loot: list = field(default_factory=list)        # Item — добыча (кошель и т.п.)
    attacking: str | None = None                    # кого атакует прямо сейчас (для защиты союзника)
    alive: bool = True

    def down(self) -> bool:
        return self.hp <= 0 or not self.alive


@dataclass
class World:
    places: dict = field(default_factory=dict)      # place -> [neighbors]
    bodies: dict = field(default_factory=dict)       # id -> Body
    ground: dict = field(default_factory=dict)       # place -> [Item] (бесхозное)
    risk: dict = field(default_factory=dict)         # place -> базовый риск узла [0..1]

    def link(self, a: str, b: str) -> None:
        self.places.setdefault(a, [])
        self.places.setdefault(b, [])
        if b not in self.places[a]:
            self.places[a].append(b)
        if a not in self.places[b]:
            self.places[b].append(a)

    def add(self, body: Body) -> Body:
        self.bodies[body.id] = body
        self.places.setdefault(body.place, [])
        return body

    def neighbors(self, p: str) -> list:
        return list(self.places.get(p, []))

    def present_at(self, place: str, exclude=()) -> list:
        return [b for b in self.bodies.values() if b.place == place and b.id not in exclude]

    def dist(self, a: str, b: str) -> int:
        if a == b:
            return 0
        seen, q = {a}, deque([(a, 0)])
        while q:
            x, d = q.popleft()
            for n in self.places.get(x, []):
                if n == b:
                    return d + 1
                if n not in seen:
                    seen.add(n)
                    q.append((n, d + 1))
        return 999
