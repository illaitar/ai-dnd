"""NPC memory + SOTA-retrieval (retrieve→rerank).

Candidates scored by recency·importance·relevance (Generative Agents memory), then precise LLM-rerank
selects top-k most relevant to QUERY. Access refreshes last_access (access strengthens memory).
Plug in a Reranker (LLMReranker) or None — then shortlist by mechanical score as-is
(this is ranking, not content: the only sanctioned 'no-LLM' place).

Key functions
-------------
Memory : NPC memory record with text, importance, recency tracking.
relevance_lexical(query, m) -> float : Lexical token overlap scoring.
Reranker : Base reranking interface for memory retrieval strategies.
LLMReranker(manager) : LLM-driven top-k selection by relevance via cognition.
MemoryStore : Memory bank with scored recall (recency·importance·relevance).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


def _tokens(s: str) -> set:
    return {w[:5] for w in re.split(r"[^0-9a-zа-яё]+", (s or "").lower()) if len(w) >= 3}


def _parse_json(text: str | None) -> dict | None:
    if not text:
        return None
    t = re.sub(r"```$", "", re.sub(r"^```(?:json)?", "", text.strip()).strip()).strip()
    try:
        return json.loads(t)
    except (json.JSONDecodeError, ValueError):
        i, j = t.find("{"), t.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(t[i:j + 1])
            except (json.JSONDecodeError, ValueError):
                return None
    return None


@dataclass
class Memory:
    id: int
    text: str
    t: int                       # tick of creation
    importance: float = 0.3      # brightness [0,1]
    last_access: int = 0         # tick of last access (refreshed by retrieval)
    kind: str = "observation"    # observation | reflection | fact
    about: list = field(default_factory=list)   # id of entities this concerns


def _recency(m: Memory, now: int, halflife: int = 144) -> float:
    return 0.5 ** (max(0, now - m.last_access) / halflife)   # 144 ticks ≈ day


def relevance_lexical(query: str, m: Memory) -> float:
    q, t = _tokens(query), _tokens(m.text + " " + " ".join(m.about))
    return (len(q & t) / len(q)) if q and t else 0.0


def _norm(d: dict) -> dict:
    if not d:
        return {}
    lo, hi = min(d.values()), max(d.values())
    rng = (hi - lo) or 1.0
    return {k: (v - lo) / rng for k, v in d.items()}


class Reranker:
    def rerank(self, query: str, mems: list, k: int) -> list:
        return mems[:k]


class LLMReranker(Reranker):
    """Precise top-k selection of memories most relevant to query via model (cognition role)."""

    def __init__(self, manager):
        self.manager = manager

    def rerank(self, query: str, mems: list, k: int) -> list:
        if not mems:
            return mems[:k]
        listing = "\n".join(f"{i}. {m.text}" for i, m in enumerate(mems))
        system = (f"Дан вопрос и пронумерованные воспоминания NPC. Верни ТОЛЬКО JSON "
                  f'{{"ids":[...]}} — номера до {k} САМЫХ релевантных вопросу, по убыванию релевантности.')
        resp = self.manager.call("cognition",
                                 [{"role": "system", "content": system},
                                  {"role": "user", "content": f"Вопрос: {query}\nВоспоминания:\n{listing}"}],
                                 options={"temperature": 0})
        ids = (_parse_json(resp.get("content") if resp else None) or {}).get("ids") or []
        picked = [mems[i] for i in ids if isinstance(i, int) and 0 <= i < len(mems)]
        return (picked or mems)[:k]


class MemoryStore:
    W_REC, W_IMP, W_REL = 0.5, 1.0, 1.5     # relevance and brightness more important than recency

    def __init__(self):
        self.items: list[Memory] = []
        self._next = 0

    def add(self, text: str, t: int, importance: float = 0.3,
            kind: str = "observation", about=None) -> Memory:
        m = Memory(self._next, text, t, importance, t, kind, list(about or []))
        self.items.append(m)
        self._next += 1
        return m

    def recall(self, query: str, now: int, k: int = 10, reranker: Reranker | None = None,
               pool: int = 30, relevance=relevance_lexical) -> list[Memory]:
        """Top-k memories for query: cheap scoring → pool → precise rerank. Refreshes last_access."""
        if not self.items:
            return []
        rec = _norm({m.id: _recency(m, now) for m in self.items})
        imp = _norm({m.id: m.importance for m in self.items})
        rel = _norm({m.id: relevance(query, m) for m in self.items})
        score = {m.id: self.W_REC * rec[m.id] + self.W_IMP * imp[m.id] + self.W_REL * rel[m.id]
                 for m in self.items}
        shortlist = sorted(self.items, key=lambda m: -score[m.id])[:pool]
        top = reranker.rerank(query, shortlist, k) if reranker else shortlist[:k]
        for m in top:
            m.last_access = now
        return top
