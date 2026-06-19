"""L2 LOD-симуляция — тиры, salience, smart objects (main §4)."""

from .smart_objects import block_at, fast_forward
from .tiers import LODManager, narrative_role, proximity, salience

__all__ = ["LODManager", "salience", "proximity", "narrative_role",
           "block_at", "fast_forward"]
