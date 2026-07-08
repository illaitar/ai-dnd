# Code Structure: Current → Target

Map of the `src/aidnd` tree (~16.5k lines), an honest list of issues and migration plan.
Module dependencies: `server` orchestrates all; domain packages (`mind`, `society`, `citygraph`,
`items`, `combat`, `magic`, `plot`, `inference`, `worldgen`) do NOT import each other
(exception: mind → items/society) and don't know about the server.

## Current Tree

```
src/aidnd/
  inference/   700   client (retries→LLMUnavailable) · backends ollama/openai-compat · structured
  mind/       2000   mind: model/goals/value/act/brain/modulators/fsm/tick/memory/agenda/
                     llm_agent (decide_hybrid) / trade / tools / world (test microworld)
  society/     235   needs · places · routines (declarative catalogs)
  citygraph/   850   graph generation · A* · model · parameters
  worldgen/   1800   store (both sqlite) · enrich buildings · personas · imagegen · enrichment ·
                     furnish (furnisher role: zones+items) · floorplan (footprint+annealing) ·
                     floorart (paper render plan: parchment/stroke/hatching/glyphs)
  items/       560   model factsheet · smith · inspect · craft (material graph) · durability · loot_pool
  combat/      620   Combatant · Encounter · auto · encounters · dungeon
  magic/       390   grammar (budget/hash/base_law) · inscribe (scribe_law/wild)
  plot/        260   bible · architect · casting (NOT at runtime)
  (play/ demolished 2026-07-07 → worldgen/population.py: Townsperson/populate/person_core)
  content/           bestiary.json (322) · glyphs · materials · zones.json (location zone templates)
  server/    10950   app · auth · db(postgres) · usage · debug-rigs (+plansdebug: gallery
                     of plans) · web/ (only play.html/assets — citygen.py moved to citygraph/render.py) ·
                     play/: engine{core 802, world 1400, worldsim, zones (zone selection by needs)} ·
                     mechanics{items, contracts, combat} · handlers{10 domain: +building plan
                     /plan /zone in travel}
scripts/            furnish.py (furnishing pool with zones) · peoplegen · buildinggen · bench …
```

## Issues (as of revision 2026-07-04)

1. **`engine/world.py` — 1835 lines** (was 1307 at revision 2026-07-04 — grew, didn't shrink),
   functions of 200-485 lines (`_live_build` ~258, `_live_tick` ~485, `_world_tick`) know everything
   at once: generation, routines, LLM-planning, combat. Main goal of Phase B refactoring.
2. **`_S` — untyped dict-blob** in contextvar, touched from 50+ functions; LLM outputs —
   raw dicts without schemas.
3. **mechanics → core directly** (`_S`, `PB`, `_store`) — mechanics are welded to the session.
4. ✔ PARTIAL: `engine/resolve.py` — arbiter `resolve(text)` + context assembler, prompt from
   PRIMITIVES registry (`_INTENT_SYS` died, 2026-07-06). Services `_voice`/`_world_lookup`/
   `_dm_snapshot` MOVED from world.py to resolve.py (2026-07-08, world.py 1835→1632; functions
   are AST-identical, world→resolve with no cycle — resolve pulls world lazily). Remaining: consequence-
   layer and `engine/loop.py`.
5. ✔ (2026-07-07) **Twins demolished**: `aidnd/play` → `worldgen/population.py`;
   `server/web/citygen.py` → `citygraph/render.py` (normal sibling import instead of importlib).
   Remaining debt ≤50 lines: `render.build_city` (~398) and `render.render_svg` (~231) — decomposition
   in a separate pass under visual review /citydebug.
6. No deed-log: feed/gossip/wanted/chronicle — five ad-hoc mechanisms.

## Target Tree

```
src/aidnd/
  inference/       + schemas.py: UNIFIED boundary — pydantic-schemas of ALL LLM outputs
                     (Intent, Verdict, Consequence, NpcDecision, SpellLaw, Persona, Contract)
  mind/ society/   as is (purity standard)
  citygraph/       + render.py (moving server/web/citygen.py — city visuals to graph)
  worldgen/        + population.py (moving aidnd/play — Townsperson/settlement); play/ package dies
  items/ combat/ magic/ plot/ content/   as is
  server/
    app.py auth db usage debug-rigs web/
    play/
      engine/
        session.py   TYPED Session (Player / LiveScene / CombatRef) instead of _S-blob
        core.py      PB · time · persist (shrinks)
        loop.py      session_step + game_tick + durative-cycles + interrupts   [from world.py]
        resolve.py   resolve(text)→{domain,goals,args,verdict} · context_assembler ·
                     consequence(clamp-menu) · voice · world_lookup            [from world/freeform]
        world.py     scene only: _live_build/_live_tick/_scene_dict (shrinks to ~500)
        worldsim.py  society adapter
        deeds.py     deed-log: append + queries for gossip/watch/chronicle/plot
      mechanics/     items · contracts · combat — accept (session, store, pb) as PARAMETERS
      handlers/      thin endpoints: unpack request → service → response
```

## Migration Plan (order = priority; each step — green increment to prod)

1. **`engine/resolve.py` + `engine/loop.py`** — extract services and tick from `world.py`/
   `freeform.py`; behavior unchanged, world.py shrinks by half.
2. **`inference/schemas.py`** — LLM output schemas, validation+clamp in one place
   (structured.py becomes a thin parser under schemas).
3. **Typed `Session`** — behind `_S` facade (incrementally: field by field), mechanics
   are moved to parameters.
4. ✔ (2026-07-06) **Unified `resolve()`** — arbiter+context in `engine/resolve.py`,
   prompt from primitives registry; executors still in `freeform._attempt`.
5. ✔ (2026-07-07) **Moves**: `aidnd/play` → `worldgen/population.py` (4 importers updated);
   `server/web/citygen.py` → `citygraph/render.py`. Folder-per-domain restored, `server/web/`
   holds only assets.
6. **`deeds.py`** — deed log + transition gossip/wanted/chronicle/requests to it
   ([entities.md](entities.md) "Further").

Related: [README.md](README.md) (principles) · [loop.md](loop.md) · [entities.md](entities.md)
