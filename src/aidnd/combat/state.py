"""Боевое состояние: машина состояний, бойцы, экономика действий, сетка (док 09).

Тактический бой «как в Baldur's Gate»: позиции на сетке, бюджет движения в футах,
поверхности на клетках. Позиции живут ТОЛЬКО внутри энкаунтера.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .grid import BattleGrid


@dataclass
class TurnBudget:
    """Экономика действий 5e как бюджет хода (док 09 §3)."""

    action: bool = True
    bonus_action: bool = True
    reaction: bool = True
    movement: int = 30          # остаток в футах
    dashed: bool = False

    @staticmethod
    def fresh(speed: int = 30) -> TurnBudget:
        return TurnBudget(movement=speed)


@dataclass
class Combatant:
    entity_id: str
    initiative: int = 0
    ac: int = 10
    side: str = "enemy"             # party | enemy
    pos: tuple = (0, 0)             # (col, row) на сетке
    reactions_used: int = 0
    concentration: str | None = None
    fled: bool = False
    dodging: bool = False           # Dodge: атаки по нему с помехой
    disengaging: bool = False       # Disengage: не провоцирует AoO
    death_successes: int = 0
    death_failures: int = 0
    stable: bool = False


@dataclass
class Surface:
    kind: str                       # fire | grease | water | ice | poison
    rounds: int = 3


@dataclass
class CombatState:
    grid: BattleGrid = field(default_factory=BattleGrid.empty)
    combatants: dict[str, Combatant] = field(default_factory=dict)
    initiative_order: list[str] = field(default_factory=list)
    surfaces: dict[tuple, Surface] = field(default_factory=dict)   # (col,row) -> Surface
    round: int = 1
    turn_index: int = 0
    turn_budget: TurnBudget = field(default_factory=TurnBudget.fresh)
    mode: str = "active"            # active | ended
    outcome: str | None = None      # victory | flee | tpk
    town: bool = False              # бой в городе → давление времени: стража + бегство (раунд=5с)
    guard_eta: int = 0              # раунд прибытия ближайшего патруля (по расстоянию, не рандом)
    guard_patrol: str = ""          # какой патруль отвечает (имя)
    guard_intervened: bool = False  # драку разняла городская стража (нападавшие бежали)
    log: list[str] = field(default_factory=list)

    def current(self) -> str | None:
        return self.initiative_order[self.turn_index] if self.initiative_order else None

    def occupied(self, exclude: str | None = None) -> set:
        return {c.pos for eid, c in self.combatants.items()
                if eid != exclude and not c.fled and c.pos is not None}

    def at(self, cell: tuple) -> str | None:
        for eid, c in self.combatants.items():
            if c.pos == cell and not c.fled:
                return eid
        return None
