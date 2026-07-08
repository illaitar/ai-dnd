"""Session persistence — access to the two world databases.

Key functions
-------------
_store() -> WorldStore : Access runtime world database (data/live.db).
_pool() -> WorldStore : Access content pool database (data/worlds.db).
"""

from __future__ import annotations

import os

from aidnd.worldgen import WorldStore

_STORE: WorldStore | None = None
_POOL: WorldStore | None = None


def _store() -> WorldStore:
    """RUNTIME worlds (data/live.db, not in git): placements/items/flags/contracts/states."""
    global _STORE
    if _STORE is None:
        base = os.path.dirname(WorldStore().path)
        _STORE = WorldStore(os.path.join(base, "live.db"))
    return _STORE


def _pool() -> WorldStore:
    """CONTENT POOLS (data/worlds.db, committed): people bank, buildings bank."""
    global _POOL
    if _POOL is None:
        _POOL = WorldStore()
    return _POOL
