# Sim Stitching — the ring-A↔B seam

For a long time the two rings never talked. Ring B (the passive city sim, [citysim.md](citysim.md))
relocated ~1354 residents every 30 game-min; ring A (the live LLM scene, [locations.md](locations.md))
breathed around the player. But the town's motion never *touched* the player's scene: passive
movement was invisible, scene NPCs were frozen out of the sim, venues had only soft per-call
capacity, and cross-town moves teleported. This file is that seam — **four increments, all on
prod, ZERO new LLM calls** (churn lines ride the pre-existing `scene_digest`).

Code: `engine/worldsim.py` (`routine_step`, `_transit_node`, `_plan_move`, `transit_of`) ·
`engine/core.py` (`_here`, `_here_settled`, `_flip_arrived`, `_display`) ·
`engine/world.py` (`_live_build` diff, `_churn_items`, `_salient`, `_live_tick`, `_select_actors`) ·
`engine/loop/routine.py` (`_apply_routine`). Spec of record:
`docs/superpowers/specs/2026-07-14-sim-stitching-design.md`.

## How it works (all four increments in prod)

### Inc1 — arrivals & departures as feed events

Every scene rebuild diffs the previous occupant set against the new one and emits **join/leave
feed items** — no new model call. `_live_build` (`world.py`) keeps a `churn` **queue** on
`_S["live"]`: on a same-loc rebuild it appends `_churn_items(prev.who, here, …)` and never
overwrites (undrained items from a prior fast tick survive — the client only drains via `/live`).
`_live_tick` pops the whole queue atomically and prepends it to the feed
(`feed = churn + zone_feed`); `scene_digest` narrates it like any other feed line (shape
`{k:"deed", who, text}`, exactly what `_event_lines` consumes).

- **Salience** (`_salient`) decides who gets a **named** line — all REAL fields, nothing invented:
  `PLAYER in state.relationships` (acquaintance), an active/offered contract's `giver` or
  `target`, `role == "стражник"`, or wounded (`state.hp < state.config.max_hp`; note `max_hp`
  lives on the config, not the state). A quest-giver arrival even gets «, ищет тебя взглядом».
- **Everyone else folds into ONE summary line per direction** — «народ прибывает — вошли трое» /
  «зал редеет — вышли двое», via a small RU numeral helper `_ru_count` (`двое…шестеро`, fallback
  «N человек»). Named lines are capped at `PB.churn_named_max` (2) per direction; salient overflow
  drops into the summary.
- **Identity fog applies** — every churn/pass-through line renders the person via `_display`:
  `PLAYER→ты`, a met NPC → name, an unmet one → scene descriptor / «прохожий», never a raw id.

### Inc2 — hard capacity + overflow

`routine_step` builds a **durable ledger** `load = Counter(crof.values())` plus the player at
`_S["loc"]` — recomputed from `crof` every call, never persisted (a pure function of the durable
placement, so a restart can't drift it; the observed "134 душ" spikes are now impossible). A
resident vacates their **own** origin seat before deciding anew (else they read their own
occupancy as "full" and self-evict every slot — a revolving door). A venue is full when
`load[node] ≥ _building_cap(bid)` (Σ social-zone caps, min 6, default 14, cached per bid);
`_candidates` then walks the same-need candidate list (tavern/temple/market) down
`PB.overflow_max_hops` (2) to the next non-full node, falling back to a street node if exhausted —
never stuck. **Commitments respect it too**: an appointment/shift to a full node lands the NPC «у
входа (ждёт)» rather than phantom-stacking inside. The player is counted but **never rejected** —
`move` does not consult the ledger (§6 of the spec: the player is a special actor, always
admitted; a full venue only reads as crowded around him).

### Inc3 — transit as derived state (query-shaped walkers)

A **free** routine reassignment (not a commitment — those must land this slot, since a follow
destination is dynamic) of ≥ `PB.transit_min_steps` (3) nodes no longer teleports. `_plan_move`
decides instant-flip vs walker; a long hop writes a **transit row** to `_S["transit"][pid] =
{from, to, depart_gt, arrive_gt = depart + steps×step_min, path}` and leaves `crof` at the
**origin**. Position is then **derived on demand**, nothing ticks per NPC:

- `_transit_node(row, gt)` = `path[(gt−depart)//step_min]`, O(1); `to` once arrived.
- `_flip_arrived(spot)` (core.py) is lazy: on any here-query, rows past `arrive_gt` flip into
  `crof` and are deleted (orphan rows whose pid vanished are composted, never a phantom).
- `_here_settled(node)` = `crof` members at node **minus** anyone in flight — this drives scene
  rebuilds and interaction, so a walker passing through never thrashes a full rebuild.
- `_here(node)` = settled **plus** any walker whose derived position == node — kept transit-aware
  for **witnesses** (crime, audibility, guards): someone crossing a crime node still sees it.
- On a **street** scene, `_live_tick` appends a **pass-through** line «проходит мимо, не
  задерживаясь» for each transit walker currently co-located with the player (not added to the
  who-set → no rebuild). Read paths (schedule card / geo) answer «в пути» via `transit_of` (which
  deliberately does NOT touch `predict`/`crosses` — the forecast stays on the utility path).
- **Observability**: the ТИК log carries «в пути=N» — the count of live transit rows this tick.

### Inc4 — unpin (+ polite one-slot postpone)

The `pin` parameter is **gone** from `routine_step`/`_apply_routine`. A resident standing in the
player's tavern whom the routine decides to move now actually LEAVES — the departure surfaces as
Inc1's leaver-diff (named or summary) plus, if it's a long hop, an Inc3 transit row. The **one**
exception is a code-owned world rule, not a mind gate: an NPC **mid-conversation with the player**
(`_S["dlg"] == pid`) has his move **postponed one slot** (`PB.depart_postpone_slots` = 1) —
«человек, занятый разговором, не срывается с места на полуслове» — his origin seat is re-credited,
no crof/transit change, no event; the next slot he leaves regardless. Bounded at one slot so he can
never be trapped.

Load-bearing ordering (`_apply_routine`): `_here_settled(loc, crof)` runs `_flip_arrived`
**globally before** `routine_step` builds the ledger, so a walker who just arrived is counted at
its DESTINATION (crof already flipped), not its stale origin. Do not reorder.

### Crowd LOD — reason-based salience (the tick-cost fix)

Not part of the four increments but shipped alongside: how many NPCs get an LLM decision per tick
is now **REASON-based**, not a numeric impulse threshold. `_select_actors` (`world.py`): NPCs
whose impulse label is in `_MUST_WHY` — `{событие, долг ответа, слово, тень дела, эмоция, услышал
чужака}` (a live event, an owed answer, a due promise, a foreshadow beat, a hot emotion, or
overhearing the player) — **always** think; the reasonless background crowd
(«беседа»/«нужда»/«агенда»/«фон») is staggered through a round-robin (`lv["rot_cursor"]`) inside
the crowd budget (`_active_budget`: everyone ≤ `live_full_upto` = 3, else ~`live_active_ratio`
(0.5) capped at `live_active_cap` = 6). This is level-of-detail rotation, **not** a behavior cap —
non-selected NPCs still live via the cheap code path (needs/emotions/agendas advance). It cut a
130-LLM-call tick in a packed tavern down to ~6.

## Data & tunables

- `_S["transit"]: {pid: {from, to, depart_gt, arrive_gt, path}}` — in-memory, rebuilt from `crof`
  on load (empty after restart → walkers resolve to their `crof` origin; at worst one lost
  in-flight animation). No schema migration.
- `_S["depart_postpone"]: {pid: slots}` — the one-slot postpone counter.
- PB (`session/config.py`): `transit_min_steps=3`, `churn_named_max=2`, `overflow_max_hops=2`,
  `depart_postpone_slots=1`, `step_min=1` (reused for `arrive_gt` and derived position).

## Invariants honored

- **Zero new LLM.** The only model call in the whole flow is the pre-existing `scene_digest`.
- **Query-shaped sim.** Transit position is derived on demand; the ledger is a pure function of
  `crof`; no new per-NPC background loop.
- **No mechanical gate.** Capacity is a world constraint (a room holds N → overflow to the next
  real venue), the postpone is a bounded world rule — minds are unchanged.
- **Code owns positions, LLM only narrates.** Diff, ledger, overflow, transit are all code; the
  player-visible line is the digest wording an authored event, never a fabricated one.

## Next

- **Mind-level «уйти».** Departures are driven by the routine (ring B), not by any mind primitive —
  modelling "the NPC left because bored" is a later phase (spec §2 non-goal).
- **Passive injury salience.** «раненый» fires on `hp < max_hp`, only ever set in combat today; a
  passive-injury flag would let sim-injured residents earn a named line (spec §10).
- **Fast-path churn lag.** Churn stashed during a `_world_tick_fast` build is consumed by the
  following `/live` turn — an accepted one-turn lag; a surfaced immediate short line on the move
  handler is an open question (spec §10).
- **`crosses`/ambush vs transit.** Intercept planning still reads the forecast path, not a
  walker's current transit node (spec §10, left unchanged).

Related: [citysim.md](citysim.md) (ring B) · [loop.md](loop.md) (fast/slow tick) ·
[locations.md](locations.md) (live scene, capacity) · [mind.md](mind.md) (ring A minds) ·
[geo.md](geo.md) (geo reads «в пути»)
