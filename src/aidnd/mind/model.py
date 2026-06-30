"""Модель NPC для нового ядра решений (отдельно от старого aidnd/npc).

NpcConfig — редактируемые настройки (характер/характеристики/нужды/эмоции/память/связи).
NpcState — рантайм (config + позиция на графе + текущие нужды/эмоции/режим + память).
Scene — лёгкий мир дебага: граф города + часы (тик) + размещённые NPC + предметы.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .memory import MemoryStore

TRAITS = ("bravery", "greed", "honesty", "curiosity", "pride", "loyalty",
          "sociability", "ambition", "lawful", "irritability")
ABILITIES = ("str", "dex", "con", "int", "wis", "cha")
NEEDS = ("fatigue", "hunger", "social")
EMOTIONS = ("anger", "fear", "joy", "distress")


@dataclass
class NpcConfig:
    id: str = "npc:debug"
    name: str = "Безымянный"
    race: str = "human"
    role: str = "горожанин"
    level: int = 1
    max_hp: int = 10
    traits: dict = field(default_factory=lambda: dict.fromkeys(TRAITS, 0.5))
    abilities: dict = field(default_factory=lambda: dict.fromkeys(ABILITIES, 10))


@dataclass
class NpcState:
    config: NpcConfig
    node: int | None = None
    hp: int = 10
    mode: str = "idle"                                   # idle | conversing | flee | fight | trade
    needs: dict = field(default_factory=lambda: dict.fromkeys(NEEDS, 0.2))
    emotion: dict = field(default_factory=lambda: dict.fromkeys(EMOTIONS, 0.0))
    emotion_target: dict = field(default_factory=dict)   # канал → id источника (на кого/из-за кого)
    relationships: dict = field(default_factory=dict)    # id → {trust, affinity, fear}
    memory: MemoryStore = field(default_factory=MemoryStore)

    @classmethod
    def from_config(cls, cfg: NpcConfig, node: int | None = None) -> NpcState:
        return cls(config=cfg, node=node, hp=cfg.max_hp)

    # эмоц. параметры выводятся из черт (один механизм, черты параметризуют)
    def emotion_gain(self, channel: str) -> float:
        t = self.config.traits
        return {"anger": 0.6 + t.get("irritability", 0.5),
                "fear": 0.6 + (1 - t.get("bravery", 0.5)),
                "joy": 0.6 + t.get("sociability", 0.5),
                "distress": 0.6 + (1 - t.get("bravery", 0.5)) * 0.5}.get(channel, 1.0)

    def emotion_baseline(self, channel: str) -> float:
        t = self.config.traits
        return {"fear": (1 - t.get("bravery", 0.5)) * 0.1}.get(channel, 0.0)

    def rel(self, entity: str) -> dict:
        return self.relationships.setdefault(entity, {"trust": 0.0, "affinity": 0.0, "fear": 0.0})

    def view(self) -> dict:
        return {"id": self.config.id, "name": self.config.name, "role": self.config.role,
                "node": self.node, "hp": self.hp, "mode": self.mode,
                "needs": {k: round(v, 2) for k, v in self.needs.items()},
                "emotion": {k: round(v, 2) for k, v in self.emotion.items()},
                "emotion_target": dict(self.emotion_target),
                "relationships": self.relationships, "memory_count": len(self.memory.items)}


@dataclass
class Scene:
    city: object                                         # aidnd.citygraph.City
    clock: int = 0
    npcs: dict = field(default_factory=dict)             # id → NpcState (все размещённые)
    items: dict = field(default_factory=dict)            # node → [имена предметов]
