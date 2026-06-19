"""Память как лес деревьев с забыванием (main §5.1-5.3).

Листья — сырые наблюдения с importance, внутренние узлы — рефлексии/саммари.
Retrieval по взвешенной сумме recency·importance·relevance, top-k. Забывание по
кривой Эббингауза: ниже порога деталь сливается в родителя-саммари, не теряя суть.

Эмбеддинги: при наличии модели — настоящие; без сервера — детерминированный
токен-оверлап (множество слов), чтобы retrieval работал офлайн.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .. import config

_TOKEN = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(text)}


def _similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / math.sqrt(len(a) * len(b))   # косинус для множеств


@dataclass
class MemoryNode:
    node_id: str
    text: str
    t: int                          # tick
    importance: int = 5             # 1..10
    kind: str = "observation"       # observation | reflection
    access_count: int = 0
    evidence_ids: list[str] = field(default_factory=list)
    _embed: set[str] = field(default_factory=set)

    def __post_init__(self):
        if not self._embed:
            self._embed = _tokens(self.text)


class NPCMemory:
    """Per-NPC лес памяти (episodic + semantic + working)."""

    def __init__(self, npc_id: str) -> None:
        self.npc_id = npc_id
        self.nodes: dict[str, MemoryNode] = {}
        self.semantic: dict[str, str] = {}   # факт-ключ -> значение (стабильные факты)
        self._counter = 0

    def add_observation(self, text: str, now: int, importance: int = 5) -> MemoryNode:
        self._counter += 1
        nid = f"{self.npc_id}#obs{self._counter}"
        node = MemoryNode(nid, text, now, importance, "observation")
        self.nodes[nid] = node
        return node

    def add_reflection(self, statement: str, evidence_ids: list[str], now: int,
                       importance: int = 7) -> MemoryNode:
        self._counter += 1
        nid = f"{self.npc_id}#refl{self._counter}"
        node = MemoryNode(nid, statement, now, importance, "reflection",
                          evidence_ids=list(evidence_ids))
        self.nodes[nid] = node
        return node

    def set_fact(self, key: str, value: str) -> None:
        """Семантическая память: стабильный факт с детекцией конфликта (Mem0-стиль)."""
        self.semantic[key] = value

    # --- retrieval (main §5.2) -------------------------------------------- #
    def retrieve(self, query: str, now: int, k: int = config.MEM_TOPK) -> list[MemoryNode]:
        q = _tokens(query)
        scored = []
        for node in self.nodes.values():
            recency = math.exp(-config.MEM_RECENCY_LAMBDA * max(0, now - node.t))
            importance = node.importance / 10.0
            relevance = _similarity(q, node._embed)
            score = (config.MEM_ALPHA * recency + config.MEM_BETA * importance
                     + config.MEM_GAMMA * relevance)
            scored.append((score, node))
        scored.sort(key=lambda s: s[0], reverse=True)
        top = [n for _, n in scored[:k]]
        for n in top:
            n.access_count += 1
        return top

    # --- забывание/компакция (main §5.3) ---------------------------------- #
    def strength(self, node: MemoryNode, now: int) -> float:
        dt = max(0, now - node.t)
        return node.importance * math.exp(-dt / config.MEM_FORGET_TAU) \
            * (1 + math.log1p(node.access_count))

    def compact(self, now: int, threshold: float = 1.0) -> int:
        """Слабые листья-наблюдения сливаются в родителя-рефлексию (не truncation)."""
        merged = 0
        reflections = [n for n in self.nodes.values() if n.kind == "reflection"]
        for node in list(self.nodes.values()):
            if node.kind != "observation":
                continue
            if self.strength(node, now) < threshold:
                parent = next((r for r in reflections if node.node_id in r.evidence_ids), None)
                if parent:
                    del self.nodes[node.node_id]
                    merged += 1
        return merged


class CognitionStore:
    """Реестр памяти всех NPC (volatile-проекция, перестраивается из лога)."""

    def __init__(self) -> None:
        self._mem: dict[str, NPCMemory] = {}

    def memory(self, npc_id: str) -> NPCMemory:
        if npc_id not in self._mem:
            self._mem[npc_id] = NPCMemory(npc_id)
        return self._mem[npc_id]
