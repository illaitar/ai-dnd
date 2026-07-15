# World Generation

Where the world comes from. Rule [principle 7](README.md): expensive work is forged OFFLINE in pools,
a user's world is assembled from pools **< 1 sec, without a single LLM call**.

## City graph — citygraph (pure package)

`src/aidnd/citygraph`: generation from `CityParams(seed, key_buildings=12, river, walls,
segment=16)` → street nodes/edges, building polygons (~24% rectangular), live courtyards
(garden/built-up/empty) with movement nodes, clear riverbank, fields/farmsteads. A*-routes with
landmark signs (`route → Signs`). City walks the graph; buildings are locations on it
(generator fix → placements self-heal). Visual SVG render (clickable buildings, signage) — currently
`server/web/citygen.py` (migration: [structure.md](structure.md)).
Testbed: `/citydebug`.

## Pools (offline scripts; LLM required — we don't poison pools with stub content)

| pool | script | LLM role | what gets forged |
|---|---|---|---|
| people (~1354) | `scripts/peoplegen.py` | character_writer | mechanics (traits/abilities) + persona (origin/voice/speech/quirks/aspirations/secret/values) + Flux portraits ×4 emotions (fal.ai, key `.secrets/fal.key`; cap ~500 souls) |
| buildings (599) | by type-hints | location_writer | factsheet: tier/size/age/condition/features/services/sub_rooms/containers (enum tags, not prose) |
| city names (100) | — | — | kind `city_name` in building_pool |
| items | seed-templates | — | data with rarity weights ([items.md](items.md)) |
| zone furnishings | `scripts/furnish.py` | furnisher, layout_architect | location zones + each item as a separate record + layout preset ([locations.md](locations.md)) |

Portraits — `data/portraits/` (NOT git; rsync to prod). Top-up generation: `scripts/portraits_topup.py`.
`enrich_city` (worldgen/enrichment.py): backend parallelization (cloud — parallelize,
local Ollama — sequentially), incremental writes (crash doesn't lose progress).

**Location floor plans** (`worldgen/floorplan.py` + `floorart.py`): by building zones, the code
deterministically lays out the interior (footprint archetype + simulated annealing) and draws a
"paper" page (parchment/hatching/furniture glyphs). The LLM (`layout_architect`) provides only
the FLAVOR of the layout; the code handles geometry and guarantees traversability. Details —
[locations.md](locations.md).

## Per-user world assembly (runtime, no LLM)

`user_world_create(user)` → new `world_id` (monotonic counter — IDs not reused after permanent
death) + seed → graph by seed → `_assign_key_buildings` (key buildings from pool by slot
type-hint) → residential buildings deterministically from res-pool (not written to DB) → city name
from pool → **resettlement of ALL ~1354** (`_fill_from_pool`: home+work → placements; empty pool =
hard error, bare populate is gone) → seed item pool. Container keys — belong to building owner.

## Lazy enrichment in-game

NPC inventory — on demand (corpse/theft/contract: `_materialize_npc` from persona's pockets);
item forging — on first touch (`_forge`, cache by seed); agendas — on first need
(`plan_agenda`); circle laws — on first cast (grimoire). All via LLM, all persisted.

## Next

- Sub-locations: movement through building rooms = mini-graph inside (same gates/keys).
- Parchment mask of unexplored districts — quarter polygons in geom (currently baked in SVG).
- Portraits for the missing ~400 souls in the pool.

Related: [entities.md](entities.md) (pool schemas) · [items.md](items.md) ·
[service.md](service.md) (pool deployment)
