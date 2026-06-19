"""Smart objects, расписания и off-screen fast-forward (main §4.3-4.4, док 08 §8).

Рутина L1 строится на smart objects: объект рекламирует аффордансы (наковальня —
work, кровать — sleep). NPC выбирает аффорданс по расписанию. Вне сцены L0-NPC не
тикаются по шагам — при возвращении их состояние вычисляется из расписания
аналитически.
"""

from __future__ import annotations

from ..world.components import Schedule, ScheduleBlock


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def block_at(schedule: Schedule, hhmm: str) -> ScheduleBlock | None:
    """Активный блок расписания на момент времени (аналитически)."""
    if not schedule or not schedule.routine:
        return None
    now = _minutes(hhmm)
    chosen = None
    for blk in sorted(schedule.routine, key=lambda b: _minutes(b.t)):
        if _minutes(blk.t) <= now:
            chosen = blk
    return chosen or sorted(schedule.routine, key=lambda b: _minutes(b.t))[-1]


def fast_forward(world, player_id: str) -> int:
    """Аналитический fast-forward дормант-NPC по расписанию (док 08 §8)."""
    hhmm = world.clock.hhmm()
    moved = 0
    for npc in world.npcs():
        from ..world.components import LODState
        lod = world.ecs.get(npc, LODState)
        if lod and lod.tier > 0:
            continue                        # активные тикаются обычным циклом
        sched = world.ecs.get(npc, Schedule)
        blk = block_at(sched, hhmm)
        if blk:
            pos = world.position(npc)
            if not pos or pos.place_id != blk.place:
                world.commit("set_position", "lod", target=npc,
                             payload={"region": "region:phandalin", "place": blk.place})
                moved += 1
    return moved
