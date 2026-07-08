# Game Loop

Turn-based world: **player action = world turn**. Without model, loop breaks
([principle 1](README.md)): `LLMUnavailable` → 503, `LLMBadOutput` → 502, player sees honest
error and retries action.

## Tick Tree

```
session_step(input)                                         (target: engine/loop.py)
│  durative (journey N nodes / rest until morning) → LOOP game_tick until arrival|interrupt
│  instant (dialogue / cast / deal)               → one game_tick
│
game_tick(action) → response
├── player_logic
│   ├── input
│   │   ├── UI buttons (ONLY): inventory · map_journey(node, N) · enter/exit ·
│   │   │   talk (portrait click) · combat/cast buttons
│   │   └── freeform-text → LLM-intent → routing to handler
│   └── HANDLERS (by domains, see catalog below)
├── npc_logic          LOD rings:
│   │                  A — player scene: full hybrid, LLM-decisions (cap 8 souls = LOD)
│   │                  B — city: routine from needs, deterministic (society)
│   │                  C — actors (agendas/purges): rare LLM
│   │                  D — crowd: pure mechanics
├── world_simulation   economy (caravan/restock) · monsters · guild · decay  [det; phase/day]
└── compose_response   scene · feed + addresses · narrator · interrupts
```

## Single Action Flow (as in code)

`/api/play/act` → `_play()` (world into session) → `_scene_dict()` → `_intent(text)` [LLM] →
`_attempt(intent)` — single resolver (primitive × manner × gates: rolls, item transfer,
memory, consequences) → `_gt_add(PB[...])` → `_world_tick()`:
`_apply_routine()` (ring B) + `_live_tick()` (ring A: `decide_hybrid` in parallel on
present, `apply_actions` executes — theft ACTUALLY moves items, speech written to
memory/hist, gossip spreads) → response `{narr, feed, address, gt, coins, hp, mana}`.

Modules: `server/play/handlers/freeform.py` · `server/play/engine/world.py` (scene-core) ·
`server/play/engine/worldsim.py` (society adapter) · `server/play/engine/core.py`
(session `_S`, table `PB`, time, persist).

## Handlers Catalog

| handler | inputs | LLM roles | effects | module (handlers/) |
|---|---|---|---|---|
| travel | map/move/enter/exit/room/sign_ack/live | — | location/time; path interrupts | travel.py |
| dialogue | talk/say (tone shifts relations) | voice | trust/affection/fear/memory | dialogue.py |
| magic | cast/glyphs/learn/teachers/grimoire | spell_scribe, wild_magic | mana/fatigue/damage/grimoire/taboo | magic.py |
| combat-UI | attack/defend/flee/maneuver | — | hp/statuses/death/loot | mechanics/combat.py |
| trade | offer/sell/wares/buy/askkey | voice | coins/inventory | trade.py |
| crime | steal | — | inventory/investigation/witnesses | crime.py |
| inventory | loot/inspect/commission/repair/use/give | item_smith | inventory/knowledge/stats | inventory.py |
| observe | look | narrator | fog/hidden/clues | observe.py |
| board | board/guild_redeem/board_take/delve/surrender | — | contracts/coffers/rank | board.py |
| freeform | act (everything outside catalog) | narrator (intent+DM) | by verdict | freeform.py |

**Services** (handlers call, don't duplicate): intent · voice · world_lookup · narrator.
Currently spread across `world.py`/`freeform.py` — target: `engine/resolve.py`
([structure.md](structure.md)).

## Path Interrupts

Traveling the graph ticks the world at each step; interrupted by: encounter (combat) / guard / sign
(button "map it") / story beat → PAUSE with choice. Ambient events → feed without pause.

## Design Decisions

- Single check: where a roll is needed — `d20 + axis-mod vs DC`. Magic — exception (no roll,
  failures — contradictions in the design, [magic.md](magic.md)).
- Tick advances ONLY through player spending game time; no quantization; combat — 5 sec round,
  world at minute scale is still.
- Freeform consequences: LLM proposes deltas from LIMITED menu
  (hp±/item/relation/flag/move/reveal), code validates.

## Next

- ✔ (2026-07-06) **Unified `resolve(text)`** — `engine/resolve.py`: PRIMITIVES registry
  (verb+targets+«when») — single source of truth, arbiter prompt GENERATED from registry
  (add primitive = one record; handwritten `_INTENT_SYS` dead); context collector
  yields max scene facts (people/containers/bag/zones/nearby items/places/time);
  verdict do|narrate (non-action → DM-narrator with snapshot). Executors stay in
  `handlers/freeform._attempt` (primitive×manner×gates). **CHAINS v1** (2026-07-06): one
  phrase → PLAN of 1-3 links (cap PB.plan_cap) — player as agent uses same
  tools as NPC; executor runs links in order, failure/boundary change
  (dialogue/combat/loot/move) BREAKS chain without rollback («chain breaks where it breaks»);
  in chain a link without target doesn't go to narrator (we don't gift non-existent). Arbiter sees loose
  items in OTHERS' zones («walk and take» is planned honestly). ✔ DEAL-GATE (2026-07-06,
  mechanics/deals.py): say link with stake → want×stake×DC-from-mind×roll → REAL
  obligation (contract giver=pc + gold escrow + agenda «hired» to executor + word-deed
  with deadline); refusals — three honest branches: «won't touch my own» (kin/warm tie to target),
  honest witness (_witness_crime, crime_solicit investigation), trade refusal (memory, deed solicit with
  ZONE witnesses — stealthy whisper is muffled). Morning: _deal_jobs executes blood by auto-resolver
  (same engine as purges) — flag dead, deed murder, escrow payout / deposit return;
  other types: overdue = return. DC breathes character: guard 22, townswoman 15. ✔ PERCEPTIVE LINKS
  (2026-07-06): listen primitive (one registry record!) — Perception roll vs
  base+noise×k target zone → hearing tier bought for listen_ticks ticks (others' full dialogue,
  «(overheard — …)», memory weight 0.3); unnamed target — nearest foreign dialogue;
  DM-snapshot gives narrator ONLY what player hears (own table/participation/eavesdrop) — hole
  «narrator gifts alien dialogue» closed. ✔ CHAIN BREAK (2026-07-06):
  executor `_run_plan` (freeform.py) breaks plan on FRESH salient scene event —
  «hall explodes, no time for planning» + stopped/remaining (city route pattern);
  loud accusation of dirty deal breaks salient itself — hall jerks at
  next tick AND breaks player's remaining plan. NEXT for chains: reach-auto-insert move.
- Extract `engine/loop.py` (game_tick + durative-loops); consequence-layer in
  `engine/resolve.py` — map in [structure.md](structure.md).
- Deed-log as substrate of feed/gossip/guard ([entities.md](entities.md)).

Related: [mind.md](mind.md) (ring A from inside) · [entities.md](entities.md) ·
[service.md](service.md) (LLM-call limits per tick)
