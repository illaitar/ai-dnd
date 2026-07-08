"""Task 8 (docs/citysim.md race relations): seed non-human races into the NPC pool — offline, no LLM.

Tags a deterministic ~10% of worlds.db:people with race орк/дворф/эльф (persona["race"]), so
race_relations.json has real targets. Idempotent: rerun is a no-op once seeded.
Run: .venv/bin/python scripts/seed_races.py
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from aidnd.worldgen import WorldStore  # noqa: E402
from aidnd.worldgen.seed_races import seed_races  # noqa: E402


def main() -> None:
    store = WorldStore()
    made = seed_races(store)
    print(f"non-human races seeded: {made}. pool total: {store.people_count()}")


if __name__ == "__main__":
    main()
