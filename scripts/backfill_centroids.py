"""Backfill zone centroids into every building already in a worlds pool.

Idempotent: re-running only rewrites cx,cy (deterministic). Run once against the
committed pool, then commit worlds.db (same pattern as scripts/seed_races.py).

Usage: uv run python scripts/backfill_centroids.py data/worlds.db

Key functions
-------------
backfill(store) -> (ok, skipped) : compute+store centroids for every pooled building.
"""

import sys

from aidnd.worldgen import WorldStore
from aidnd.worldgen.centroids import store_centroids


def backfill(store) -> tuple[int, int]:
    """Compute centroids for every pooled building and save it back. Returns (ok, skipped)."""
    ok = 0
    skipped = 0
    for b in store.pool_buildings():
        try:
            store_centroids(b["data"])
            store.pool_save_building(b["id"], b["kind"], b["btype"], b["data"])
            ok += 1
        except Exception as e:
            skipped += 1
            print(f"skip {b.get('id')}: {e}")
    return ok, skipped


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "data/worlds.db"
    n_ok, n_skipped = backfill(WorldStore(db))
    print("centroids backfilled into", n_ok, "buildings;", n_skipped, "skipped")
