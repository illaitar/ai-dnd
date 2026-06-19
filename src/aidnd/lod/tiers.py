"""LOD-симуляция: тиры, salience, AOI (main §4, док 08 §7).

Тир выбирается по salience (interest management). Дорогой когнитивный контур L3
включается только когда игрок взаимодействует нестандартно. Демоушн с
гистерезисом. Жёсткий cap на число L3-NPC за тик.
"""

from __future__ import annotations

from .. import config
from ..world.components import LODState, Persona


def proximity(world, npc_id: str, player_id: str) -> float:
    """Близость по графу связности локаций (без координат): та же локация = 1.0,
    дальше — спад по числу переходов."""
    a, b = world.position(npc_id), world.position(player_id)
    if not a or not b or not a.place_id or not b.place_id:
        return 0.0
    if a.place_id == b.place_id:
        return 1.0
    hops = world.spatial.hops_between(a.place_id, b.place_id, limit=config.AOI_HOPS + 1)
    if hops is None:
        return 0.0
    return max(0.0, 1.0 - hops / (config.AOI_HOPS + 1))


def narrative_role(world, npc_id: str) -> float:
    for q in world.quests.values():
        if npc_id == getattr(q, "giver_ref", None) or npc_id in getattr(q, "world_bindings", []):
            if getattr(q, "state", "") in ("offered", "active"):
                return 1.0
            return 0.5
    persona = world.ecs.get(npc_id, Persona)
    if persona and persona.epithet:        # именной/заметный
        return 0.6
    return 0.0


def recency(world, npc_id: str) -> float:
    lod = world.ecs.get(npc_id, LODState)
    if not lod or lod.last_active_tick == 0:
        return 0.0
    dt = world.clock.tick - lod.last_active_tick
    return max(0.0, 1.0 - dt / 100.0)


def salience(world, npc_id: str, player_id: str, in_active_scene: bool = False) -> float:
    return (config.W_DIST * proximity(world, npc_id, player_id)
            + config.W_ROLE * narrative_role(world, npc_id)
            + config.W_RECENT * recency(world, npc_id)
            + config.W_ACTIVE * (1.0 if in_active_scene else 0.0))


class LODManager:
    def __init__(self, world) -> None:
        self.world = world
        self._l3_count = 0

    def ensure_tier(self, npc_id: str, in_dialogue: bool = False) -> int:
        """Промоушн NPC в нужный тир (main §4.2). Возвращает итоговый тир."""
        lod = self.world.ecs.get(npc_id, LODState)
        if not lod:
            lod = LODState()
            self.world.ecs.add(npc_id, lod)
        s = salience(self.world, npc_id, self.world.player_id or "pc:hero", in_dialogue)
        lod.salience = s
        target = lod.tier
        if in_dialogue and s > config.TAU_HIGH and self._l3_count < config.MAX_L3_NPCS:
            target = 3
        elif s > config.TAU_HIGH:
            target = max(2, lod.tier)
        elif s > config.TAU_MID:
            target = 2
        elif proximity(self.world, npc_id, self.world.player_id or "pc:hero") > 0:
            target = 1
        else:
            target = 0
        self._set_tier(npc_id, lod, target)
        return target

    def _set_tier(self, npc_id, lod, target) -> None:
        if target == lod.tier:
            if target >= 2:
                lod.last_active_tick = self.world.clock.tick
            return
        if target < lod.tier and lod.tier == 3:
            # гистерезис демоушна с L3
            if self.world.clock.tick - lod.last_active_tick < config.DEMOTE_COOLDOWN_TICKS:
                return
            self._l3_count = max(0, self._l3_count - 1)
        if target == 3 and lod.tier < 3:
            self._l3_count += 1
        self.world.commit("set_lod", "lod", target=npc_id, payload={"tier": target})

    def tick(self, player_id: str) -> dict:
        """Пересчёт salience только в окрестности игрока (AOI, док 08 §7)."""
        pos = self.world.position(player_id)
        counts = {0: 0, 1: 0, 2: 0, 3: 0}
        if not pos or not pos.place_id:
            nearby = set(self.world.npcs())
        else:
            nearby = self.world.spatial.neighbors(pos.place_id, config.AOI_HOPS)
        for eid in self.world.npcs():
            lod = self.world.ecs.get(eid, LODState)
            if not lod:
                continue
            if eid in nearby:
                self.ensure_tier(eid, in_dialogue=False)
            elif lod.tier > 0 and self.world.clock.tick - lod.last_active_tick > config.DEMOTE_COOLDOWN_TICKS:
                self._set_tier(eid, lod, 0)
            counts[lod.tier] = counts.get(lod.tier, 0) + 1
        return counts
