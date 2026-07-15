"""Pass A of NPC entity enrichment (docs/superpowers/specs/2026-07-15-npc-entity-enrichment-design.md).

Deterministic, no-LLM, idempotent seeding of the 26 «D» structured fields onto every pool row's
`mech` JSON (worldview / allegiances / standing / skills / kin+sampled rels / economy / perception
+ the 2 new traits). Seconds for 1354 rows; free; re-runnable.

Run:  .venv/bin/python scripts/enrich_pool.py [--db data/worlds.db] [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from aidnd.worldgen import WorldStore  # noqa: E402
from aidnd.worldgen.enrich_pool import enrich_pool  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Pass A — derived NPC entity enrichment (no LLM).")
    ap.add_argument("--db", default=os.path.join(ROOT, "data", "worlds.db"),
                    help="path to worlds.db (default: data/worlds.db)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print 3 sample enriched rows, write nothing")
    args = ap.parse_args()

    store = WorldStore(args.db)
    n = enrich_pool(store, dry_run=args.dry_run)
    if args.dry_run:
        print(f"\n[dry-run] would enrich {n} rows in {args.db} (no writes)")
    else:
        print(f"enriched {n} rows in {args.db} (pool total: {store.people_count()})")


if __name__ == "__main__":
    main()
