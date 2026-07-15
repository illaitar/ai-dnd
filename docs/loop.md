# Game Loop

Turn-based world: **player action = world turn**. Without model, loop breaks
([principle 1](README.md)): `LLMUnavailable` → 503, `LLMBadOutput` → 502, player sees honest
error and retries action.

## Tick Tree

```
player action (POST /api/play/*)  →  _gt_add  →  world mutation  →  TICK  →  response
│
├── FAST TICK  _world_tick_fast()   [act/say/move/enter/exit/room/look — ZERO LLM]
│   ├── _apply_routine()   ring B: routine_step relocates ALL residents (needs/character/time)
│   │                      + daily events + economy catch-up; idempotent per 30-min phase
│   └── _live_build()      ring A POSITIONS ONLY: who's here (settled), zones, seats; NO minds
│   → {feed:[], live_pending:True}   → client then fetches /live
│
└── SLOW TICK  _world_tick()        [POST /api/play/live — wait button + streamed follow-up]
    ├── _apply_routine()  +  _live_build()  (as above)
    ├── _live_tick()       ring A minds: decide_hybrid ∥ on present, apply_actions executes
    │                      (theft moves items, speech → memory/hist, gossip). LOD: _select_actors
    │                      — salient REASONS always think, background crowd round-robin
    └── scene_digest()     weave observable feed → ONE third-person paragraph (launder self-narration)

LOD rings:  A player scene (LLM minds, budgeted)  ·  B city routine (society, det.)
            C actors (agendas/purges: rare LLM)   ·  D crowd (pure mechanics)
```

The stitch between rings A and B (arrivals/departures as feed events, venue capacity, transit
walkers, unpin) is **[sim-stitching.md](sim-stitching.md)**.

## Single Action Flow (as in code)

`/api/play/act` → `_play()` (world into session) → `_scene_dict()` → `_intent(text)` [LLM] →
`_attempt(intent)` — single resolver (primitive × manner × gates: rolls, item transfer,
memory, consequences) → `_gt_add(PB[...])` → **`_world_tick_fast()`** →
response `{narr, feed, address, live_pending, gt, coins, hp, mana}`.

**Fast vs slow tick — the crowd is deferred.** The tick lives in `engine/loop/tick.py` as two
functions:

- **`_world_tick_fast()`** — syncs the passive world (`_apply_routine` → ring B) and builds the
  live-scene *positions* (`_live_build`: who's here, where they sit) with **zero LLM**, then
  returns `{feed:[], address:[], live_pending:True}`. Every player-facing action uses it —
  `/act`, `/say`, `/move`, `/enter`, `/exit`, `/room`, `/look`, walk-to-table — so speech and
  movement in a crowded room land **instantly** instead of blocking on N NPC minds.
- **`_world_tick()`** — the slow half: same passive sync + `_live_build`, then `_live_tick()`
  (ring A: `decide_hybrid` in parallel on present souls, `apply_actions` executes — theft
  ACTUALLY moves items, speech written to memory/hist, gossip spreads) and an end-of-tick
  `scene_digest` that launders the raw feed into one third-person paragraph. Called ONLY by
  `POST /api/play/live` — the "wait" button AND the follow-up the client fires whenever a fast
  tick returned `live_pending:True`. So the crowd's reaction *streams in* behind the action.

Modules: `server/play/handlers/freeform.py` · `server/play/engine/loop/tick.py` (tick split) ·
`server/play/engine/world.py` (scene-core: `_live_build`/`_live_tick`) ·
`server/play/engine/worldsim.py` (society adapter, `routine_step`) · `server/play/engine/core.py`
(session `_S`, table `PB`, `_here`/`_here_settled`/`_flip_arrived`, persist) ·
`server/play/engine/session/time.py` (game clock).

**Game-time write-through.** `_gt_set` (session/time.py) sets `_S["gt"]` **and** persists it to
`pc_state` immediately (`store.pc_set_gt`); `_gt_add` routes through it. Time therefore never
rewinds on a server restart / session eviction to a stale sleep-or-combat snapshot — the old
`_pc_save()`-only path fired on far fewer routes than time advanced. Best-effort: no live
session/store → skip the persist, never fatal.

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

Related: [mind.md](mind.md) (ring A from inside) · [sim-stitching.md](sim-stitching.md)
(ring-A↔B seam) · [citysim.md](citysim.md) (ring B) · [entities.md](entities.md) ·
[service.md](service.md) (LLM-call limits per tick)
