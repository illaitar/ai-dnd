"""Event sourcing: единственный способ менять мир — записать событие в
append-only log (main §3.3, док 08 §4).

Текущее состояние — свёртка событий. RollRecord (док 07 §7) заменил dice_seed:
хранит выпавшие грани и источник, поэтому replay подставляет грани, а не
пересевает. Сид остаётся для авто-бросков и предгенерации мира.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass
class RollRecord:
    """Запись броска в логе для точного реплея (док 07 §7)."""

    request_id: str
    dice: str                       # "1d20", "2d6+3"
    raw: list[int]                  # выпавшие грани
    total: int                      # после adv/dis и модификатора
    nat: int = 0                    # грань d20 для крита/фамбла
    source: str = "server_seeded"   # player_ui | player_manual | server_seeded
    seed: int | None = None         # только для server_seeded

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> RollRecord:
        return RollRecord(**d)


@dataclass
class Event:
    """Единица изменения мира (main §3.3).

    Event(tick, actor, verb, target, payload, roll). roll — RollRecord или None.
    """

    tick: int
    actor: str
    verb: str
    target: str | None = None
    payload: dict = field(default_factory=dict)
    roll: RollRecord | None = None
    seq: int = 0  # глобальный порядковый номер, проставляет лог

    @property
    def touches_memory(self) -> bool:
        """Затрагивает ли событие память NPC (для апдейта vector index, док 08 §4)."""
        return self.verb in {
            "talk", "attack", "give", "steal", "persuade", "intimidate",
            "help", "threaten", "trade", "observe",
        }

    def to_dict(self) -> dict:
        d = asdict(self)
        d["roll"] = self.roll.to_dict() if self.roll else None
        return d

    @staticmethod
    def from_dict(d: dict) -> Event:
        roll = d.get("roll")
        return Event(
            tick=d["tick"], actor=d["actor"], verb=d["verb"],
            target=d.get("target"), payload=d.get("payload", {}),
            roll=RollRecord.from_dict(roll) if roll else None,
            seq=d.get("seq", 0),
        )


class EventLog:
    """Append-only лог событий — источник истины (main §3.3).

    В прототипе держит события в памяти и (опционально) персистит в JSONL.
    Полная воспроизводимость партии по seed + RollRecord.
    """

    def __init__(self) -> None:
        self._events: list[Event] = []

    def append(self, ev: Event) -> Event:
        ev.seq = len(self._events)
        self._events.append(ev)
        return ev

    def all(self) -> list[Event]:
        return list(self._events)

    def after(self, seq: int) -> list[Event]:
        return self._events[seq + 1:]

    def since_tick(self, tick: int) -> list[Event]:
        return [e for e in self._events if e.tick > tick]

    def count(self) -> int:
        return len(self._events)

    def dumps(self) -> str:
        return "\n".join(json.dumps(e.to_dict(), ensure_ascii=False) for e in self._events)

    def load_lines(self, text: str) -> None:
        self._events = []
        for line in text.splitlines():
            line = line.strip()
            if line:
                self.append(Event.from_dict(json.loads(line)))
