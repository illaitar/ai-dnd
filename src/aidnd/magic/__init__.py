"""Магия (в духе Witch Hat Atelier): круг из глифов по чётким правилам → эффект.
Ядро (grammar) — детерминированно из данных, БЕЗ LLM. LLM только именует чистый круг и
разыгрывает дикую магию (слой inscribe, добавится позже). См. docs/MAGIC.md.

    from aidnd.magic import load, classify, build_spec, known_ids

Key functions
-------------
load(data: dict) -> dict : Parse and normalize raw circle data structure.
classify(circle: dict) -> str : Classify circle type from glyphs and rules.
normalize(circle: dict) -> dict : Normalize circle representation for storage.
describe(circle: dict) -> str : Generate human-readable circle description.
power_budget(circle: dict) -> int : Calculate remaining power budget for circle.
base_law(circle: dict) -> dict : Extract base law from circle glyph rules.
circle_hash(circle: dict) -> str : Compute deterministic content hash of circle.
Inscriber : Base class for circle inscription and wild magic effects.
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
