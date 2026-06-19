"""Knowledge Graph мира (main §3.2).

Триплстор (subject, relation, object) поверх сущностей. Кодирует мировые законы
как структуру, а не как текст. Запрос "где живёт кузнец" — это обход графа, а не
вызов LLM. Прототипная реализация на индексах в памяти (вместо networkx/Kùzu).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class Triple:
    subject: str
    relation: str
    object: str

    def as_tuple(self) -> tuple[str, str, str]:
        return (self.subject, self.relation, self.object)


class KnowledgeGraph:
    """Индексированный триплстор с обходами по subject/relation/object."""

    def __init__(self) -> None:
        self._triples: set[tuple[str, str, str]] = set()
        self._by_s: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
        self._by_o: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
        self._by_r: dict[str, set[tuple[str, str, str]]] = defaultdict(set)

    # --- мутации (только через event.apply, см. world.py) ------------------ #
    def add(self, s: str, r: str, o: str) -> None:
        t = (s, r, o)
        if t in self._triples:
            return
        self._triples.add(t)
        self._by_s[s].add(t)
        self._by_o[o].add(t)
        self._by_r[r].add(t)

    def remove(self, s: str, r: str, o: str) -> None:
        t = (s, r, o)
        if t not in self._triples:
            return
        self._triples.discard(t)
        self._by_s[s].discard(t)
        self._by_o[o].discard(t)
        self._by_r[r].discard(t)

    def remove_where(self, subject: str, relation: str) -> None:
        """Снимает все рёбра subject-relation-* (для апдейта функциональных связей)."""
        for t in list(self._by_s.get(subject, ())):
            if t[1] == relation:
                self.remove(*t)

    # --- запросы ----------------------------------------------------------- #
    def object_of(self, subject: str, relation: str) -> str | None:
        """Первый объект для (subject, relation). Для функциональных связей."""
        for t in self._by_s.get(subject, ()):
            if t[1] == relation:
                return t[2]
        return None

    def objects_of(self, subject: str, relation: str) -> list[str]:
        return [t[2] for t in self._by_s.get(subject, ()) if t[1] == relation]

    def subjects_of(self, relation: str, obj: str) -> list[str]:
        return [t[0] for t in self._by_o.get(obj, ()) if t[1] == relation]

    def relations_of(self, subject: str) -> list[tuple[str, str]]:
        return [(t[1], t[2]) for t in self._by_s.get(subject, ())]

    def has(self, s: str, r: str, o: str) -> bool:
        return (s, r, o) in self._triples

    def by_relation(self, relation: str) -> list[tuple[str, str, str]]:
        return list(self._by_r.get(relation, ()))

    def all(self) -> list[tuple[str, str, str]]:
        return list(self._triples)

    # --- удобные доменные обходы (main §3.2) ------------------------------- #
    def lives_in(self, npc: str) -> str | None:
        return self.object_of(npc, "lives_in")

    def works_at(self, npc: str) -> str | None:
        return self.object_of(npc, "works_at")

    def owner_of(self, thing: str) -> str | None:
        return self.object_of(thing, "owned_by")

    def located_in(self, thing: str) -> str | None:
        return self.object_of(thing, "located_in")
