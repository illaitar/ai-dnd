"""Память NPC + SOTA-ретрива (retrieve→rerank).

Кандидаты по скору recency·importance·relevance (память Generative Agents), затем точный LLM-rerank
выбирает top-k самых релевантных ВОПРОСУ. Обращение освежает last_access (доступ укрепляет память).
Реранкер подключаем: StubReranker (офлайн/тесты) | LLMReranker.
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
    t: int                       # тик создания
    importance: float = 0.3      # яркость [0,1]
    last_access: int = 0         # тик последнего обращения (освежается ретривой)
    kind: str = "observation"    # observation | reflection | fact
    about: list = field(default_factory=list)   # id сущностей, которых касается


def _recency(m: Memory, now: int, halflife: int = 144) -> float:
    return 0.5 ** (max(0, now - m.last_access) / halflife)   # 144 тика ≈ сутки


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


class StubReranker(Reranker):
    """Без LLM — кандидаты как есть (уже по убыванию скора)."""


class LLMReranker(Reranker):
    """Точный отбор top-k релевантных вопросу через модель (роль cognition)."""

    def __init__(self, manager):
        self.manager = manager

    def rerank(self, query: str, mems: list, k: int) -> list:
        if not mems or not self.manager.available():
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
    W_REC, W_IMP, W_REL = 0.5, 1.0, 1.5     # релевантность и яркость важнее свежести

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
        """Top-k воспоминаний по вопросу: дешёвый скор → пул → точный rerank. Освежает last_access."""
        if not self.items:
            return []
        rec = _norm({m.id: _recency(m, now) for m in self.items})
        imp = _norm({m.id: m.importance for m in self.items})
        rel = _norm({m.id: relevance(query, m) for m in self.items})
        score = {m.id: self.W_REC * rec[m.id] + self.W_IMP * imp[m.id] + self.W_REL * rel[m.id]
                 for m in self.items}
        shortlist = sorted(self.items, key=lambda m: -score[m.id])[:pool]
        top = (reranker or StubReranker()).rerank(query, shortlist, k)
        for m in top:
            m.last_access = now
        return top
