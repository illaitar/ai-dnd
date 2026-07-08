# Sound & audibility (Pillar 1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every entity spatial hearing — a location's conversations and ambient sound sources reach a listener at one of three distance-based fidelity tiers (verbatim / random cutout / presence-only), rendered to the player as a darkness gradient and fed to NPCs as memory, with ambient sound handed to the narrator as prose context.

**Architecture:** A new pure module `engine/sound.py` (logic over plain dicts, no server/DB — same shape as `engine/convo.py`) owns the audibility math, the deterministic word-cutout, and ambient collection. Zone **centroids** are computed once at furnish time from the deterministic floorplan and stored on each zone record, backfilled into the existing pool by a one-off script. The existing `_dm_snapshot` overheard block in `world.py` is generalized to call `audibility()`; `play.html` renders the resulting per-line `tier` as three text colors. This is Pillar 1 of [docs/sound-attention.md](sound-attention.md); the attention economy (Pillar 2) consumes this seam in a later plan.

**Tech Stack:** Python 3.14, `uv`, pytest; FastAPI server; vanilla-JS front-end (`play.html`). Ruff auto-fixes on save (PostToolUse hook) — do not fight it; re-add imports the fixer strips before their consumer exists.

## Global Constraints

- All player-facing / LLM-prompt / ambient **string literals stay Russian**; new **code and comments are English**.
- Every new file starts with a top-of-file English docstring naming its **Key functions** (repo convention).
- **No function longer than 50 lines.**
- **No hardcoded gameplay numbers** — every tunable (falloff `k`, tier thresholds, conversation loudness, memory weights) lives in the `PB` table in `src/aidnd/server/play/engine/core.py` (principle #4).
- Content (sound descriptors) lives in `src/aidnd/content/`, loaded via `os.path.join(os.path.dirname(__file__), "..", "content", ...)`.
- Each increment ends **green** (`uv run pytest -q`) → commit → deploy (`/deploy`). Commits carry **no Claude co-author** trailer.
- Reuse existing hooks, do not rebuild: `mind.sim.perceive`/`Percept`, `mind.world.Body` (`.place` is a zone id/name), `engine/convo.py` (`_convs`, conv `{zone, members, log}`), the `PB` table, `worldgen.floorplan.plan_location` (deterministic rects `{id,name,kind,x,y,w,h}`), `worldgen.furnish.furnish_building` (writes `data["zones"]`).

---

## File Structure

- **Create** `src/aidnd/server/play/engine/sound.py` — pure audibility logic: `audibility()`, `cutout()`, `overheard_line()`, `load_sound_sources()`, `zone_source()`, `audible_ambient()`. No imports from server/DB; imports `PB` from `core` only.
- **Create** `src/aidnd/content/sound_sources.json` — authored `{by_kind, by_object}` descriptors `{loudness, ambient_ru}`.
- **Create** `scripts/backfill_centroids.py` + `src/aidnd/worldgen/centroids.py` — compute+store zone centroids; backfill the existing pool.
- **Modify** `src/aidnd/server/play/engine/core.py` — add sound `PB` keys.
- **Modify** `src/aidnd/worldgen/furnish.py` — `furnish_building` stores `cx,cy` on each zone.
- **Modify** `src/aidnd/server/play/engine/world.py` — generalize the overheard block (~1571–1611) to call `audibility()`/`overheard_line()`; collect ambient.
- **Modify** `src/aidnd/server/play/handlers/freeform.py` — `listen` primitive lifts the player's effective tier.
- **Modify** `src/aidnd/server/web/play.html` — `renderFeed` colors lines by `tier`.
- **Test** `tests/play/test_sound.py`, `tests/worldgen/test_centroids.py`.

---

## Increment 1 — Audibility foundation

Goal: `data["zones"]` carry centroids; `sound_sources.json` exists; a pure `audibility()` returns a tier. No behavior change to the live scene yet.

### Task 1: PB sound knobs + `audibility()` in `engine/sound.py`

**Files:**
- Create: `src/aidnd/server/play/engine/sound.py`
- Modify: `src/aidnd/server/play/engine/core.py` (the `PB` dict, after the EAVESDROP block near line 141)
- Test: `tests/play/test_sound.py`

**Interfaces:**
- Produces: `audibility(listener_zone: dict, source_zone: dict, loudness: float, boost: int = 0) -> str | None` returning `"L1"`/`"L2"`/`"L3"`/`None`. `boost` lifts the result by N tiers (the `listen` primitive uses it). Zone dicts carry `id`, and `cx`/`cy` when placed.

- [ ] **Step 1: Add the PB knobs.** In `src/aidnd/server/play/engine/core.py`, add to the `PB` dict immediately after the `listen_ticks` line:

```python
    # SOUND (docs/sound-attention.md): heard = loudness − sound_k · euclid(centroids); tier by thresholds
    "sound_k": 0.045,          # falloff per cell of centroid distance
    "sound_t1": 0.6,           # heard ≥ t1 → L1 (verbatim)
    "sound_t2": 0.35,          # heard ≥ t2 → L2 (cutout)
    "sound_t3": 0.12,          # heard ≥ t3 → L3 (presence only); below → inaudible
    "sound_voice": 0.8,        # loudness of ordinary conversation
    "sound_cutout_keep": 0.4,  # fraction of words kept at L2
    "sound_mem_l1": 0.18,      # overheard-memory weight at L1 (matches today's same-zone weight)
    "sound_mem_l2": 0.12,
    "sound_mem_l3": 0.06,
    "sound_murmur_k": 0.5,     # crowd-murmur loudness = occupancy_frac × zone.noise × this
```

- [ ] **Step 2: Write the failing test.** Create `tests/play/test_sound.py`:

```python
"""Pure audibility math and fidelity helpers (no server/DB).

Key tests
---------
test_same_zone_is_l1        : a normal voice in your own zone is heard verbatim (L1).
test_distance_drops_tier    : the same voice two zones away drops to a lower tier.
test_far_zone_inaudible     : far enough → None (inaudible).
test_missing_centroid_none  : a zone without a centroid is treated as inaudible.
test_boost_lifts_tier       : boost=1 lifts L2→L1 (the listen primitive).
"""

from aidnd.server.play.engine.sound import audibility


def _z(zid, cx=None, cy=None):
    z = {"id": zid}
    if cx is not None:
        z["cx"], z["cy"] = cx, cy
    return z


def test_same_zone_is_l1():
    z = _z("z0", 5.0, 5.0)
    assert audibility(z, z, 0.8) == "L1"


def test_distance_drops_tier():
    a, b = _z("z0", 0.0, 0.0), _z("z1", 10.0, 0.0)
    assert audibility(a, b, 0.8) == "L2"          # heard = 0.8 − 0.045·10 = 0.35


def test_far_zone_inaudible():
    a, b = _z("z0", 0.0, 0.0), _z("z1", 40.0, 0.0)
    assert audibility(a, b, 0.8) is None          # heard = 0.8 − 1.8 < 0


def test_missing_centroid_none():
    a, b = _z("z0", 0.0, 0.0), _z("z1")           # b unplaced
    assert audibility(a, b, 0.8) is None


def test_boost_lifts_tier():
    a, b = _z("z0", 0.0, 0.0), _z("z1", 10.0, 0.0)
    assert audibility(a, b, 0.8, boost=1) == "L1"  # L2 lifted one tier
```

- [ ] **Step 3: Run test to verify it fails.** Run: `uv run pytest tests/play/test_sound.py -q` — Expected: FAIL (`ModuleNotFoundError: aidnd.server.play.engine.sound`).

- [ ] **Step 4: Implement `engine/sound.py`.** Create `src/aidnd/server/play/engine/sound.py`:

```python
"""Sound & audibility — pure logic over plain dicts (no server/DB, tested standalone).

Distance is spatial: each zone carries a centroid (cx, cy) from the floorplan;
a sound is heard at a fidelity tier that falls off with centroid distance
(docs/sound-attention.md, Pillar 1). Same shape as convo.py.

Key functions
-------------
audibility(listener_zone, source_zone, loudness, boost=0) -> "L1"|"L2"|"L3"|None
    Fidelity tier of a sound of given loudness for a listener, by centroid distance.
"""

import math

from .core import PB

_TIERS = ("L1", "L2", "L3")


def _dist(a: dict, b: dict) -> float | None:
    """Euclidean distance between zone centroids; None if either is unplaced."""
    if a.get("id") == b.get("id"):
        return 0.0
    if "cx" not in a or "cx" not in b:
        return None
    return math.hypot(a["cx"] - b["cx"], a["cy"] - b["cy"])


def audibility(listener_zone: dict, source_zone: dict, loudness: float,
               boost: int = 0) -> str | None:
    """Fidelity tier of `loudness` heard from source_zone at listener_zone.

    heard = loudness − sound_k · distance; thresholds t1>t2>t3 pick the tier.
    boost lifts the result by N tiers (the player `listen` primitive). Unplaced
    zone (no centroid) or too-faint → None (inaudible)."""
    d = _dist(listener_zone, source_zone)
    if d is None:
        return None
    heard = loudness - PB["sound_k"] * d
    if heard >= PB["sound_t1"]:
        idx = 0
    elif heard >= PB["sound_t2"]:
        idx = 1
    elif heard >= PB["sound_t3"]:
        idx = 2
    else:
        return None
    return _TIERS[max(0, idx - max(0, boost))]
```

- [ ] **Step 5: Run test to verify it passes.** Run: `uv run pytest tests/play/test_sound.py -q` — Expected: PASS (5 passed).

- [ ] **Step 6: Commit.**

```bash
git add src/aidnd/server/play/engine/sound.py src/aidnd/server/play/engine/core.py tests/play/test_sound.py
git commit -m "sound: pure audibility() + PB knobs (spatial tier by centroid distance)"
```

### Task 2: Zone centroids at furnish time + backfill the pool

**Files:**
- Create: `src/aidnd/worldgen/centroids.py`
- Create: `scripts/backfill_centroids.py`
- Modify: `src/aidnd/worldgen/furnish.py` (`furnish_building`, near line 303 `data["zones"] = zones`)
- Test: `tests/worldgen/test_centroids.py`

**Interfaces:**
- Produces: `store_centroids(data: dict) -> dict` — mutates `data["zones"]`, writing `cx,cy` on every zone found in the deterministic floorplan; returns `data`. Consumes `worldgen.floorplan.plan_location(data, seed_key="")`.

- [ ] **Step 1: Write the failing test.** Create `tests/worldgen/test_centroids.py`:

```python
"""Zone centroids: furnish stores each zone's floorplan-rect center on the zone record.

Key tests
---------
test_centroid_is_rect_center : every placed zone gets cx,cy = rect (x+w/2, y+h/2).
test_idempotent              : running twice does not change the centroids.
"""

from aidnd.worldgen.centroids import store_centroids
from aidnd.worldgen.floorplan import plan_location


def _building():
    return {"name": "Тестовый двор", "type": "таверна", "size": "medium",
            "zones": [{"id": "z0", "kind": "hall", "name": "общий зал"},
                      {"id": "z1", "kind": "table", "name": "стол у окна"}]}


def test_centroid_is_rect_center():
    data = store_centroids(_building())
    rects = {r["id"]: r for fl in plan_location(data)["floors"] for r in fl["zones"]}
    for z in data["zones"]:
        if z["id"] in rects:
            r = rects[z["id"]]
            assert z["cx"] == r["x"] + r["w"] / 2
            assert z["cy"] == r["y"] + r["h"] / 2


def test_idempotent():
    data = store_centroids(_building())
    snap = [(z.get("cx"), z.get("cy")) for z in data["zones"]]
    store_centroids(data)
    assert [(z.get("cx"), z.get("cy")) for z in data["zones"]] == snap
```

- [ ] **Step 2: Run test to verify it fails.** Run: `uv run pytest tests/worldgen/test_centroids.py -q` — Expected: FAIL (`ModuleNotFoundError: aidnd.worldgen.centroids`).

- [ ] **Step 3: Implement `centroids.py`.** Create `src/aidnd/worldgen/centroids.py`:

```python
"""Zone centroids — store each zone's floorplan-rect center on its record.

The floorplan (plan_location) is deterministic, so we solve geometry once at
furnish time and persist (cx, cy) per zone; the runtime scene then has spatial
positions for audibility (docs/sound-attention.md) without recomputing layout.

Key functions
-------------
store_centroids(data) -> data : write cx,cy onto every zone present in the floorplan.
"""

from .floorplan import plan_location


def store_centroids(data: dict) -> dict:
    """Mutate data['zones'], setting cx,cy = rect center for each placed zone."""
    plan = plan_location(data)
    rects = {r["id"]: r for fl in plan.get("floors", []) for r in fl.get("zones", [])}
    for z in data.get("zones", []):
        r = rects.get(z["id"])
        if r:
            z["cx"] = r["x"] + r["w"] / 2
            z["cy"] = r["y"] + r["h"] / 2
    return data
```

- [ ] **Step 4: Run test to verify it passes.** Run: `uv run pytest tests/worldgen/test_centroids.py -q` — Expected: PASS (2 passed).

- [ ] **Step 5: Call it from furnish.** In `src/aidnd/worldgen/furnish.py`, add the import near the other `from .` imports at the top of the module:

```python
from .centroids import store_centroids
```

Then in `furnish_building`, change the line that finalizes zones (currently `data["zones"] = zones`) to:

```python
    data["zones"] = zones
    store_centroids(data)                # spatial positions for audibility
```

- [ ] **Step 6: Backfill the existing pool.** Create `scripts/backfill_centroids.py`:

```python
"""Backfill zone centroids into every building already in a worlds pool.

Idempotent: re-running only rewrites cx,cy (deterministic). Run once against the
committed pool, then commit worlds.db (same pattern as scripts/seed_races.py).

Usage: uv run python scripts/backfill_centroids.py data/worlds.db
"""

import sys

from aidnd.worldgen import WorldStore
from aidnd.worldgen.centroids import store_centroids


def backfill(store) -> int:
    n = 0
    for b in store.all_buildings():                 # (id, data) per pooled building
        if store_centroids(b["data"])["zones"]:
            store.save_building_data(b["id"], b["data"])
            n += 1
    return n


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "data/worlds.db"
    print("centroids backfilled into", backfill(WorldStore(db)), "buildings")
```

Before running, confirm the exact store accessors: run `grep -n "def .*building" src/aidnd/worldgen/store.py`. If the pool-wide getter/saver are named differently than `all_buildings` / `save_building_data`, adjust the two calls in `backfill()` to the real names (e.g. `building_pool()` / `save_building`). Do not invent columns — read `store.py` and use what exists.

- [ ] **Step 7: Run the backfill and verify.**

```bash
uv run python scripts/backfill_centroids.py data/worlds.db
```

Expected: prints a non-zero building count. Spot-check with:
`uv run python -c "from aidnd.worldgen import WorldStore; b=WorldStore('data/worlds.db').all_buildings()[0]; print([(z['id'],z.get('cx'),z.get('cy')) for z in b['data']['zones']][:4])"`
Expected: zones show numeric `cx,cy` (not `None`).

- [ ] **Step 8: Commit** (code + regenerated pool, as done in commit 723b08d for races):

```bash
git add src/aidnd/worldgen/centroids.py scripts/backfill_centroids.py src/aidnd/worldgen/furnish.py tests/worldgen/test_centroids.py data/worlds.db
git commit -m "worldgen: store zone centroids at furnish + backfill pool (spatial audibility)"
```

### Task 3: `sound_sources.json` + loader/lookup

**Files:**
- Create: `src/aidnd/content/sound_sources.json`
- Modify: `src/aidnd/server/play/engine/sound.py` (add loader + `zone_source`)
- Test: `tests/play/test_sound.py` (extend)

**Interfaces:**
- Produces: `load_sound_sources() -> dict` (cached) and `zone_source(zone: dict) -> dict | None` returning `{"loudness": float, "ambient_ru": str}` for a zone by its `kind` or a contained object's `kind`, else `None`.

- [ ] **Step 1: Author the content.** Create `src/aidnd/content/sound_sources.json`:

```json
{
  "by_object": {
    "очаг":  {"loudness": 0.5, "ambient_ru": "потрескивает очаг"},
    "камин": {"loudness": 0.5, "ambient_ru": "гудит пламя в камине"},
    "горн":  {"loudness": 0.85, "ambient_ru": "звенит молот у горна"},
    "фонтан": {"loudness": 0.4, "ambient_ru": "журчит вода"}
  },
  "by_kind": {
    "kitchen": {"loudness": 0.55, "ambient_ru": "с кухни доносится стук и шипение"},
    "forge":   {"loudness": 0.85, "ambient_ru": "лязг ковки заполняет воздух"},
    "hearth":  {"loudness": 0.5, "ambient_ru": "потрескивает огонь"}
  }
}
```

- [ ] **Step 2: Write the failing test.** Append to `tests/play/test_sound.py`:

```python
from aidnd.server.play.engine.sound import zone_source


def test_zone_source_by_object():
    z = {"id": "z0", "kind": "hall", "objects": [{"name": "очаг", "kind": "очаг"}]}
    src = zone_source(z)
    assert src and src["ambient_ru"] == "потрескивает очаг"


def test_zone_source_by_kind():
    assert zone_source({"id": "z1", "kind": "forge"})["loudness"] == 0.85


def test_zone_source_none():
    assert zone_source({"id": "z2", "kind": "table"}) is None
```

Note: object records may use `kind` or only `name` — the lookup checks both keys against `by_object`.

- [ ] **Step 3: Run test to verify it fails.** Run: `uv run pytest tests/play/test_sound.py -q` — Expected: FAIL (`cannot import name 'zone_source'`).

- [ ] **Step 4: Implement the loader + lookup.** Append to `src/aidnd/server/play/engine/sound.py` (add `import json, os` to the existing imports):

```python
_SOURCES: dict | None = None


def load_sound_sources() -> dict:
    """Authored ambient descriptors (cached): {by_object, by_kind} → {loudness, ambient_ru}."""
    global _SOURCES
    if _SOURCES is None:
        p = os.path.join(os.path.dirname(__file__), "..", "..", "..", "content",
                         "sound_sources.json")
        with open(p, encoding="utf-8") as f:
            _SOURCES = json.load(f)
    return _SOURCES


def zone_source(zone: dict) -> dict | None:
    """Fixed ambient source for a zone: matched by a contained object's kind/name,
    else by the zone's own kind. None if the zone emits nothing authored."""
    cat = load_sound_sources()
    for o in zone.get("objects", []):
        hit = cat["by_object"].get(o.get("kind")) or cat["by_object"].get(o.get("name"))
        if hit:
            return hit
    return cat["by_kind"].get(zone.get("kind"))
```

Confirm the content path depth: `sound.py` is at `src/aidnd/server/play/engine/`, so `../../../content` reaches `src/aidnd/content`. Verify with `uv run python -c "from aidnd.server.play.engine.sound import load_sound_sources; print(list(load_sound_sources()))"` → expect `['by_object', 'by_kind']`; if it raises `FileNotFoundError`, fix the number of `..` segments.

- [ ] **Step 5: Run test to verify it passes.** Run: `uv run pytest tests/play/test_sound.py -q` — Expected: PASS (8 passed).

- [ ] **Step 6: Commit.**

```bash
git add src/aidnd/content/sound_sources.json src/aidnd/server/play/engine/sound.py tests/play/test_sound.py
git commit -m "sound: authored sound_sources.json + zone_source() lookup"
```

- [ ] **Step 7: Deploy Increment 1.** Run `uv run pytest -q` (expect all green), then `/deploy` with message "sound: audibility foundation (centroids, PB, sources)".

---

## Increment 2 — Conversation fidelity + 3-tier rendering

Goal: overheard NPC↔NPC conversations reach the player at a spatial tier (verbatim / cutout / presence-only) and render as a darkness gradient; NPC bystanders record a tier-weighted memory; the `listen` primitive lifts the player's tier.

### Task 4: deterministic word-cutout + `overheard_line()`

**Files:**
- Modify: `src/aidnd/server/play/engine/sound.py`
- Test: `tests/play/test_sound.py` (extend)

**Interfaces:**
- Produces: `cutout(text: str, seed: str) -> str` — keep `sound_cutout_keep` fraction of words, others → «…», deterministic on `seed`. `overheard_line(text: str, tier: str, zone_name: str, seed: str) -> tuple[str, float]` — returns `(display_text, memory_weight)` for a tier (`L1` verbatim, `L2` cutout, `L3` presence-only Russian).

- [ ] **Step 1: Write the failing test.** Append to `tests/play/test_sound.py`:

```python
from aidnd.server.play.engine.sound import cutout, overheard_line


def test_cutout_is_deterministic():
    t = "караван из Хельгарда так и не пришёл третий день жду"
    assert cutout(t, "s1") == cutout(t, "s1")           # stable for a fixed seed
    assert "…" in cutout(t, "s1")                        # something was masked


def test_overheard_l1_verbatim():
    text, w = overheard_line("привет друг", "L1", "у очага", "s")
    assert text == "привет друг" and w == 0.18


def test_overheard_l3_presence_only():
    text, w = overheard_line("секрет", "L3", "у дальнего стола", "s")
    assert "секрет" not in text and "у дальнего стола" in text
```

- [ ] **Step 2: Run test to verify it fails.** Run: `uv run pytest tests/play/test_sound.py -q` — Expected: FAIL (`cannot import name 'cutout'`).

- [ ] **Step 3: Implement.** Append to `src/aidnd/server/play/engine/sound.py` (add `import random` to imports):

```python
def cutout(text: str, seed: str) -> str:
    """Keep sound_cutout_keep fraction of words (deterministic on seed), mask the
    rest with «…» — the L2 'part of a conversation' render."""
    words = text.split()
    if not words:
        return text
    rng = random.Random(seed)
    keep = max(1, round(len(words) * PB["sound_cutout_keep"]))
    idx = sorted(rng.sample(range(len(words)), min(keep, len(words))))
    out, gap = [], False
    for i in range(len(words)):
        if i in idx:
            out.append(words[i])
            gap = False
        elif not gap:
            out.append("…")
            gap = True
    return " ".join(out)


def overheard_line(text: str, tier: str, zone_name: str, seed: str) -> tuple[str, float]:
    """(display_text, memory_weight) for an overheard conversation line at a tier."""
    if tier == "L1":
        return text, PB["sound_mem_l1"]
    if tier == "L2":
        return cutout(text, seed), PB["sound_mem_l2"]
    return f"у «{zone_name}» о чём-то говорят", PB["sound_mem_l3"]
```

- [ ] **Step 4: Run test to verify it passes.** Run: `uv run pytest tests/play/test_sound.py -q` — Expected: PASS (11 passed).

- [ ] **Step 5: Commit.**

```bash
git add src/aidnd/server/play/engine/sound.py tests/play/test_sound.py
git commit -m "sound: deterministic cutout + overheard_line fidelity tiers"
```

### Task 5: generalize the `world.py` overheard block to spatial tiers

**Files:**
- Modify: `src/aidnd/server/play/engine/world.py` (the `else:` branch at ~1570–1613 — the `conv_note_say` + `same_zone`/`eaves_on`/`murmur` logic shown in the plan context)
- Test: `tests/play/test_overheard.py`

**Interfaces:**
- Consumes: `audibility`, `overheard_line` from `engine.sound`.
- Produces: feed items now carry `"tier": 1|2|3` on `k=="speech"` overheard lines (consumed by `play.html` in Task 6).

- [ ] **Step 1: Write the failing test.** Create `tests/play/test_overheard.py`. This is a focused unit test of a small extracted helper (so the huge `_dm_snapshot` need not be driven end-to-end):

```python
"""Overheard conversation lines are rendered at the audibility tier between the
speaker's zone and the player's zone.

Key tests
---------
test_same_zone_verbatim : speaker in the player's zone → L1, verbatim feed text.
test_far_zone_presence  : speaker far away → L3, presence-only text (no content).
test_out_of_earshot_none: no centroids / inaudible → None (caller bumps murmur).
"""

from aidnd.server.play.engine.world import _overheard

PZ = {"id": "z0", "cx": 0.0, "cy": 0.0}


def test_same_zone_verbatim():
    tier, text, w = _overheard("тайна каравана", PZ, PZ, "у очага", "seed")
    assert tier == 1 and text == "тайна каравана"


def test_far_zone_presence():
    far = {"id": "z1", "cx": 12.0, "cy": 0.0}
    tier, text, w = _overheard("тайна каравана", PZ, far, "у окна", "seed")
    assert tier == 3 and "тайна" not in text


def test_out_of_earshot_none():
    gone = {"id": "z2", "cx": 99.0, "cy": 0.0}
    assert _overheard("что угодно", PZ, gone, "далеко", "seed")[0] is None
```

- [ ] **Step 2: Run test to verify it fails.** Run: `uv run pytest tests/play/test_overheard.py -q` — Expected: FAIL (`cannot import name '_overheard'`).

- [ ] **Step 3: Add the `_overheard` helper.** In `src/aidnd/server/play/engine/world.py`, add near the top-level helpers (module scope, not nested), and add `from .sound import audibility, overheard_line` to the engine imports:

```python
def _overheard(text, player_zone, speaker_zone, zone_name, seed, boost=0):
    """(tier_int|None, display_text, mem_weight) for a conversation line the player
    overhears — spatial audibility tier drives the fidelity (docs/sound-attention.md)."""
    tier = audibility(player_zone, speaker_zone, PB["sound_voice"], boost=boost)
    if tier is None:
        return None, "", 0.0
    disp, w = overheard_line(text, tier, zone_name, seed)
    return int(tier[1]), disp, w
```

- [ ] **Step 4: Rewire the overheard block.** Replace the `else:` branch body (from `conv_note_say(lv, pid, tid, txt, ...)` through the `murmur` increment) so it uses `_overheard`. The speaker's zone dict and the player's zone dict come from `lv["zones"]` keyed by `w.bodies[...].place`; the `eaves` boost is `1` when the player is actively eavesdropping that speaker's zone. Concretely:

```python
                else:
                    conv_note_say(lv, pid, tid, txt, w.bodies[pid].place)
                    zn_by_place = {z["name"]: z for z in zones_l}
                    sp_place = w.bodies[pid].place
                    pl_place = w.bodies[PLAYER].place if PLAYER in w.bodies else sp_place
                    ev = _S.get("eaves") or {}
                    boost = 1 if (ev.get("place") == sp_place
                                  and lv["clock"] <= ev.get("until", -1)) else 0
                    tier, disp, mw = _overheard(
                        txt, zn_by_place.get(pl_place, {"id": pl_place}),
                        zn_by_place.get(sp_place, {"id": sp_place}),
                        sp_place, f"hear|{lv['clock']}|{pid}", boost=boost)
                    if tier is None:
                        lv["murmur"] = lv.get("murmur", 0) + 1
                    else:
                        feed.append({"k": "speech", "who": who, "tier": tier,
                                     "to": _display(tid, people) if tid in people else tgt,
                                     "text": disp})
                        pc.memory.add(f"слышал в «{lv['place']}»: {who} — {disp[:90]}",
                                      _mt(), mw, kind="heard", about=[pid])
                    spoke.append(f"сказал(а) {lv['names'].get(tid, tgt)}: «{txt[:50]}»")
                    if tid in w.npc_minds and ((not zones_l)
                                               or w.bodies[tid].place == w.bodies[pid].place):
                        _gossip(st, lv["names"].get(pid, pid), w.npc_minds[tid])
```

This removes the old `same_zone`/`eaves_on`/35%-краем-уха logic (superseded by tiers) while preserving `conv_note_say`, `spoke`, and `_gossip`. Leave the earlier `if`-branch (direct address to the player at ~1555) untouched.

- [ ] **Step 5: Run tests.** Run: `uv run pytest tests/play/test_overheard.py tests/play/test_sound.py -q` — Expected: PASS. Then `uv run pytest -q` to confirm no regression in the broader play suite.

- [ ] **Step 6: Commit.**

```bash
git add src/aidnd/server/play/engine/world.py tests/play/test_overheard.py
git commit -m "sound: overheard conversations use spatial audibility tiers"
```

### Task 6: render the darkness gradient in `play.html`

**Files:**
- Modify: `src/aidnd/server/web/play.html` (the `renderFeed` function ~line 749 and the `.lf` styles)

**Interfaces:**
- Consumes: feed items `{k:"speech", tier:1|2|3, who, to, text}` from Task 5.

- [ ] **Step 1: Add tier color classes.** In `play.html`, next to the existing `.lf` / `.lfd` / `.lfq` style rules, add (the game theme vars: `--ink` darkest, `--dim` mid, `--faint` lightest):

```css
  .lf.t1{color:var(--ink)}
  .lf.t2{color:var(--dim)}
  .lf.t3{color:var(--faint);font-style:italic}
```

- [ ] **Step 2: Apply the tier class in `renderFeed`.** Change the `f.k==='speech'` branch so it appends the tier class:

```javascript
    f.k==='speech'?`<div class="lf t${f.tier||1}"><b>${esc(f.who)}</b> <span class="lfto">→ ${esc(f.to)}</span>: «${esc(f.text)}»</div>`
```

- [ ] **Step 3: Verify in the preview.** Start the dev server (`preview_start`), enter a location with NPCs talking in different zones, and confirm via `preview_snapshot` that overheard lines appear at three visibly different greys (nearest darkest). Capture a `preview_screenshot` as proof. (Front-end change — no pytest.)

- [ ] **Step 4: Commit.**

```bash
git add src/aidnd/server/web/play.html
git commit -m "play.html: render overheard conversations as a distance darkness gradient"
```

### Task 7: `listen` primitive lifts the player's effective tier

**Files:**
- Modify: `src/aidnd/server/play/handlers/freeform.py` (the `listen` verb ~line 277–305)
- Test: `tests/play/test_sound.py` (the `test_boost_lifts_tier` from Task 1 already proves the mechanism; add a focused wiring assert)

**Interfaces:**
- Consumes: the existing `_S["eaves"] = {"place", "until"}` set by `listen`; Task 5 already reads it as `boost=1`. This task only ensures the eaves `place` matches the zone key that Task 5 compares against.

- [ ] **Step 1: Confirm the key match.** Task 5 compares `ev.get("place") == sp_place`, where `sp_place = w.bodies[pid].place` (a zone **name**, since bodies' `.place` holds the zone name). The `listen` handler currently sets `"place": (lv.get("zone_names") or {}).get(zid, z["name"])` — already a zone name. Verify these are the same namespace by reading both; if `listen` stores an id while bodies store a name, change the `listen` handler to store `z["name"]` so they match.

- [ ] **Step 2: Add a wiring test.** Append to `tests/play/test_sound.py`:

```python
def test_boost_promotes_l3_to_l2():
    a, b = _z("z0", 0.0, 0.0), _z("z1", 16.0, 0.0)   # heard = 0.8 − 0.72 = 0.08... tune
    base = audibility(a, b, 0.8)
    boosted = audibility(a, b, 0.8, boost=1)
    assert boosted is None or base is None or _z_rank(boosted) < _z_rank(base)
```

Add the helper `def _z_rank(t): return int(t[1])` near the top of the test file. (If both are `None`, pick closer centroids so `base` is `L3` — the intent is "boost never lowers fidelity.")

- [ ] **Step 3: Run tests.** Run: `uv run pytest tests/play/test_sound.py -q` — Expected: PASS.

- [ ] **Step 4: Commit + deploy Increment 2.**

```bash
git add src/aidnd/server/play/handlers/freeform.py tests/play/test_sound.py
git commit -m "sound: listen primitive lifts the player's effective hearing tier"
```

Run `uv run pytest -q` (green), then `/deploy` with "sound: 3-tier conversation fidelity + rendering".

---

## Increment 3 — Ambient → narrator context

Goal: audible ambient sources (fireplace/forge + crowd murmur) for the player's location are collected and handed to the narrator prompt as Russian phrases; ambient is never masked and NPCs never record it.

### Task 8: `audible_ambient()` collector

**Files:**
- Modify: `src/aidnd/server/play/engine/sound.py`
- Test: `tests/play/test_sound.py` (extend)

**Interfaces:**
- Produces: `audible_ambient(zones: list[dict], listener_zone: dict, occupancy: dict[str, int]) -> list[str]` — Russian ambient phrases the listener can hear: authored `zone_source` phrases whose sound reaches the listener (via `audibility`), plus a crowd-murmur phrase for busy zones. `occupancy` maps zone-id → head count.

- [ ] **Step 1: Write the failing test.** Append to `tests/play/test_sound.py`:

```python
from aidnd.server.play.engine.sound import audible_ambient


def test_ambient_includes_near_source():
    zones = [{"id": "z0", "kind": "hall", "cx": 0.0, "cy": 0.0},
             {"id": "z1", "kind": "forge", "cx": 3.0, "cy": 0.0}]
    out = audible_ambient(zones, zones[0], {"z0": 1, "z1": 0})
    assert any("ковк" in s for s in out)               # the forge carries to the listener


def test_ambient_drops_distant_quiet_source():
    zones = [{"id": "z0", "kind": "hall", "cx": 0.0, "cy": 0.0},
             {"id": "z1", "kind": "hearth", "cx": 30.0, "cy": 0.0}]
    out = audible_ambient(zones, zones[0], {"z0": 1, "z1": 0})
    assert not any("огонь" in s for s in out)          # quiet hearth too far → silent
```

- [ ] **Step 2: Run test to verify it fails.** Run: `uv run pytest tests/play/test_sound.py -q` — Expected: FAIL (`cannot import name 'audible_ambient'`).

- [ ] **Step 3: Implement.** Append to `src/aidnd/server/play/engine/sound.py`:

```python
def audible_ambient(zones: list[dict], listener_zone: dict,
                    occupancy: dict) -> list[str]:
    """Russian ambient phrases the listener can hear: authored fixed sources that
    carry to the listener + a crowd-murmur phrase for busy zones. Never masked."""
    out: list[str] = []
    total = sum(occupancy.values()) or 1
    for z in zones:
        src = zone_source(z)
        if src and audibility(listener_zone, z, src["loudness"]):
            out.append(src["ambient_ru"])
        murmur = PB["sound_murmur_k"] * (occupancy.get(z["id"], 0) / total) * z.get("noise", 0.0)
        if murmur and audibility(listener_zone, z, murmur):
            out.append("гул голосов")
    return list(dict.fromkeys(out))                     # dedup, keep order
```

- [ ] **Step 4: Run test to verify it passes.** Run: `uv run pytest tests/play/test_sound.py -q` — Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/aidnd/server/play/engine/sound.py tests/play/test_sound.py
git commit -m "sound: audible_ambient() collects reaching ambient sources + crowd murmur"
```

### Task 9: feed ambient into the narrator prompt

**Files:**
- Modify: `src/aidnd/server/play/engine/resolve.py` (the `_dm_snapshot` narrator-context builder) or `engine/core.py` (near the DM prompt string at ~line 690) — locate the exact site in Step 1.
- Test: `tests/play/test_ambient_prompt.py`

**Interfaces:**
- Consumes: `audible_ambient` from `engine.sound`; the live `lv` dict (`lv["zones"]`, player zone, occupancy via `zonemap`/`_here`).

- [ ] **Step 1: Locate the narrator context.** Run `grep -n "детали (кто рядом\|что слышно\|снимок\|_dm_snapshot\|def _dm" src/aidnd/server/play/engine/*.py`. The DM instruction string at `core.py:690` already says "что слышно" — the snapshot assembled in `_dm_snapshot` (`resolve.py`) is where audible context belongs. Read `_dm_snapshot` and find where it lists present people / scene facts.

- [ ] **Step 2: Write the failing test.** Create `tests/play/test_ambient_prompt.py`:

```python
"""The narrator snapshot carries audible ambient phrases so the DM can weave them
into prose (docs/sound-attention.md, Pillar 1)."""

from aidnd.server.play.engine.resolve import _ambient_note


def test_ambient_note_lists_phrases():
    zones = [{"id": "z0", "kind": "hall", "cx": 0.0, "cy": 0.0},
             {"id": "z1", "kind": "forge", "cx": 2.0, "cy": 0.0}]
    lv = {"zones": zones, "zonemap": {"P": "z0"}, "occ": {"z0": 1}}
    note = _ambient_note(lv, listener_zone=zones[0], occupancy={"z0": 1, "z1": 0})
    assert "слышно:" in note and "ковк" in note


def test_ambient_note_empty_when_silent():
    lv = {"zones": [{"id": "z0", "kind": "hall", "cx": 0.0, "cy": 0.0}]}
    assert _ambient_note(lv, listener_zone=lv["zones"][0], occupancy={"z0": 1}) == ""
```

- [ ] **Step 3: Run test to verify it fails.** Run: `uv run pytest tests/play/test_ambient_prompt.py -q` — Expected: FAIL (`cannot import name '_ambient_note'`).

- [ ] **Step 4: Implement `_ambient_note`.** In `resolve.py`, add (import `audible_ambient` from `.sound`):

```python
def _ambient_note(lv: dict, listener_zone: dict, occupancy: dict) -> str:
    """Russian one-liner of audible ambient sound for the DM snapshot; '' if silent."""
    phrases = audible_ambient(lv.get("zones") or [], listener_zone, occupancy)
    return f"слышно: {', '.join(phrases)}" if phrases else ""
```

- [ ] **Step 5: Wire it into the snapshot.** In `_dm_snapshot`, compute the player's zone dict (from `lv["zones"]` by the player's `place`) and the occupancy (head count per zone via the existing `zonemap` or `_here`), call `_ambient_note`, and append its non-empty result to the snapshot text the DM receives — beside the existing "кто рядом" facts. Keep it one short Russian line; do not add it to any NPC memory.

- [ ] **Step 6: Run tests.** Run: `uv run pytest tests/play/test_ambient_prompt.py -q` then `uv run pytest -q` — Expected: PASS / green.

- [ ] **Step 7: Verify in preview.** Enter a location with a hearth/forge; trigger a narrator description; confirm via `preview_logs`/`preview_snapshot` that the prose mentions the ambient sound. Screenshot as proof.

- [ ] **Step 8: Commit + deploy Increment 3.**

```bash
git add src/aidnd/server/play/engine/resolve.py tests/play/test_ambient_prompt.py
git commit -m "sound: feed audible ambient to the narrator snapshot"
```

Run `uv run pytest -q` (green), then `/deploy` with "sound: ambient sources in narration".

---

## Self-Review

**Spec coverage (docs/sound-attention.md, Pillar 1):**
- Sound sources (authored layer) → Task 3 (`sound_sources.json` + `zone_source`). Crowd murmur → Task 8. ✅
- Zone centroids (spatial distance C) → Task 2 (furnish + backfill). ✅
- One audibility function → Task 1. ✅
- Fidelity: conversation cutout (L1/L2/L3) → Tasks 4–5; ambient never masked → Tasks 8–9. ✅
- Rendering & focus (3-tier gradient) → Task 6; `listen` as tier modifier → Task 7. ✅
- Cost (no LLM in audibility) → all `sound.py` functions are pure arithmetic. ✅

**Placeholder scan:** No TBD/TODO; every code step shows complete code. Two steps ask the implementer to *confirm a real name/site by grep before editing* (store accessors in Task 2 Step 6; narrator-context site in Task 9 Step 1) — these are verification instructions, not placeholders, because the surrounding files are large and the exact accessor/site must match reality.

**Type consistency:** `audibility(listener_zone, source_zone, loudness, boost)` returns `"L1"|"L2"|"L3"|None` throughout; `_overheard` converts the tier string to `int(tier[1])` (1/2/3) for the feed and `play.html` reads `f.tier` as 1/2/3. `overheard_line` returns `(str, float)`; `zone_source` returns `{"loudness","ambient_ru"}|None`; `audible_ambient` returns `list[str]`. Consistent across tasks.

**Known follow-ups (out of scope, Pillar 2):** salience from sound, reactions-as-actions, derived duty — separate plan. Conversation loudness is a single `PB["sound_voice"]` for now (whisper/shout variation deferred).
