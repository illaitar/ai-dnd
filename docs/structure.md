# Code Structure

Map of the `src/aidnd` tree (~28k lines). The `server/play` refactor **happened**: the old
`core.py`/`world.py` megapair has been split into a **module-per-system** tree (`session · pc ·
worldbuild · scene · narrator · sound · action · loop · quests · mechanics · handlers`). This doc
**supersedes the old `refactor-map.md`** (deleted) — that map's target became reality; the still-live
pain points are folded into "What's left" below.

Module dependencies: `server` orchestrates all; domain packages (`mind`, `society`, `citygraph`,
`items`, `combat`, `magic`, `plot`, `inference`, `worldgen`) do NOT import each other (exception:
`mind → items/society`) and don't know about the server. Every file opens with an English
"Key functions" docstring; the standard is **one focused module per system, no function > 50 lines**.

## Current Tree

```
src/aidnd/
  inference/   640   client (retries→LLMUnavailable) · backends ollama/openai-compat · structured
  mind/       2450   model/goals/value/act/brain/modulators/fsm/tick/sim/memory/agenda ·
                     appraisal (impression/appraise_present, perception subsystem) ·
                     llm_agent (decide_hybrid) · trade · tools · world (test microworld)
  society/     290   needs · places · routine (declarative catalogs)
  citygraph/  1970   generate · graph · model · params · render (city SVG — was server/web/citygen)
  worldgen/   4460   store (both sqlite) · population (Townsperson/settle) · enrichment · persona_llm ·
                     imagegen · furnish · floorplan · floorart · centroids (zone geometry for sound) ·
                     seed_races · abilities · dungeongen/dungeonlore · watabou · progress
  items/       860   model factsheet · attrs (attribute graph) · smith · inspect · graph (craft) ·
                     durability · loot_pool
  combat/       675   Combatant · Encounter (engine) · auto · encounters · dungeon
  magic/        425   grammar (budget/hash/base_law) · inscribe (scribe_law/wild)
  plot/         285   bible · architect · casting (NOT at runtime)
  content/            bestiary · glyphs · materials · zones.json · race_relations.json · sound_sources
  server/    15650   app (+ _replay_tap middleware) · auth · db (postgres) · usage · gencode ·
                     routes_{auth,citydebug,minddebug,npcdebug,usage} · models · debuglog
    play/    14240   replay.py (flight recorder, docs/service.md)
      engine/
        session/    state (_S proxy) · time (gt clock) · persist (both DBs) · config (PB · PLAYER)
        pc/         hero · mana · fatigue · glyphs · luck
        worldbuild/ assembly · population · jobs · ties · person · building · geom · mappng
        scene/      view (_scene_dict) · vision (look / fog / _watch_check)
        narrator/   voice (_voice · DM) · snapshot (_dm_snapshot) · lookup (_world_lookup) · scene_digest
        sound/      audibility · fidelity (cutout) · ambient  (Pillar 1, docs/sound-attention.md)
        action/     arbiter (PRIMITIVES · resolve · context assembler)
        loop/       tick (_world_tick) · routine (Ring B)
        quests/     pipeline · seeds · casting · offer · director · foreshadow · twist · framing ·
                    salience · bridge (Milestone→journal)   (docs/quests.md)
        world.py    STILL BIG (1395) — Ring A live conductor: _live_build / _live_tick / _gossip /
                    market+trade steps / salience  (the last megafile; see "What's left")
        core.py     (425) thin re-export shim over session/ + pc/  ·  resolve.py (35) facade → action+narrator
        convo · economy · incidents · geo · journal · worldsim · zones · open_hours
      handlers/     act(freeform) · travel · observe · inventory · trade · board · dungeon · magic ·
                    crime · dialogue · misc   (freeform.py 653 still holds _attempt + verb executors)
      mechanics/    combat · contracts · deals · haggle · items
bench/              harness · llmtap · snapshot · trace   (end-to-end bench, Increment 1 only — docs/bench.md)
scripts/            peoplegen · depgen · furnish · backfill_centroids · bench …
```

## What's left (honest debt)

1. **`engine/world.py` — 1395 lines, the last megafile.** It is the Ring A **live conductor**
   (`_live_build` ~260, `_live_tick` ~200, `_gossip`, market/trade steps, `_salient`). Target home:
   `loop/live/` (build · conductor · gossip), splitting `_live_tick` into <50-line steps. Everything
   else the old map named (`session · pc · worldbuild · scene · narrator · sound`) already moved out.
2. **`handlers/freeform.py` — 653 lines.** Still holds `_attempt` (the primitive×manner executor) and
   the per-verb gates. Target: `action/attempt.py` + `action/verbs/*` (one executor per verb). The
   arbiter half (`resolve`) already lives in `action/arbiter.py`.
3. **`_S` — untyped dict-blob** behind the `session/state.py` proxy, touched from many functions;
   LLM outputs are still raw dicts. Target: a **typed `Session`** and a single `inference/schemas.py`
   boundary (pydantic schemas of every LLM output: Intent/Verdict/Consequence/NpcDecision/SpellLaw/
   Persona/Contract) with validation+clamp in one place.
4. **`mechanics/` de-weld.** `combat/contracts/deals/items` still reach into `_S`/`PB`/`_store`
   directly; target is to take `(session, store, PB)` as parameters so mechanics are session-agnostic.
5. **Attention economy (Pillar 2, [sound-attention.md](sound-attention.md))** — designed, no code;
   gets an `engine/attention/` home when built. Sound **Pillar 1 shipped** (`sound/` package).

## Migration order (each = one green increment → deploy)

Remaining steps, cleanest seam first: **(a)** `world.py → loop/live/` (the live conductor split);
**(b)** `freeform._attempt → action/attempt.py + verbs/`; **(c)** `inference/schemas.py` + typed
`Session`; **(d)** `mechanics/` parameterization. After each: `uv run pytest -q` green, commit,
`/deploy`.

Related: [README.md](README.md) (principles) · [loop.md](loop.md) · [entities.md](entities.md) ·
[sound-attention.md](sound-attention.md) · [bench.md](bench.md)
