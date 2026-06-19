"""Система бросков (док 07).

Движок запрашивает броски вместо тихого подсчёта. Игрок владеет случайным
извлечением, движок владеет математическим контекстом (модификатор, DC, adv/dis).
Авто-броски (монстры, скрытое) сидируются и логируются. Replay подставляет грани
из RollRecord, а не пересевает (док 07 §7).
"""

from __future__ import annotations

import random
import re
from dataclasses import asdict, dataclass, field

from ..world.events import RollRecord

_EXPR = re.compile(r"^\s*(\d*)d(\d+)\s*([+-]\s*\d+)?\s*$", re.IGNORECASE)
_CONST = re.compile(r"^\s*([+-]?\d+)\s*$")


def parse_expr(expr: str) -> tuple[int, int, int]:
    """'2d6+3' -> (n=2, faces=6, mod=3). '5' -> (0, 0, 5)."""
    m = _EXPR.match(expr)
    if m:
        n = int(m.group(1)) if m.group(1) else 1
        faces = int(m.group(2))
        mod = int(m.group(3).replace(" ", "")) if m.group(3) else 0
        return n, faces, mod
    c = _CONST.match(expr)
    if c:
        return 0, 0, int(c.group(1))
    raise ValueError(f"не удалось разобрать выражение кубов: {expr!r}")


def double_dice(expr: str) -> str:
    """Крит удваивает кости, не модификатор (док 07 §5)."""
    n, faces, mod = parse_expr(expr)
    sign = "" if mod == 0 else (f"+{mod}" if mod > 0 else str(mod))
    return f"{n * 2}d{faces}{sign}"


@dataclass
class RollRequest:
    """Запрос броска у игрока/движка (док 07 §2)."""

    request_id: str
    roller: str                 # pc:id | npc:id | dm
    kind: str                   # attack|damage|save|ability_check|skill|initiative|
                                # death_save|discovery|hit_dice
    dice: str                   # "1d20", "2d6"
    modifier: int = 0
    advantage: int = 0          # -1 dis, 0 none, +1 adv
    dc: int | None = None
    visibility: str = "open"    # open | hidden
    context: dict = field(default_factory=dict)
    auto: bool = False          # True — движок кидает, иначе ждём игрока

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RollResult:
    """Результат броска (док 07 §2)."""

    request_id: str
    raw: list[int]
    total: int
    nat: int = 0
    source: str = "server_seeded"
    seed: int | None = None

    def to_record(self, dice: str) -> RollRecord:
        return RollRecord(
            request_id=self.request_id, dice=dice, raw=self.raw,
            total=self.total, nat=self.nat, source=self.source, seed=self.seed,
        )


def _roll_die(faces: int, rng: random.Random) -> int:
    return rng.randint(1, faces)


def roll_expr(
    request_id: str, expr: str, seed: int,
    modifier: int = 0, advantage: int = 0, source: str = "server_seeded",
) -> RollResult:
    """Сидированный бросок выражения с adv/dis для d20 (док 07 §9)."""
    rng = random.Random(seed)
    n, faces, inline_mod = parse_expr(expr)
    mod = modifier + inline_mod

    if n == 1 and faces == 20 and advantage != 0:
        a, b = _roll_die(20, rng), _roll_die(20, rng)
        nat = max(a, b) if advantage > 0 else min(a, b)
        return RollResult(request_id, [a, b], nat + mod, nat, source, seed)

    rolls = [_roll_die(faces, rng) for _ in range(n)] if n else []
    nat = rolls[0] if (n == 1 and faces == 20) else 0
    total = sum(rolls) + mod
    return RollResult(request_id, rolls, total, nat, source, seed)


def validate_player_roll(
    request: RollRequest, raw: list[int], source: str = "player_ui",
) -> RollResult:
    """Пересчитывает total с СЕРВЕРНЫМ модификатором, чтобы игрок не подменил его
    (док 07 §9). Принимает выпавшие грани от игрока."""
    n, faces, inline_mod = parse_expr(request.dice)
    mod = request.modifier + inline_mod
    if n == 1 and faces == 20 and request.advantage != 0 and len(raw) >= 2:
        nat = max(raw[:2]) if request.advantage > 0 else min(raw[:2])
        return RollResult(request.request_id, raw[:2], nat + mod, nat, source)
    nat = raw[0] if (n == 1 and faces == 20 and raw) else 0
    return RollResult(request.request_id, raw, sum(raw) + mod, nat, source)


class DiceService:
    """Маршрутизирует броски в игрока (suspend) либо в авто-сид (док 07 §3-4)."""

    def __init__(self, world) -> None:
        self.world = world
        self._counter = 0

    def next_seed(self) -> int:
        """Детерминированный сид авто-броска от мирового сида + счётчик."""
        self._counter += 1
        return (self.world.seed * 1_000_003 + self._counter) & 0x7FFFFFFF

    def new_request_id(self) -> str:
        self._counter += 1
        return f"roll-{self.world.clock.tick}-{self._counter}"

    def roll_seeded(
        self, kind: str, dice: str, modifier: int = 0, advantage: int = 0,
        dc: int | None = None, roller: str = "dm",
    ) -> RollResult:
        seed = self.next_seed()
        rid = self.new_request_id()
        return roll_expr(rid, dice, seed, modifier, advantage, "server_seeded")

    def request_player(
        self, kind: str, dice: str, modifier: int = 0, advantage: int = 0,
        dc: int | None = None, visibility: str = "open",
        roller: str = "pc", context: dict | None = None,
    ) -> RollRequest:
        return RollRequest(
            request_id=self.new_request_id(), roller=roller, kind=kind, dice=dice,
            modifier=modifier, advantage=advantage, dc=dc, visibility=visibility,
            context=context or {}, auto=False,
        )
