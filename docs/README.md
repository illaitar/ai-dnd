# AI-DnD — Documentation (canon)

A Russian-language AI-D&D game: a living frontier town (1354 NPCs — minds, memory, needs, agendas),
per-user world assembled from pre-generated pools, turn-based world (**player action = world tick**).
The LLM parses intent, resolves ambiguity, speaks through people's voices, and arbitrates freeform;
deterministic code owns dice, budgets, inventories, and combat — and clamps everything the model
proposes.

Each file covers one domain. Together they form a complete picture of the project. Section format:
**how it works** (canon, in production) and **next** (decided but not yet implemented solutions).

## Cross-cutting principles (violation = review failure)

1. **LLM is mandatory, no fallbacks.** No model → `LLMUnavailable`, bad response →
   `LLMBadOutput`; server returns 503/502 with an honest message to the player. Stubs `Stub*` exist
   only in tests; runtime never instantiates them.
2. **LLM proposes — code clamps.** A circle's law is constrained by the drawing budget, freeform
   consequences limited to a menu of deltas, quest goals only real things in the world.
3. **Generic abstract systems, no special cases.** One action resolver, one Combatant, contracts as
   predicates, NPC behavior as utility over 7 primitives. No verb-based branching.
4. **No hardcoded gameplay numbers.** Thresholds/prices/chances in the `PB` table (engine/core.py),
   content in data (JSON/pools), not in code strings.
5. **Player is an agent like any NPC.** Special branches "if player" only in UI.
6. **No mechanical gates on NPC behavior.** Not cooldowns and caps, but modeling the missing world
   piece plus all relevant context in the prompt. LOD and dedup of feeds are fine.
7. **Pools instead of runtime generation.** Expensive content (personas, buildings, portraits)
   forged by offline scripts; world assembled from pools in <1 sec without LLM.
8. **Content ≠ state.** `worlds.db` (pools, in git) / `live.db` (runtime, gitignored); deploy
   does not wipe progress.
9. **Everything is real.** Theft moves actual items, speech is an action recorded in memory and
   history, a quest closes by world fact, NPC death leaves a body and witnesses.
10. **Turn-based world, LOD rings.** Time only advances via player spending game time; player scene
    is full hybrid with LLM, city is cheap simulation without LLM.

## Documentation map

| file | topic |
|---|---|
| [entities.md](entities.md) | data entities: world, person, building, item, contract, journal, law, knowledge; flags; both DBs |
| [locations.md](locations.md) | locations: interior zones and streets, object-items, runtime scenes, conductor |
| [loop.md](loop.md) | game loop: session_step → game_tick, handlers, services, interrupts |
| [mind.md](mind.md) | NPC minds: utility core, perception/appraisal (impression, disgust, proxemics), decide_hybrid, memory, agendas; society (needs→routine) |
| [npc-brain.md](npc-brain.md) | NPC/player as one entity: two-layer surface/hidden + identity fog + appraisal/disgust + freeform talk (shipped); attention economy + body lifecycle (design) |
| [sound-attention.md](sound-attention.md) | hearing: spatial audibility, 3-tier conversation fidelity, sound sources; attention economy as a utility term (design) |
| [citysim.md](citysim.md) | city simulation: housing, work, daily rhythm, day GIF |
| [sim-stitching.md](sim-stitching.md) | ring-A↔B seam: arrival/departure feed events, venue capacity+overflow, transit walkers, unpin, crowd LOD |
| [worldgen.md](worldgen.md) | generation: city graph → pools → per-user world assembly |
| [combat.md](combat.md) | combat BG-lite: grid, initiative, auto-resolve, gear via derivation graph, delve entry, permadeath reset |
| [dungeons.md](dungeons.md) | dungeons: cyclic generation, vignette machines, rooms as scene zones |
| [magic.md](magic.md) | circle magic: drawing → budget → law from LLM → clamp; wild magic; enchanting |
| [items.md](items.md) | items: surface/hidden/known, attribute derivation graph → effects/worth, inspection gates, rarity, spark-ladder craft, NPC & player trade + haggle |
| [quests.md](quests.md) | emergent quest pipeline (sift→judge→cast→offer→arc), predicate contracts, board+incidents, guild ranks |
| [journal.md](journal.md) | player chronicle «Хроника → дела»: quest-only, one first-person thread per quest via `j_beat` |
| [geo.md](geo.md) | NPC geographic knowledge: known_places, geometry-true directions, one mind-router, map reveal |
| [plot.md](plot.md) | main plot: regressor player, LLM bible (design doc, not in runtime) |
| [service.md](service.md) | service: auth, LLM limits, invite codes, deploy, replay recorder, UI scaffold |
| [structure.md](structure.md) | code tree: current module-per-system tree (refactor done), remaining debt + migration order |

## How to read

Start with [entities.md](entities.md) (what exists) → [loop.md](loop.md) (what happens per tick)
→ [mind.md](mind.md) (why NPCs are alive). Everything else by need. History of prior docs
(SLICE/TASKS/MAGIC/PLOT/UI and old engine docs) is in git.
