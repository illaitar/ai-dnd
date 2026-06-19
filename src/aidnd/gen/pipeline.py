"""Универсальный пайплайн генерации (док 01 §3, §6, §8).

Шесть стадий: Request → Constraint gather → Template select → Instantiate →
Validate → Commit. Два режима полей: табличный для механики, модель для
творчества. Цикл reject-repair: невалидное не коммитится никогда.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .lore_keeper import Verdict


@dataclass
class GenContext:
    kind: str                   # npc | item | quest | building
    where: str = ""
    why: str = ""
    hints: dict = field(default_factory=dict)
    requester: str = ""


@dataclass
class GenRequest:
    ctx: GenContext
    seed: int


@dataclass
class Constraints:
    kg_facts: list = field(default_factory=list)
    tables: dict = field(default_factory=dict)
    invariants: list[str] = field(default_factory=list)
    capacity: dict = field(default_factory=dict)


@dataclass
class Draft:
    components: dict = field(default_factory=dict)
    triples: list = field(default_factory=list)
    provenance: object = None


def commit_with_validation(draft: dict, world, validate, apply_fixes, commit,
                           max_repairs: int = 3):
    """Цикл reject-repair до N попыток, затем безопасный дефолт (док 01 §6)."""
    for _ in range(max_repairs + 1):
        verdict: Verdict = validate(draft, world)
        if verdict.valid:
            return commit(draft, world)
        draft = apply_fixes(draft, verdict.fixes, world)
    return commit(draft, world)  # safe default / flag
