"""NPC model for the new decision core (separate from old aidnd/npc).

NpcConfig — editable settings (traits/characteristics/needs/emotions/memory/relationships).
NpcState — runtime state (config + position on graph + current needs/emotions/mode + memory).
Scene — lightweight debug world: city graph + clock (tick) + placed NPCs + items.

Key functions
--------------
NpcConfig : editable NPC config (traits, abilities, relationships).
Plan : routine plan with steps and execution cursor tracking.
NpcState : runtime NPC state (emotions, needs, relationships, memory).
Scene : lightweight debug world (city graph, NPCs, items, clock).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .memory import MemoryStore

TRAITS = ("bravery", "greed", "honesty", "curiosity", "pride", "loyalty",
          "sociability", "ambition", "lawful", "irritability", "malice",
          "empathy", "vengefulness")
ABILITIES = ("str", "dex", "con", "int", "wis", "cha")
NEEDS = ("fatigue", "hunger", "social", "purpose", "wealth", "comfort", "novelty")
EMOTIONS = ("anger", "fear", "joy", "distress", "disgust")


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
    # enriched entity slices (docs/.../npc-entity-enrichment-design.md §3) — code-readable;
    # empty defaults so un-enriched/legacy rows degrade to neutral (never crash, §4.3).
    worldview: dict = field(default_factory=dict)        # faith/morals{6}/taboos/mood_baseline
    skills: dict = field(default_factory=dict)           # combat/craft{}/magic/literacy
    allegiances: list = field(default_factory=list)      # [{group,kind,role,standing}]
    standing: dict = field(default_factory=dict)         # {rank,notoriety}
    perception: dict = field(default_factory=dict)       # {vigilance}


@dataclass
class Plan:
    """Routine plan: ordered steps toward a goal + importance (resistance to interruption)."""
    goal: str
    steps: list = field(default_factory=list)            # step descriptions / tool calls
    importance: float = 0.4
    cursor: int = 0

    def done(self) -> bool:
        return self.cursor >= len(self.steps)

    def current(self):
        return self.steps[self.cursor] if not self.done() else None

    def view(self) -> dict:
        return {"goal": self.goal, "steps": self.steps, "cursor": self.cursor,
                "importance": round(self.importance, 2), "done": self.done()}


@dataclass
class NpcState:
    config: NpcConfig
    node: int | None = None
    hp: int = 10
    mode: str = "leisure"                                # routine | leisure | converse | threat
    needs: dict = field(default_factory=lambda: dict.fromkeys(NEEDS, 0.2))
    emotion: dict = field(default_factory=lambda: dict.fromkeys(EMOTIONS, 0.0))
    emotion_target: dict = field(default_factory=dict)   # channel → source id (target/reason)
    relationships: dict = field(default_factory=dict)    # id → {trust, affinity, fear}
    memory: MemoryStore = field(default_factory=MemoryStore)
    plan: Plan | None = None                           # active plan (routine mode)
    engagement: float = 0.0                              # dialogue engagement (hold for converse)
    venue_social: float = 0.0                            # leisure-venue converse lift for acquaintances (set by live scene)
    on_shift: float = 0.0                                # workplace 'keep working' purpose lift (set by live scene)
    mode_history: list = field(default_factory=list)     # [(tick, mode, switched, reason)] — history
    agendas: list = field(default_factory=list)          # long-term goals (LLM scheduler, mind/agenda)
    last_decay_gt: int = 0                               # gt-min of the last decay_lazy (Inc1 clock)
    familiarity: dict = field(default_factory=dict)      # id → co-presence tick count (Inc3; seeds a faint tie at familiarity_k)

    @classmethod
    def from_config(cls, cfg: NpcConfig, node: int | None = None) -> NpcState:
        return cls(config=cfg, node=node, hp=cfg.max_hp)

    # emotion parameters derived from traits (one mechanism, traits parameterize)
    def emotion_gain(self, channel: str) -> float:
        t = self.config.traits
        return {"anger": 0.6 + t.get("irritability", 0.5),
                "fear": 0.6 + (1 - t.get("bravery", 0.5)),
                "joy": 0.6 + t.get("sociability", 0.5),
                "distress": 0.6 + (1 - t.get("bravery", 0.5)) * 0.5,
                "disgust": 0.6 + t.get("pride", 0.5)}.get(channel, 1.0)

    def emotion_baseline(self, channel: str) -> float:
        t = self.config.traits
        # mood_baseline (§3.2/§3.10) = the two-speed decay TARGET: a cheerful soul rests
        # warm (joy floor), a melancholic rests low (distress floor). 0 for un-enriched rows.
        mood = self.config.worldview.get("mood_baseline", 0.0)
        return {"fear": (1 - t.get("bravery", 0.5)) * 0.1,
                "joy": max(0.0, mood) * 0.15,
                "distress": max(0.0, -mood) * 0.15}.get(channel, 0.0)

    def rel(self, entity: str) -> dict:
        return self.relationships.setdefault(
            entity, {"trust": 0.0, "affinity": 0.0, "fear": 0.0, "anchored": False})

    def view(self) -> dict:
        return {"id": self.config.id, "name": self.config.name, "role": self.config.role,
                "node": self.node, "hp": self.hp, "mode": self.mode,
                "needs": {k: round(v, 2) for k, v in self.needs.items()},
                "emotion": {k: round(v, 2) for k, v in self.emotion.items()},
                "emotion_target": dict(self.emotion_target),
                "relationships": self.relationships, "memory_count": len(self.memory.items),
                "plan": self.plan.view() if self.plan else None,
                "engagement": round(self.engagement, 2),
                "mode_history": self.mode_history[-24:]}


@dataclass
class Scene:
    city: object                                         # aidnd.citygraph.City
    clock: int = 0
    npcs: dict = field(default_factory=dict)             # id → NpcState (all placed)
    items: dict = field(default_factory=dict)            # node → [item names]
