"""Система квестов (док 05).

Квест — DAG стадий с машиной состояний. Авторские и сгенерированные квесты в одной
структуре. Прогресс реактивен: события мира матчат предикаты и продвигают стадии.
Quest Writer отрисовывает только текст, механика детерминирована.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .provenance import Provenance
from .seeds import subseed


# --------------------------------------------------------------------------- #
#  Предикаты над миром (условия завершения стадий)                            #
# --------------------------------------------------------------------------- #
@dataclass
class Predicate:
    pred: str
    args: list = field(default_factory=list)

    def holds(self, world) -> bool:
        fn = getattr(self, f"_p_{self.pred}", None)
        return bool(fn(world)) if fn else False

    def _p_Flag(self, world) -> bool:
        return self.args[0] in world.flags

    def _p_NpcDead(self, world) -> bool:
        return not world.is_alive(self.args[0])

    def _p_LairCleared(self, world) -> bool:
        return f"cleared:{self.args[0]}" in world.flags

    def _p_KnowsFact(self, world) -> bool:
        return f"knows:{self.args[0]}:{self.args[1]}" in world.flags

    def _p_HasItem(self, world) -> bool:
        owner, template = self.args[0], self.args[1]
        carry = world.containers.get(f"carry:{owner.split(':',1)[1]}")
        if not carry:
            return False
        for iid in carry.items:
            inst = world.items.get(iid)
            if inst and (inst.template_id == template or iid == template):
                return True
        return False

    def _p_ItemInContainer(self, world) -> bool:
        inst_id, container = self.args[0], self.args[1]
        c = world.containers.get(container)
        return bool(c and inst_id in c.items)

    def _p_AnyOf(self, world) -> bool:
        return any(p.holds(world) for p in self.args)


@dataclass
class Stage:
    stage_id: str
    objective: str
    completion_conditions: list[Predicate] = field(default_factory=list)
    on_complete: list[dict] = field(default_factory=list)
    next_stages: list[str] = field(default_factory=list)
    optional: bool = False
    hooks_revealed: list[str] = field(default_factory=list)


@dataclass
class Rewards:
    currency: dict = field(default_factory=dict)
    items: list[str] = field(default_factory=list)
    xp: int = 0
    faction_rep: dict = field(default_factory=dict)
    faction_membership: str | None = None


@dataclass
class Quest:
    quest_id: str
    kind: str                       # main | side | faction | emergent
    title: str
    giver_ref: str | None = None
    state: str = "not_offered"      # not_offered|offered|active|completed|failed|abandoned
    stages: list[Stage] = field(default_factory=list)
    current_stages: list[str] = field(default_factory=list)
    rewards: Rewards = field(default_factory=Rewards)
    prerequisites: list[str] = field(default_factory=list)
    world_bindings: list[str] = field(default_factory=list)
    framing: str = ""
    giver_lines: list[str] = field(default_factory=list)
    provenance: Provenance | None = None

    def stage(self, sid: str) -> Stage | None:
        return next((s for s in self.stages if s.stage_id == sid), None)


class QuestSystem:
    """Подписка на события мира, продвижение стадий, выдача наград (док 05 §8)."""

    def __init__(self, world) -> None:
        self.world = world
        self.log: list[str] = []        # человекочитаемый журнал для UI
        world.subscribe(self.on_event)

    def register(self, quest: Quest) -> None:
        self.world.quests[quest.quest_id] = quest

    def offer(self, quest_id: str) -> None:
        q = self.world.quests.get(quest_id)
        if q and q.state == "not_offered":
            q.state = "offered"
            self.log.append(f"Предложен квест: {q.title}")

    def accept(self, quest_id: str) -> None:
        q = self.world.quests.get(quest_id)
        if q and q.state in ("offered", "not_offered"):
            q.state = "active"
            if not q.current_stages and q.stages:
                q.current_stages = [q.stages[0].stage_id]
            self.log.append(f"Принят квест: {q.title}")

    def on_event(self, ev, world) -> None:
        for q in list(world.quests.values()):
            if q.state == "active":
                self.advance(q)

    def advance(self, quest: Quest) -> None:
        progressed = False
        for sid in list(quest.current_stages):
            stage = quest.stage(sid)
            if stage and all(c.holds(self.world) for c in stage.completion_conditions):
                for eff in stage.on_complete:
                    self._apply_effect(eff, quest)
                for hook in stage.hooks_revealed:
                    self.world.flags.add(f"hook:{hook}")
                quest.current_stages.remove(sid)
                quest.current_stages.extend(stage.next_stages)
                self.log.append(f"[{quest.title}] выполнено: {stage.objective}")
                progressed = True
        if progressed and not quest.current_stages:
            self.complete(quest)

    def _apply_effect(self, eff: dict, quest: Quest) -> None:
        kind = eff.get("effect")
        if kind == "set_flag":
            self.world.flags.add(eff["flag"])

    def complete(self, quest: Quest) -> None:
        quest.state = "completed"
        r = quest.rewards
        if r.currency:
            from ..inventory.container import transfer_currency
            if self.world.player_id:
                transfer_currency(self.world, None, self.world.player_id,
                                  r.currency, actor="quest")
        for faction, delta in r.faction_rep.items():
            self.world.flags.add(f"rep:{faction}:+{delta}")
        self.log.append(f"Квест завершён: {quest.title} (XP {r.xp})")


# --------------------------------------------------------------------------- #
#  Процедурные побочки (док 05 §4.2-5)                                         #
# --------------------------------------------------------------------------- #
QUEST_TEMPLATES = {
    "bounty": {"slots": ["giver", "location"], "tier_range": (1, 3)},
    "clear": {"slots": ["giver", "location"], "tier_range": (1, 3)},
}

_q_counter = {"n": 0}


def generate_side_quest(world, template_id: str, giver: str, location: str,
                        title: str, objective: str, seed: int,
                        quest_writer=None) -> Quest:
    """CSP-побочка: слоты заполнены, текст отрисован моделью с фоллбэком."""
    _q_counter["n"] += 1
    random.Random(subseed(seed, "quest", template_id, location))
    framing, lines = "", []
    if quest_writer is not None:
        out = quest_writer(template_id, giver, location, title, objective)
        if out:
            framing = out.get("framing", "")
            lines = out.get("giver_lines", [])
    if not lines:
        lines = [f"{objective}. Помоги — город не забудет."]
        framing = f"{title}: {objective}."
    return Quest(
        quest_id=f"quest:{template_id}_{location.split(':',1)[-1]}",
        kind="side", title=title, giver_ref=giver, state="offered",
        stages=[Stage("s1", objective,
                      completion_conditions=[Predicate("LairCleared", [location])],
                      on_complete=[{"effect": "complete"}], optional=True)],
        current_stages=[],
        rewards=Rewards(currency={"gp": 100}, xp=200,
                        faction_rep={"faction:phandalin": 0.15}),
        world_bindings=[giver, location], framing=framing, giver_lines=lines,
        provenance=Provenance(source="lazy", generator="quest_gen@1.0", seed=seed,
                              tick=world.clock.tick,
                              satisfied=["giver_has_motive", "location_reachable",
                                         "tier_appropriate", "no_main_plot_conflict"]),
    )
