"""Ядро разума NPC (новое, отдельно от старого aidnd/npc): состояние, память+SOTA-ретрива,
инструменты (READ/WRITE), ход мира. Граф города и LLM — внешние зависимости (citygraph, inference).
"""

from __future__ import annotations

from .fsm import dominant_need, hold, urgency
from .fsm import step as fsm_step
from .memory import LLMReranker, Memory, MemoryStore, Reranker, StubReranker
from .model import ABILITIES, EMOTIONS, NEEDS, TRAITS, NpcConfig, NpcState, Plan, Scene
from .tick import advance, appraise
from .tools import TOOLS, run_tool

MODES = ("routine", "leisure", "converse", "threat")

__all__ = ["NpcConfig", "NpcState", "Plan", "Scene", "MemoryStore", "Memory", "Reranker",
           "StubReranker", "LLMReranker", "TOOLS", "run_tool", "advance", "appraise",
           "fsm_step", "urgency", "hold", "dominant_need", "MODES",
           "TRAITS", "ABILITIES", "NEEDS", "EMOTIONS"]
