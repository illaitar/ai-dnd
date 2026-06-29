"""Кто кого ЗНАЕТ (гибрид: община + встречи) — для правдивого «знаком ли ты с X», мнений и сплетен.

Община: в маленьком фронтирном городке жители-ростер знают друг друга в лицо (одна семья по фамилии /
одна фракция / просто соседи-горожане). Чужаки, приезжие и ИГРОК — только после реальной встречи
(`record_meeting`, копится в `world.met[a] = {b,...}`). `acquainted(world,a,b)` = община ИЛИ встречались.

Это слой ЗНАКОМСТВА (знаю ли я этого агента вообще), поверх него — отношение (граф мнений / Relationships).
Нельзя иметь мнение о том, кого не знаешь: мнения/сплетни гейтятся знакомством.
"""

from __future__ import annotations

import math

from ..world.components import Persona

# Распад знакомства (тики; SIM_MINUTES_PER_TICK=10 → 144 тика/сутки):
_FADE_TICKS = 432        # одиночная мимолётная встреча тускнеет за ~3 суток без контакта
_STICK_COUNT = 3         # после стольких ОТДЕЛЬНЫХ встреч — знаком прочно (больше не тускнеет)
_SESSION_GAP = 18        # встречи дальше ~3 ч друг от друга считаются разными сессиями


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


def _rec(world, a: str, b: str):
    """Запись встречи a→b: {"last": тик, "count": число отдельных сессий} или None."""
    r = _met_map(world).get(a, {}).get(b)
    return r if isinstance(r, dict) else None


def record_meeting(world, a: str, b: str, now: int = 0) -> None:
    """a и b встретились лично (взаимно). Хранится время последней встречи и счётчик ОТДЕЛЬНЫХ
    сессий: внутри одного разговора (ходы близко по времени) счётчик не растёт — растёт лишь на
    новых встречах (дальше _SESSION_GAP). Так знакомство КРЕПНЕТ с повторными визитами."""
    if not a or not b or a == b:
        return
    m = _met_map(world)
    for x, y in ((a, b), (b, a)):
        d = m.setdefault(x, {})
        r = d.get(y)
        if not isinstance(r, dict):                        # первая встреча (или миграция старого set)
            d[y] = {"last": now, "count": 1}
        else:
            if now - r.get("last", now) >= _SESSION_GAP:   # новая сессия, не продолжение разговора
                r["count"] = r.get("count", 1) + 1
            r["last"] = now


def familiarity(world, a: str, b: str, now: int) -> float:
    """Сила знакомства a с b [0..1]: крепнет с числом встреч, тает в отсутствие контакта.
    Прочное знакомство (count ≥ _STICK_COUNT) держится и не падает ниже 0.5."""
    if community_acquainted(world, a, b):
        return 1.0
    r = _rec(world, a, b)
    if not r:
        return 0.0
    base = min(1.0, r.get("count", 1) / _STICK_COUNT)
    decay = math.exp(-max(0, now - r.get("last", now)) / _FADE_TICKS)
    fam = base * decay
    return max(0.5, fam) if r.get("count", 1) >= _STICK_COUNT else fam


def has_met(world, a: str, b: str, now: int | None = None) -> bool:
    """Знают ли друг друга по личной встрече. now=None → «когда-либо» (без распада, для мнений/сплетен).
    now задан → с распадом: мимолётная встреча тускнеет за _FADE_TICKS, прочное знакомство держится."""
    r = _rec(world, a, b)
    if not r:
        old = _met_map(world).get(a)                       # совместимость со старым set-форматом
        return isinstance(old, set) and b in old
    if now is None:
        return True
    if r.get("count", 1) >= _STICK_COUNT:                  # знаком прочно — не забывается
        return True
    return (now - r.get("last", now)) <= _FADE_TICKS       # одиночная встреча ещё свежа?


def feels_stranger(world, a: str, b: str, now: int) -> bool:
    """Ощущается ли b для a ЧУЖАКОМ прямо сейчас (для тона приветствия/фазы знакомства):
    общинно-знакомый — никогда; высокое доверие подразумевает прежнее знакомство (даже без записи
    встречи — давний завсегдатай); иначе — если личная встреча уже выветрилась."""
    if community_acquainted(world, a, b):
        return False
    if has_met(world, a, b, now=now):
        return False
    try:                                                   # высокий trust ⇒ они не впервые видятся
        from ..world.components import Relationships
        rels = world.ecs.get(a, Relationships)
        e = rels.edges.get(b) if rels else None
        if e and getattr(e, "trust", 0.0) >= 0.4:
            return False
    except Exception:
        pass
    return True


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
