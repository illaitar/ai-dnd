"""Main plot: bible (theme/truth/cast 30+ with hierarchy≠importance), architect, casting.
Player — regressor. See docs/PLOT.md.

Key functions
-------------
StubArchitect : Deterministic plot architecture; cult sacrifice template for seeding.
validate_bible(b) -> list : Validates plot bible structure; returns violations.
match_cast(cast, people) -> dict : Greedily matches archetypal roles to NPCs.
ARCHETYPES : Tuple of 13+ archetypal character roles with hierarchy.
CATEGORIES : Tuple of plot categories (enemy, ally, neutral) for NPC classification.
"""

from __future__ import annotations

from .architect import StubArchitect
from .bible import ARCHETYPES, CATEGORIES, validate_bible
from .casting import match_cast

__all__ = ["StubArchitect", "validate_bible", "match_cast", "ARCHETYPES", "CATEGORIES"]
