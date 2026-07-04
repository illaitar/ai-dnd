"""Магия (в духе Witch Hat Atelier): круг из глифов по чётким правилам → эффект.
Ядро (grammar) — детерминированно из данных, БЕЗ LLM. LLM только именует чистый круг и
разыгрывает дикую магию (слой inscribe, добавится позже). См. docs/MAGIC.md.

    from aidnd.magic import load, classify, build_spec, known_ids
"""

from __future__ import annotations

from .grammar import (
                      RULES_RU,
                      anchor,
                      base_law,
                      circle_hash,
                      classify,
                      describe,
                      glyph_cost,
                      known_ids,
                      load,
                      normalize,
                      power_budget,
)
from .inscribe import WILD_EFFECTS, Inscriber, LLMInscriber, StubInscriber, clamp_law

__all__ = ["load", "classify", "known_ids", "normalize", "describe", "anchor", "power_budget",
           "glyph_cost", "base_law", "circle_hash", "RULES_RU", "clamp_law",
           "Inscriber", "LLMInscriber", "StubInscriber", "WILD_EFFECTS"]
