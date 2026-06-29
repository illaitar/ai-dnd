"""Кто кого ЗНАЕТ (гибрид: община + встречи) — для правдивого «знаком ли ты с X», мнений и сплетен.

Община: в маленьком фронтирном городке жители-ростер знают друг друга в лицо (одна семья по фамилии /
одна фракция / просто соседи-горожане). Чужаки, приезжие и ИГРОК — только после реальной встречи
(`record_meeting`, копится в `world.met[a] = {b,...}`). `acquainted(world,a,b)` = община ИЛИ встречались.

Это слой ЗНАКОМСТВА (знаю ли я этого агента вообще), поверх него — отношение (граф мнений / Relationships).
Нельзя иметь мнение о том, кого не знаешь: мнения/сплетни гейтятся знакомством.
"""

from __future__ import annotations

from ..world.components import Persona


def _persona(world, n):
    return world.ecs.get(n, Persona)


def _surname(world, n: str) -> str:
    p = _persona(world, n)
    parts = ((p.name if p else "") or "").split()
    return parts[-1] if len(parts) >= 2 else ""


def _is_townsfolk(world, n: str) -> bool:
    """Именованный житель-ростер городка (npc:*). Не игрок и не безликий фон."""
    p = _persona(world, n)
    return bool(p and p.name) and str(n).startswith("npc:")


def _met_map(world) -> dict:
    if not hasattr(world, "met") or world.met is None:
        world.met = {}
    return world.met


def record_meeting(world, a: str, b: str) -> None:
    """a и b теперь знакомы лично (встретились/поговорили) — взаимно."""
    if not a or not b or a == b:
        return
    m = _met_map(world)
    m.setdefault(a, set()).add(b)
    m.setdefault(b, set()).add(a)


def has_met(world, a: str, b: str) -> bool:
    return b in _met_map(world).get(a, set())


def community_acquainted(world, a: str, b: str) -> bool:
    """Заранее знакомы по общине: семья (фамилия) / общая фракция / оба — жители городка."""
    sa = _surname(world, a)
    if sa and sa == _surname(world, b):
        return True
    pa, pb = _persona(world, a), _persona(world, b)
    if pa and pb and pa.faction and pa.faction == pb.faction:
        return True
    return _is_townsfolk(world, a) and _is_townsfolk(world, b)


def acquainted(world, a: str, b: str) -> bool:
    """Знает ли a агента b вообще: община ИЛИ личная встреча."""
    if a == b:
        return True
    return community_acquainted(world, a, b) or has_met(world, a, b)


def known_others(world, a: str, candidates) -> list[str]:
    """Из кандидатов — те, кого a реально знает (для сплетен/мнений только о знакомых)."""
    return [b for b in candidates if b != a and acquainted(world, a, b)]
