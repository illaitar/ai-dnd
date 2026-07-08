# Locations: space, zones, objects

Space belongs to the WORLD, not the mind: mind only perceives (`perceive`) and has desires
(`goals`). A location is a single entity for both interiors AND streets. Decisions finalized
2026-07-04.

## Entity

```
LOCATION = interior of a BUILDING  |  street place (graph node: plaza·street·yard·shore)
  building → rooms (sub_rooms, mini-graph) → ZONES → OBJECTS
  street  → node zones (plaza: post·well·stalls; street: shoulder·alley; yard: garden/shed)

ZONE:    kind (bar·tables·hearth·counter·shelves·storage·workshop·altar·pews·beds·private·
         bath·games·door·well·post·stalls·yard) · name · noise · privacy · capacity ·
         role post (bartender tied to counter BY WORK)
         GROUP ANCHORS expand into INSTANCES — everywhere a place lives through its own group:
         tavern tables (5-9 by building size) · gaming tables · lodge rooms (lockable) ·
         healer's cots · stable stalls · storage sections · guild squad tables · plaza stalls ·
         jail cells (kind cell, template in reserve). Instance = OWN zone: atom
         of conversation and privacy; position-spot (by window · in dark corner · under stairs ·
         behind screen…) drives noise/privacy from data. Shared remain spaces where
         people truly mingle: counter (they eavesdrop there — that's life), temple benches, hearth.
OBJECT:  FULL-FLEDGED world item (factsheet surface/hidden, [items.md](items.md)) + zone roles:
         afford {need: closure/hour}    — hearth→comfort, cauldron→hunger, cot→fatigue
         fixed | loose                  — counter cannot be carried; cup can (and can be used as weapon)
         container (+key)               — containers get zone address
```

**No stacks**: six cups = six records with living differences (chipped, cracked…).
Thousands of records — the norm; forged ONCE into the pool, worlds materialize without LLM ([principle 7](README.md)).

## Needs model recursion

Outside (ring B): BUILDING choice = `window(phase) × affinity(traits) × Σ(closure·pressure)`
([mind.md](mind.md), society). Inside — **the same scoring one level deeper**: ZONE choice via
its objects' affordances. Occupation = `use` of afford-object (no separate occupation system). 
Hungry sits at table, tired at cot, antisocial in quiet corner, craftsman stays at post. 
Hidden cache in counter — `hidden` with gate `via: context/tool`.

## Data and filling pipeline

1. **Zone templates** by building/street type — `content/zones.json` (data, not LLM): zone composition,
   kind-defaults for noise/privacy/capacity, role posts.
2. **Filling** — `furnisher` role [LLM], one call per ZONE: building factsheet + zone →
   each object as separate record (4–10 per zone), afford/fixed, ≤1 cache per zone,
   furnishing abundance honest to building tier/prosperity.
3. **Pool**: `building_pool.data.zones` (offline `scripts/furnish.py`, resume); factsheet
   containers assigned to zones.
4. **Materialization to world** (on creation, no LLM): zone objects → real `items` in
   live.db, holder = `zone:<bid>/<zid>` — lootable, usable, portable (loose).

## Location plan (visual)

`worldgen/floorplan.py` — division by [principle 2](README.md): **LLM decides taste, code —
geometry with guarantees.**

- **LLM** (`layout_architect` role, 1 call per building, cache in pool `data.layout`,
  clamped by enums): `windows left|right|both|none · bar_wall left|right ·
  tables rows|perimeter|mixed · density airy|normal|packed` — grim forge has
  no windows and packed, bright workshop — rows with windows.
- **Layout v3** (based on Make It Home / LayoutVLM research):
  - **footprint**: deterministic archetype by building seed — rectangular hall or L
    (hall + wing-alcove), outline-polygon drawn by walls; hook: worlds can substitute
    rasterized polygon of a real house from city map;
  - **anchors** (counter/hearth/workbench/altar/stairs) — by rules, frozen;
  - **groups** (tables/cots) — on LATTICE grid (rows guaranteed by construction;
    tight → lattice progressively densifies — benches edge-to-edge), layout found by
    **simulated annealing** (Metropolis, seed = building id, ~50 ms/building) with terms:
    spot preference (continuous cost: "by window" = distance to window wall) ·
    **zone privacy ↔ distance from passage** (our unique term) · sparseness ·
    clearance;
  - **guarantees**: main passage sacred, cell before EVERY door and approach to stairs
    reserved, `reachable()` — final BFS (test on 5 types × 3 presets).
  Back rooms (private/storage/**cell**) — strip behind hall with door-openings;
  lockable lodge rooms — "2nd floor" block 🔒.
- **Render, two layers**: structural SVG (debug, pool card) and **paper**
  (`worldgen/floorart.py`, one-page-dungeon aesthetic): parchment feTurbulence (grain+stains),
  trembling ink stroke (seeded — house always drawn same), Dyson hatching
  outward, ~18 furniture glyphs by kind (table with chairs, hearth with flame, anvil, barrels,
  cell grate…), doors with arcs, window ticks, lived-in fillers (rug at entrance, wood
  by hearth, floor spots/cracks), zone numbers + legend (groups collapsed: "table ×8").
  Gallery of all plans: `/citydebug/plans`.
- **Plan = game UI on entry** (on prod): entering a building, map panel replaced with
  this paper sheet (`/api/play/plan`); `paper_svg(..., game=...)` adds people markers by
  zones (click = talk), fog 🔒 on locked rooms, interactive zones; click on zone
  = "approach" (`/api/play/zone` — player position in building, time from PB). Same sheet later
  becomes combat grid ([combat.md](combat.md)).

## Scene runtime (world state, persistence)

```
body positions    zonemap in _S["live"] (pid→zone); zone choice BY NEEDS — engine/zones.py  ✔ on prod
occupations       who uses which afford-object (interruptible)                           (coming)
conversations     object {participants, zone, topic stack (raised→developed→exhausted), floor,
                  answer debts} — tied to zone                                            (coming)
events            saliency × zone × traits → who noticed (stranger=0.3, quarrel=0.7, steel=0.9) (coming)
```

**Zone choice by needs** (`engine/zones.py`, ✔ on prod): `zone_score` = Σ afford-objects ×
need pressure + privacy-by-preference (antisocial to shade) − crowding; posts keep workers,
hysteresis against jitter. Positions — live scene state; between ticks NPCs reseat
("moves — to hearth" in log+memory). Same zonemap feeds game plan.

**Building capacity vs LOD-ring** (2026-07-07, ✔ on prod): two different limiters.
CITY SIMULATION (`worldsim.routine_step`) respects CAPACITY = Σ social zone caps
(`_building_cap` via `building_zones`, excluding private/storage/cell/beds): full building
drops from tavern/temple/market candidates → crowd flows elsewhere (workers settle
first, always fit in their workplace). So "here" stays realistic BY ITSELF (tavern ~30-42,
not 200) — mechanical presence cap not needed (principle 6). LLM-SCENE: no presence cap
INSIDE building, scene = all really there (background live by needs without LLM); `PB.live_llm_cap`
= ceiling on conductor LLM turns (latency), not presence. STREET — LOD-ring
`PB.street_lod_cap`. Proof: tavern 200→31, LLM-actors=8 at population=31.

**Hearing** (three tiers; v1 ✔ on prod): whisper = own zone only · normal speech = full own
zone, other building zones — IN FRAGMENTS (memory "from corner of ear: …", no details) ·
shout / salient = whole building. NPC prompt = his memory + what he heard in earshot —
knowledge asymmetry becomes spatial (secret whispered at table in dark corner
cannot physically surface at counter). Done: other-zone reply to player — "(…, from corner of ear)
…fragment…", NPC↔NPC gossip only in own zone, addresses to player carry through hall; zones
in NPC prompt. Next: whisper yard (say-act "whisper") and shout as separate tiers.

**Distinguishability and narrator — SCENE properties** (2026-07-06): `_scene_descriptors` gives
each stranger a CATEGORY feature not taken by scene mates (scar→hair→face→
clothes→build; pool stamps "scar" on half the city — in the hall he's one); DM-narrator
of non-actions gets SNAPSHOT of live scene (`_dm_snapshot`: place/time/weather, people with zones
and occupations, recent replies, player's items) — "snapshot — sole truth";
zone match from freeform — VIA LLM (arbiter's zone field), not tokens.

**Tick conductor** (deterministic, does NOT write replies or choose outcomes): collects
all bodies' impulses — `answer debt > event reaction > hot need/agenda > background` —
LLM turn goes to bodies above impulse threshold (usually 0–2); rest — background occupation (det,
in log via LOD). Reply cap stays emergency LOD safeguard, not rule.
Address cooldown dies: "I already greeted" — fact of conversation-object ([principle 6](README.md)).

## Verification cases (scenario bench, live LLM + LLM-judge)

| # | case | assert |
|---|---|---|
| 1 | stranger enters tavern | uninvolved don't start talking; bartender greets by role ≤3 ticks; other conversations not interrupted |
| 2 | player silence | question → 2 ticks silence → one addresser reaction, no verbatim repeat |
| 3 | pair at table | 6+ replies: 0 echoes, ≥2 topic shifts, topics trace to memory/relationships/tasks |
| 4 | question→answer | debt paid first; addressee answers, not neighbor |
| 5 | zones and hearing | ✔ v1: other-zone reply — fragment; gossip only to those who heard (shout — later) |
| 6 | salient event | occupations interrupted for those who noticed; reactions by traits; return to occupations; event became topic |
| 7 | predator and witnesses | theft only when target alone in zone |
| 8 | persona pinning | 20 ticks: voice/quirks stable (judge); stop-facts don't leak |
| 9 | inflow/outflow by routine | arrive evening, leave night; newcomer greets only familiar ones |
| 10 | repeat visit | recognition + reference to past task in first reply |
| 11 | entering commerce | "how much?" → deal ≤2 ticks |
| 12 | busy craftsman | low social: short answers, doesn't drop work |
| 13 | need→zone | ✔ hungry to table, tired to cot, antisocial to corner (mechanic, tests/play) |
| 14 | object is real | stolen cup vanished from zone, appeared in bag; works as weapon |
| 15 | privacy | conspirators silent/leave to quiet zone when stranger present |
| 16 | role post | bartender doesn't leave counter in work phase without salient event |
| 17 | cache | hidden furniture doesn't surface without gate; thief with craft_eye/tool finds it |
| 18 | table choice | ✔ partial: free table by capacity, privacy by preference (engine/zones.py); "conspirators in corner" motive — with conversation-object (step 4) |

## Implementation order

1. ✔ **Zones in pool + furnisher + debug-browser** `/citydebug` — entire pool
   furnished 600/600 (2026-07-06): key 181 (~5900 objects) + res 419 (~13000).
2. ✔ **Location plans** (stages A/B/C, on prod): footprint+annealing (`floorplan.py`) →
   paper render (`floorart.py`, gallery `/citydebug/plans`) → plan as game UI on entry
   (`/api/play/plan` + `/zone`, NPC markers/fog/clicks). See "Location plan" section above.
3. ✔ PARTIAL (2026-07-05): zone positions = live scene state (`engine/zones.py`:
   needs×afford×privacy-by-preference×crowding, posts keep workers, reseat hysteresis,
   "moves — to hearth" in log; case 13 covered by tests). Hearing v1 (see above).
   Player zone persist ✔ (pc-blob). ✔ (2026-07-06) MATERIALIZATION: building furnishings →
   REAL items in live.db (holder=zone:<bid>/<zid>, lazy on first entry,
   idempotent — taken doesn't return); scene reads live zone flow; player takes
   loose from own zone (witnesses/roll when worker), fixed cannot carry; NPC pickup from
   zone ground — real inv_move. STEP 3 FULLY CLOSED.
4a. ✔ (2026-07-06) ANTI-CHORUS: actor decisions — IN WAVES (impulse-leader first, entourage
   decides in parallel but sees his bid: "⏱ RIGHT NOW already…" + ban repeat
   others' gesture/object/topic word-for-word) + PHYSICS of object use: one object —
   one pair of hands per tick (taken → next same-need → queues); background long so
   (busy-set). Metric: use-object dupes per tick 2-3 → 0; tick replies — one topic
   from DIFFERENT angles to different addressees. Tick latency not grew (~5-11s).
4. ✔ (2026-07-06) CONVERSATION-OBJECT (`engine/convo.py`: zone+participants+reply log+ANSWER DEBT;
   circle merge, dissolve by silence/zone exit; "CURRENT CONVERSATION" block in prompt;
   player replies enter via /talk /say) + IMPULSE CONDUCTOR (debt 4.0 > emotion 3.0 >
   need 1.2+hot > chat 1.6 > agenda > background; threshold PB.impulse_llm; LLM-actors 3-7 of 8,
   background live by zone occupations WITHOUT LLM) + SCENARIO BENCH `scripts/scene_bench.py`
   (D1/D2/K1/K4/K5/K12/P via aidnd.scene struct log; 6/7 green).
5. ✔ PARTIAL: saliency v1 — attack in scene wakes hall (impulse 3.5 all, "⚡ JUST
   NOW…" in prompt); deed-log v1 ALIVE ([entities.md](entities.md)): thefts+promises,
   gossip from deeds, word leads to meeting by routine. Next: street saliency/shout.
6. ✔ (2026-07-06) **Street-zones** same outline: street templates carry objects directly in
   data (`zones.json`: post/well/stalls/bench/alley with afford, runtime no LLM);
   node without building → "plaza" (geom.plaza) or "street", entry "shoulder"; `_scene_zones()` —
   single zone source for intent (scene → building → street template), "to post" on plaza
   = same move+zone as "to hearth" in tavern. Node WITH building lives by building (cr2b).
7. KNOWN WORLD BUG (shines on bench K12): society routine doesn't keep WORKER at
   post in work phase (tavern owner leaves evening) — fix in society/worldsim
   (work window = workplace window).

Related: [entities.md](entities.md) · [items.md](items.md) · [mind.md](mind.md) ·
[worldgen.md](worldgen.md) · [loop.md](loop.md)
