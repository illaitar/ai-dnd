"""Microworld for simulating a mind: place-graph + bodies-agents + items.

This is a CLEAN test bench for checking emergent scenarios — without citygraph/LLM. The same
value/act loop will later connect to the real city (citygraph.City as place substrate). Nothing
"about scenario" is hardcoded here: only bodies with observable attributes and a place graph.

Key functions
-------------
Item(name, value, ...) -> Item : defines an inventory item with satisfaction effect.
Body(id, place, ...) -> Body : defines a physical agent with stats and inventory.
World() -> World : container for the place graph and agents in simulation.
World.link(a, b) -> None : connect two places bidirectionally in the graph.
World.add(body) -> Body : register an agent body into the simulation.
World.present_at(place) -> list : return all agents currently at a location.
World.dist(a, b) -> int : compute shortest path distance between locations.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

ENEMY_FACTIONS = {"monster", "bandit", "outlaw"}


@dataclass
class Item:
    name: str
    value: float = 0.2          # base value [0..1] (objective; worth subjectifies it)
    satisfies: str | None = None  # if satisfies a need: name of the need (hunger/purpose/…)
    kind: str = "good"          # good | coin (coins are the same item type)
    amount: float = 1.0         # for divisible items (coins — sum in wallet)


@dataclass
class Body:
    """Physical body of an agent in the world (NPC-mind references it by id)."""
    id: str
    place: str
    hp: int = 10
    max_hp: int = 10
    power: float = 1.0          # combat power
    appearance: float = 0.2     # visible WEALTH [0..1] (rich clothes → target for a predator)
    charisma: float = 0.3       # attractiveness/charm [0..1] (draws toward TALK, not rob)
    attention: float = 0.7      # vigilance [0..1] (low → easy to pickpocket)
    faction: str = "town"
    carrying: list = field(default_factory=list)    # Item — in plain sight
    loot: list = field(default_factory=list)        # Item — loot (wallet, etc.)
    attacking: str | None = None                    # whom to attack right now (to defend an ally)
    talking_to: str | None = None                   # whom to talk to right now (pairs; crowd around a "star")
    alive: bool = True

    def down(self) -> bool:
        return self.hp <= 0 or not self.alive


@dataclass
class World:
    places: dict = field(default_factory=dict)      # place -> [neighbors]
    bodies: dict = field(default_factory=dict)       # id -> Body
    ground: dict = field(default_factory=dict)       # place -> [Item] (unclaimed)
    risk: dict = field(default_factory=dict)         # place -> base node risk [0..1]

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
