"""Appraisal: turning percepts/traits into emotion deltas and social readings.

Key functions
-------------
load_race_relations : lazily load + cache the race_relations.json sentiment table.
race_sentiment : how race `a` feels about race `b` (self -> mild positive, else table lookup).
"""

import json
import os

_RACE_RELATIONS: dict | None = None


def load_race_relations() -> dict:
    """Load the race_relations.json table once and cache it in a module global."""
    global _RACE_RELATIONS
    if _RACE_RELATIONS is None:
        p = os.path.join(os.path.dirname(__file__), "..", "content", "race_relations.json")
        with open(p, encoding="utf-8") as f:
            _RACE_RELATIONS = json.load(f)
    return _RACE_RELATIONS


def race_sentiment(race_rel: dict, a: str, b: str) -> float:
    """How race `a` feels about race `b`, in [-1..1].

    A race about itself defaults to a mild positive (in-group bias). An authored
    pair returns its table value. An unlisted pair is neutral (0.0).
    """
    if a == b:
        return 0.15
    return float(race_rel.get(a, {}).get(b, 0.0))
