"""Магия (в духе Witch Hat Atelier): круг из глифов по чётким правилам → эффект.
Ядро (grammar) — детерминированно из данных, БЕЗ LLM. LLM только именует чистый круг и
разыгрывает дикую магию (слой inscribe, добавится позже). См. docs/MAGIC.md.

    from aidnd.magic import load, classify, build_spec, known_ids
"""

from __future__ import annotations

from .grammar import build_spec, classify, known_ids, load
from .inscribe import (WILD_EFFECTS, Inscriber, LLMInscriber, StubInscriber, circle_hash)

__all__ = ["load", "classify", "build_spec", "known_ids",
           "Inscriber", "LLMInscriber", "StubInscriber", "circle_hash", "WILD_EFFECTS"]
