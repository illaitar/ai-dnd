"""Game loop /api/play — package with layers (see docs/loop.md):

    engine/     core-scene: core (session/state/router/time/mana) · world (scene/tick/voice) · worldsim
    mechanics/  domain-mechanics: items · contracts · combat
    handlers/   domain handlers (endpoints): magic · dialogue · trade · crime · inventory ·
                observe · misc · board · travel · freeform

Importing submodules registers endpoints on the common router (located in engine.core).
"""

from .engine import world  # noqa: F401 — core-scene (tick/live scene)
from .engine.core import router
from .handlers import (
    board,
    crime,
    dialogue,
    freeform,
    inventory,
    magic,
    misc,  # noqa: F401
    observe,
    trade,
    travel,
)
from .mechanics import combat, contracts, items  # noqa: F401 — mechanics

__all__ = ["router"]
