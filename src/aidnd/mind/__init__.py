"""Ядро разума NPC (новое, отдельно от старого aidnd/npc): состояние, память+SOTA-ретрива,
инструменты (READ/WRITE), ход мира. Граф города и LLM — внешние зависимости (citygraph, inference).
"""

from __future__ import annotations

from .act import Action, decide, enumerate_actions, score
from .agenda import (
    Agenda,
    Milestone,
    StubPlanner,
    advance_agendas,
    courtship_agenda,
    predation_agenda,
    revenge_agenda,
    wealth_agenda,
)
from .fsm import dominant_need, hold, urgency
from .fsm import step as fsm_step
from .goals import Goal, propose_goals, standing_needs
from .memory import LLMReranker, Memory, MemoryStore, Reranker, StubReranker
from .model import ABILITIES, EMOTIONS, NEEDS, TRAITS, NpcConfig, NpcState, Plan, Scene
from .sim import Percept, apply, perceive, tick
from .tick import advance, appraise
from .tools import TOOLS, run_tool
from .value import BAL, utility
from .world import Body, Item, World

MODES = ("routine", "leisure", "converse", "threat")

__all__ = ["NpcConfig", "NpcState", "Plan", "Scene", "MemoryStore", "Memory", "Reranker",
           "StubReranker", "LLMReranker", "TOOLS", "run_tool", "advance", "appraise",
           "fsm_step", "urgency", "hold", "dominant_need", "MODES",
           "TRAITS", "ABILITIES", "NEEDS", "EMOTIONS",
           # эмерджентное ядро решений
           "World", "Body", "Item", "Goal", "propose_goals", "standing_needs",
           "Action", "enumerate_actions", "score", "decide", "utility", "BAL",
           "Percept", "perceive", "apply", "tick",
           # долгосрочные цели (агенды)
           "Agenda", "Milestone", "advance_agendas", "StubPlanner",
           "wealth_agenda", "courtship_agenda", "revenge_agenda", "predation_agenda"]
