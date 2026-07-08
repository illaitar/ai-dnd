# Dungeon System

Complete design (2026-07-07). Goal — **the best possible dungeon system for the player**:
beautiful grid-based D&D maps on parchment (styled like the city location system), many
rooms, hidden wings, floors, diverse shapes — and all of it **derived from the dungeon's
narrative premise** rather than pasted over random geometry.

Foundation — six research streams (PCG science · industry Brogue/Spelunky/Unexplored/Qud ·
tabletop conventions + OSR tables · LLM×PCG · **Watabou 1PDG decompilation** · adventure
design from premise). Post-mortem of previous attempts — §10. The dungeon remains a **location
of the world**: rooms = zones of live scenes, the city stack (materialization, audibility,
mind-inhabitants, deal-gates, deeds, guild) operates within.

---

## 1. Formula

**Premise (4 parameters) → three graphs → Watabou-accretion layout → layering through time →
Dyson-alphabet render → play under resource pressure.**

The premise breaks down into four independent inputs to the generator (Alexandrian/Monte Cook):

| Parameter | Determines | Example |
|---|---|---|
| **Builder** (who built it and why) | GEOMETRY: each room has a reason | tomb → processional axis |
| **Player goal** (steal/rescue/kill/learn) | TRAVERSAL TOPOLOGY: goal position, timer, denouements | rescue → goal in center, hard timer |
| **Current inhabitants** (factions and their desires) | DYNAMICS: not plot, but situation | cult → sign-fronts |
| **Catastrophe** (what happened between "then" and "now") | FURNISHINGS: traces, contrasts | chapel→lair |

From these emerges a **triple of graphs** (chief insight from adventure design research):
1. *builder's functional graph* — the plan "as it was" (typology §3);
2. *historical diff across generations* — "ruins of three authors": who rebuilt it, what broke,
   which holes were dug (unplanned loops!), what rubble remains;
3. *player's goal graph* — entrance(s), goal, ≥2 meaningfully different routes, loops,
   locks-and-keys, secrets, timer.
The map is a projection of the first two; play is traversing the third. Greatness (Thracia) occurs
when the player weaponizes the place's history (graph 2) against its current masters (graph 3).

## 2. Geometry: Watabou-accretion layout (code, zero LLM)

The 1PDG algorithm, reverse-engineered from bundle decompilation (`com.watabou.dungeon.*`) and
confirmed by the author's own phrase ("partly symmetrical tree accretion"). Our port:

1. **Room = rectangle with axis**: `origin` (entrance cell), `axis` (growth direction), `w×d`;
   widths are **odd** (door sits exactly on axis). Size classes: room (5|7)×(4-6), hall
   (5|7|9)×(7-9), short corridor 3×(4-5), junction cell 3×3. **Corridor is the same as a room**
   (narrow rectangle), no separate entity.
2. **Accretion with mirror symmetry**: queue `{seed, parent, origin, axis, size, mirror}`;
   spawn variants — symmetric pair on sides of axis, child along axis at far end, or all at once;
   **mirror twins receive ONE seed** → their subtrees unfold identically-mirrored (partial
   symmetry = "craftsmanship"). Occasionally asymmetric spawn with fresh seed. `validate`:
   collisions + cell buffer at entrance.
3. **`grow()` — the density secret**: post-pass, twin groups stretch synchronously along the axis
   one cell at a time until they hit neighbors (cap ×10) → rooms bulge to touching, share walls,
   no voids and intestinal corridors.
4. **Planner — dramaturgy on solid layout**:
   - entrance = root; **climax = farthest room by weighted A\*** (traversals through big halls cost more) —
     boss/throne/goal goes there;
   - ante-room buffer before climax;
   - **secret WINGS**: entire subtrees hide behind a secret door (not a room — a wing; critical
     path never goes through secrets);
   - locks: keys placed in rooms reachable WITHOUT passing any locked door (by construction,
     Ashmore/Nitsche) + BFS-assert "room × keys";
   - backdoor — alternate entrance (≥2 entrances where narratively justified);
   - **loops `createLoop`**: pairs of unlinked rooms sharing a wall ≥3 cells, graph distance >5
     → door in wall midpoint; repeat while candidates exist — mechanical jaquaysing;
   - `cleanUp`: prune dead-end corridors (dead-ends remain only if furnished);
   - steps between rooms (height difference within floor), rotundas (symmetric groups round out),
     colonnades in long halls, water (noise map + level threshold, rooms only, Chaikin-smoothed banks).
5. **Layout profile by ROOM TYPE** (data, `content/dungeon_types.json`) — Watabou tags as knobs:
   tomb = string+ordered+false branches; temple = ordered+rotundas+colonnades; cave = chaotic+blobs
   (cellular automaton instead of rectangles for some rooms); mine = winding+deep (long drifts,
   meaningful dead-end stopes); prison = ordered+cramped (cell modules); cistern = grid+loops
   by definition. Each type specifies: size classes, symmetry, required rooms (§3), verticality,
   prop vocabulary.
6. **Code guarantees** (as in city plans): solvable-BFS with keys; critical path free of secrets;
   Jaquays filter (cyclomaticity ≥2 — except string-tombs, which have false branches instead of
   loops; dead-ends only if meaningful); Melan test: ≥2 meaningfully different routes to goal.
   Accretion+grow nearly always valid → sub-seeds as insurance, not workaround.

## 3. Room Typology (data)

11 base types with required rooms; a strong dungeon = **seam of two types**, the join being the
heart of the map and site of catastrophe (mine breaks into tomb; temple above cave):

| Type | Structure | Required Rooms | Signature |
|---|---|---|---|
| tomb | linear processional axis + false branches | vestibule → chapel → FALSE chamber → shaft → true chamber → treasury | false ending; secrets up to 30%; undead=legitimate guard |
| mine | tree + vertical shafts | mouth, shaft-horizons, drifts along vein, stopes, pumping station, office | honest dead-ends; "dug where we shouldn't" |
| temple/monastery | public axis + cloister ring + crypt | nave, altar, sacristy, cloister-loop, cells, scriptorium, crypt | symmetry; desecration as turning point |
| prison | gate-bulb | checkpoint, guardroom, cell blocks, solitary (goal!), governor's office, drain | patrols; alarm escalation; ≥2 bypass routes |
| fortress | concentric rings | gatehouse, wall-routes, courtyard-hub, keep, armory, postern | movement ALONG walls; muster zones |
| cistern | grid with loops | many hatch-entrances, collector, gallery-junctions, cistern | flow=one-way edges; epochal layering |
| beast lair | compact 3-7 zone star | approach with signs, entrance with remains, nest, hoard, black passage | telegraph across N rooms; passage too tight for beast |
| mage tower | vertical stack + breaking linearity | guard-foyer, laboratory, library, summoning circle, observatory | teleports; "more floors than outside" |
| laboratory | process pipeline | reagent storage, dissection room, sample vats, journal archive, crematorium | escaped experiment; journals=history |
| smuggler's cache | dual-façade: legal top + hidden base | grotto-dock, warehouse, office with blackmail files, passage to city | people, not monsters; tide-timer; passwords |
| cave | organic, maximum verticality | grotto, skinning pit, stalactite hall, river/lake, siphon, chasm | ecosystem; seam with "built" = genre shift |

## 4. Floors

- **Sheet-per-floor** (tabletop tradition), staircases **aligned by XY** between floors.
- **≥2 different-type connections** between adjacent levels (Jaquays): stairs + something else
  from Alexandrian's vocabulary of 19 connectors (data): shaft, deceptive slope, trapdoor,
  chute-trap (one-way!), cave-in, river, elevator, multi-level hall (one volume, entrances at
  different heights), cross-level link (stairs L1→L3).
- Vertical CYCLES: descended stairs — returned via river; fell down chute — exited through drift
  (backtrack via different route).
- Number of floors and vertical profile — derived from type (tower 4-6 small, tomb 1-2 down,
  mine 2-3 horizons, lair 1) and CR.
- Climax — on distant floor; levels = tension levels (Sunless Citadel: deeper = creepier).
- UI: floor parchment + level switcher; staircase fans with up/down labels.

## 5. Furnishings: time layers + quotas + checklist

1. **Three time layers per room**: trace of original function (architecture) + trace of upheaval
   (breach, scorch, abandoned in haste) + trace of current inhabitant (nest in altar).
   Contrast between layers = content. The past must be readable and USEFUL (not a lecture).
2. **B/X-quota stocking** (tested on 600 rooms: 32/31/15/13): 33% monster / 17% trap /
   17% feature / 33% empty-but-furnished; treasure per classic ratios (monster 50%…empty 17%,
   "empty" rooms 1-in-6 get hidden stash). Machine-vignettes (`dungeon_machines.json`, Brogue):
   lock→key→risk→reward in one data record. Trap = signal+trigger+effect+save, honest telegraph.
3. **Goblin Punch checklist — generator asserts** (7 required): what to steal; who to kill;
   what can kill YOU (overwhelming but telegraphed threat + escape route); different paths;
   **who to talk to** (prisoner/ghost/rivals — room=zone scene!); what to experiment with;
   what they'll most likely miss.
4. **Goal from premise** (table §2.2 research): steal → goal deep behind false goal, return path
   = separate phase (shortcut opens from inside); rescue → goal in center + hard timer + ≥2
   bypass routes; stop cult → sign-fronts (3-5 escalation stages, dungeon changes between visits);
   kill beast → goal is mobile (schedule); learn → clues smeared per rule of three (each checkpoint
   ≥3 solutions).
5. **Factions with economy of presence**: what they eat, what they fear, named NPC with desire
   (lord of city incidents = mind from pool); alliance with faction = free passage through its
   territory. First 3-5 rooms TEACH the dungeon's language (Tomb of Serpent Kings).

## 6. Render: Dyson/Watabou-alphabet on parchment (city plan style)

- **Line hierarchy (strictly 4 levels)**: 0.5 grid · 1.0 hatch · 1.5 symbols/water · 3.0 walls.
  **Grid on floor only** (never on "rock"). Cell large (~15px).
- **Parchment** — our city style: feTurbulence grain+stains (floorart._defs), ink INK.
- **Drop shadow**: dungeon silhouette offset 0.2 cells, gray — "map rests on paper".
- **Dyson-hatch by silhouette**: clusters of 2-5 curved strokes (thick in middle) on Poisson
  points around outline; angle = direction to neighbor + rotation; length scales to neighbor
  (closes gaps); strokes trim against each other.
- **Door vocabulary** (Watabou, 8+ types): opening · door-frame · arch · double (with bar) ·
  grating (three dots, visible-but-not-passable) · blocked · **secret — not drawn at all** (+tapestry
  hung on wall!) · stair-entrance · stair-down · step-change.
- **Prop-glyphs** (reuse city glyphs + new): altar, barrel, boulder, box, chest, podium,
  fountain, sarcophagus, statue, tapestry, throne, well, columns (chance broken), colonnades,
  floor cracks, rubble, water (Chaikin ×3 + wavy-crests + wavy lines).
- **Clockwise numbering** around center; legend in margins; text with white halo; title +
  narrative premise italicized below it (from brief).
- Play: fog (seen only), ghost "?" at doors, player marker, zoom by explored, room tooltips.

## 7. LLM and pool (our pattern, principle unchanged)

Everything offline in pool (worlds.db kind=dungeon), runtime deterministic by seed, no LLM at runtime.
**Brief v2** (`dungeon_architect`): premise by 4 parameters (builder/goal/inhabitants/catastrophe),
room type(s) from enum §3 + seam, style tags from enum layout, 5-9 bit-traces across three time
layers, faction with desire, naming, lock_flavor, sign-fronts. NO COORDINATES. **Decorator v2**:
vignettes keyed to TYPE room archetypes (not abstract hall/cave, but "vestibule/false-chamber/stope/cloister"
from §3), each clue → bit id; validator catches dangling refs. Vignette distribution no-repeat by seed.

## 8. Gameplay

Everything that works is retained: traversal with fog, informed door choice (hint by contents),
traps with save throw, searching (treasures/keys/machines/secrets), room combat on existing grid
(room shape → arena), wandering encounters, city incidents and lair incidents as PREMISE SOURCES,
incident_resolve with real coffers/prisoners. Added in phases: **light as timer** (torch 6 turns,
visible pressure counter), sign-fronts (dungeon lives between visits), restocking 1-in-6 per day,
**room = zone scene** (prisoner-mind, negotiation, deal-gate "bribe the guard"), extracting loot
as separate phase, persist traversal state in pc-blob.

## 9. Implementation Plan

- **D1 — geometry+render ✔ CORE** (2026-07-07, on prod): `worldgen/watabou.py` — 1-to-1 port
  (room=rectangle with axis, odd widths, twin queue with ONE seed + random room picker "pick one
  of the rooms", grow-bulge by groups to touching, createLoop on shared walls ≥3, cleanUp dead-end
  corridors with tail trim, rotundas at symmetric groups, water noise+threshold, colonnades). Planner
  in dungeongen: goal = farthest by weighted path (halls cost more), secret WING-subtrees, locks:
  lock all first — then keys OUTSIDE any lock, steps, rewarded dead-ends. Render v4: shadow-underlay,
  floor grid, dense Dyson-hatch by clusters, doors/steps/grates/locks/S, water with waves, columns,
  clockwise numbering. 48/48 seeds, ~8ms/dungeon. FINALIZED per port audit (2026-07-07): addSteps
  0.5 as original, buildApproach (ante-room "buffer" before climax — guard in stock), addBackdoor
  (alternate entrance by tag), dead-tree completion — TO CENTROID (fixes snakiness), loop threshold
  >5 (original), Poisson-hatch with curved clusters and thinning, tapestry on secret door.
  **D1 REMAINDER ✔** (2026-07-07): type profiles — `content/dungeon_types.json` (7 profiles:
  tomb/temple/mine/keep/warren/cistern/sanctum × knobs order/corridor/hall/string/rotunda/water/steps
  + prop vocabulary + goal_prop), type chosen by lair environment; prop-glyphs (sarcophagus/throne/
  altar/statue/chest/barrel/box/fountain/well/podium/boulder — per original drawings.*), climax carries
  profile glyph; loops — second pass after cleanUp (median cyclomaticity 2). Not 1-to-1 retained:
  exact spawn probabilities (no numbers in decompile) and Lehmer-RNG (original seeds).
- **D2 — floors ✔** (2026-07-07, on prod): room graph UNIFIED (floor — room field, inter-floor links
  — edges stairs/chute/collapse), floor = render view (sheet-per-floor). XY-alignment honest: floor
  N+1 root = floor N staircase cell (staircase physically in both rooms), one-shift normalization.
  Stairs — in FARTHEST room of floor; second different-type link — by XY floor intersection (chute
  ONE-WAY down / shaft / cave-in) → vertical cycles. Goal always on lowest tier; deeper = meaner
  (stock ×(1+0.25·floor)); return guarantee _solvable_back (chutes don't lock). Render: marks (stair
  fan/chute gape/cave-in scatter + arrow ↓↑), label "level K/N", inter-floor ghost clickable; gallery
  shows all sheets. Number of floors — from type profile (mine 2-3, lair 1). 4 floor tests (174 total).
- **D3 — premise**: dungeon_types.json → required rooms in Planner, brief v2 + decorator v2, pool
  reforging, goal-from-premise, GP checklist as asserts.
- **D4 — depth gameplay**: light-timer, sign-fronts, restocking, room=zone scene, loot extraction,
  traversal state persist.

Each phase — green increment to prod with gallery for taste testing before game integration.

## 10. Post-mortem of previous attempts (to not repeat)

1. *Ring on coarse 9×7 grid*: rooms pegged to sparse grid → square islands with intestinal
   corridors. Error: space enslaved to graph.
2. *Accretion flush without grow*: appearance correct, but packing a long ring chain stalls
   (3/24 seeds failed to assemble in 24 sub-seeds), layout crawls sausage-like. Errors: chain
   growth instead of tree with symmetry; no grow-bulge; loops laid out, not found. Watabou lesson:
   **tree by accretion + grow to touching + loops/climax/secrets FOUND on solid layout** —
   validity by construction, dramaturgy as separate pass (Planner), never the reverse.
3. Dormans's cycle vocabulary not discarded — it moves to Planner as dramaturgy pattern vocabulary
   (two arcs = two routes to farthest room, short-dangerous/long-safe = found-loop tagging, foreshadow
   = grate/window).
4. Work that SURVIVES the redesign: B/X stocking + machines + traps (§5), pool briefs (move to v2),
   traversal/fog/combat/search (handlers/dungeon.py), city incidents, cycle vocabulary (in Planner),
   parchment/hatch-primitives floorart.

Related: [worldgen.md](worldgen.md) · [locations.md](locations.md) · [combat.md](combat.md)
· [items.md](items.md) · [loop.md](loop.md) · [entities.md](entities.md)
