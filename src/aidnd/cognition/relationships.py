"""Модель отношений и аппрейзал (main §5.4).

Per-NPC рёбра аффекта к сущностям. Событие маппится в дельты аффекта правилами
в духе OCC, без LLM. Отношения — гейты в пайплайне действия: низкий trust
блокирует выдачу секретов, высокий fear открывает «сбежать»/«сдаться».
"""

from __future__ import annotations

from ..world.components import Relationships, RelEdge

# событие(verb, tone) -> дельты аффекта (main §5.4)
APPRAISAL_RULES = {
    ("help", None): {"affinity": 0.2, "trust": 0.15, "respect": 0.1, "tags": ["helped_me"]},
    ("give", None): {"affinity": 0.15, "trust": 0.1, "tags": ["gave_gift"]},
    ("attack", None): {"affinity": -0.4, "trust": -0.3, "fear": 0.3, "respect": 0.1,
                       "tags": ["attacked_me"]},
    ("threaten", None): {"fear": 0.3, "affinity": -0.2, "trust": -0.15},
    ("intimidate", None): {"fear": 0.25, "affinity": -0.15},
    ("steal", None): {"trust": -0.4, "affinity": -0.3, "tags": ["stole_from_me"]},
    ("persuade", None): {"affinity": 0.1, "trust": 0.05},
    ("trade", None): {"affinity": 0.05, "trust": 0.05},
    ("talk", "friendly"): {"affinity": 0.08, "trust": 0.03},
    ("talk", "hostile"): {"affinity": -0.1, "trust": -0.05},
    ("talk", "deceptive"): {"trust": -0.05},
}


def appraise(world, npc_id: str, actor_id: str, verb: str, tone: str | None = None,
             success: bool | None = None) -> dict:
    """Применяет дельты аффекта к ребру npc→actor через event log."""
    deltas = APPRAISAL_RULES.get((verb, tone)) or APPRAISAL_RULES.get((verb, None))
    if not deltas:
        return {}
    payload = {"npc": npc_id, "target": actor_id}
    for k, v in deltas.items():
        if k == "tags":
            payload["tags"] = list(v)
        else:
            # провал смягчает позитив, усиливает страх
            payload[k] = v
    world.commit("rel_update", actor_id, payload=payload)
    return deltas


def edge(world, npc_id: str, target_id: str) -> RelEdge:
    rels = world.ecs.get(npc_id, Relationships)
    if not rels:
        return RelEdge()
    return rels.edges.get(target_id, RelEdge())


def gate_open(world, npc_id: str, actor_id: str, kind: str) -> bool:
    """Гейты раскрытия (main §5.4). kind: share_secret | share_info | flee | yield."""
    e = edge(world, npc_id, actor_id)
    if kind == "share_secret":
        return e.trust >= 0.6
    if kind == "share_info":
        return e.trust >= 0.2
    if kind in ("flee", "yield"):
        return e.fear >= 0.6
    return True
