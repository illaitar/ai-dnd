# NPC work & idle life — design spec (Workstream A)

**Status:** approved design, ready for implementation plan. Date: 2026-07-10.
**Source:** live playtest analysis (tavern + smithy) + 4 root-cause traces, this session.
**Relates to / builds:** [sound-attention.md](../../sound-attention.md) Pillar 2 Increment 6 ("keep
working" duty — this spec builds it); [mind.md](../../mind.md) (utility core); [locations.md](../../locations.md)
(zones, afford-objects, furnisher).

## Problem (from the transcripts)

Driving a live session through DeepSeek, NPCs never do venue-appropriate work and idle behaviour is
monotonous:
- In a **smithy** (кузница «Железный зуб»), NPCs drank leftover ale, ate grease, and pickpocketed —
  **nobody smithed**. Same generic tavern actions everywhere.
- The default idle action, everywhere, is **"grab a mug, take a gulp,"** repeated tick after tick.

## Root cause (grounded in code)

1. **Work is a place, not an action.** A worker is only *positioned* at a post zone
   (`world.py` `workers` set, `zones.py:66-71` holds them there), but on-shift status **never reaches
   the mind's goal set** — `NpcState` (`model.py:72-74`) has no work/duty field. The "keep working"
   duty is designed but unbuilt ([sound-attention.md](../../sound-attention.md) Increment 6).
2. **The `purpose` need is structurally the weakest.** `needs.py:41` grows `purpose` at 0.022 vs
   `hunger` 0.055; `_u_need` (`value.py:345-357`) pays `need.level`, so `use(еда/эль)`→hunger almost
   always out-scores `use(горн)`→purpose. `open_hours.py` exists but no NPC-mind consumer reads it.
3. **Work zones lack guaranteed work affordances.** The furnisher assigns afford via LLM (`furnish.py`
   only *hints* "верстак/орудия→purpose"); the live builder keeps only the **max-afford need per object**
   (`world.py:294-308`), so a hot forge reads as `comfort` and loses `purpose`. Smithy zones get
   furnished with consumable clutter (ale, food) → hunger/comfort `use` targets.
4. **Idle = drink because it's the only above-floor drive.** The sole idle alternative is
   `idle_floor = 0.05` for `wait`/`move` (`value.py:130-131`, `act.py:74-78`). Every other action needs
   a goal, and the only standing goal for a content NPC is "satisfy a need," whose nearest realization
   is a hardcoded `"кружка эля у очага"` (`world.py:218-226`).

## Design decisions (locked with the user)

- **Balanced work-pull:** an on-shift worker sticks to work against *unimportant* stimuli (a random
  stranger entering) but real ones still pull them off — the player addressing them, a salient event
  (drawn steel, a fight). "The keeper nods and keeps pouring; the bored regular greets you."
- **Rich idle variety:** idle NPCs get a menu of small, character/zone-appropriate actions (sharpen a
  blade, tend the fire, people-watch, pray, eavesdrop, count coins, mend), not just a satiety patch.
- **Mechanism = a lift, not a new goal type:** reuse the proven `venue_social` lift machinery (which
  made regulars talk), applied to `purpose` for on-shift workers. No new decision path.
- **No mechanical gates:** every change *models a missing world piece* (work-as-action, work
  affordances, idle repertoire, satiety), never caps behaviour ([principle 6](../../README.md)).

## Architecture — four units

### Unit 1 — On-shift signal (world → mind)
Add `NpcState.on_shift: bool` beside `venue_social` (`model.py:72-74`). Set it in `_live_build` where
`venue_social`/`workers` are already computed (`world.py:333-336`): an NPC is on-shift when
`people[pid].work == bid` **and** `open_hours.is_open(building_kind, hour)` (the function exists and is
currently unused by the mind). Pure world fact; no decision logic here.
- *Interface:* `NpcState.on_shift` read by `goals.py`. *Depends on:* `open_hours.is_open`, `workers`.

### Unit 2 — The "keep working" duty (mind)
Mirror the `venue_social` lift (`world.py:333-335` set → `goals.py:104-106` read, `PB["leisure_social_lift"]`):
add `PB["workplace_purpose_lift"]`, and in `goals.py` `propose_goals`, when `state.on_shift`, lift the
`purpose` need's goal value so it competes with hunger, and tag the resulting work plan with high
**engagement/importance** (`plan.importance`, already used for interruption-resistance) so low-salience
stimuli don't override it. Balanced pull falls out for free: the duty out-scores a stranger's low-novelty
entry, but a salient event (impulse 3.5) / answer-debt (4.0) / direct address still wins in the arbiter.
- *Interface:* consumes `on_shift`, emits a high-value `purpose` goal + importance. *Depends on:* Unit 3
  (a `purpose`-affording object to `use`), the existing `_u_need` handler.

### Unit 3 — Something to work at (worldgen + live builder)
Guarantee a `purpose`-affording object at post zones so the duty has a `use`-target:
- **Furnish time:** in `furnish.py` `_norm_objects` (`:170-190`), deterministically stamp a baseline
  `{purpose: …}` afford on the **post/workshop anchor** object (forge/anvil/counter) when the zone carries
  a `post` (`zones.json` кузница workshop `post: кузнец`, `:314-318`). Idempotent; run as an afford-only
  top-up over the existing pool (no full re-furnish).
- **Live builder:** fix the max-afford collapse (`world.py:294-308`) so a post object **retains
  `purpose`** even if another need scores higher (a hot forge that is both `comfort` and `purpose` should
  surface `purpose` for its worker).
- *Optional (customers):* stamp a `novelty`-affording `wares` object on shop counter/shelf zones so a
  curious visitor's `need:novelty` realizes as `use(товар)` ("examine the goods") — gives shops ambient
  customers. Flagged optional; can defer.

### Unit 4 — Idle repertoire + satiety (mind)
- **Idle repertoire:** add a small pool of low-value idle actions above `idle_floor`, selected by
  `role`/persona/zone-kind, each a distinct payoff below a real need — e.g. `tend`, `sharpen`, `watch`,
  `pray`, `eavesdrop`, `tally`, `mend`. Implemented as lightweight `use`-like actions (or a new low-tier
  `idle` action set) enumerated in `act.py`/`goals.py`, so a content NPC has 4–5 competing idle drives.
  Flavour strings vary by role/zone (retire the single hardcoded `"кружка эля у очага"` in `world.py:218-226`).
- **Satiety:** damp the payoff of `use`-ing the same item repeatedly, reusing the "beaten topic" dedup
  pattern (`world.py:802-808`) — track recent `use` targets per NPC and reduce `_u_need` payoff for a
  just-consumed need, so nobody tops up a barely-thirsty mug every tick.
- *Interface:* extends the action enumeration + `_u_need`. *Depends on:* nothing outside the mind.

## Data flow

```
_live_build: workers + open_hours.is_open → NpcState.on_shift        (Unit 1)
propose_goals: on_shift → purpose lift + work-plan importance         (Unit 2)
value: _u_need(use forge) pays the lifted purpose; satiety damps repeats (Unit 2/4)
worldgen: post anchor guaranteed to afford purpose; wares afford novelty (Unit 3)
act: idle repertoire gives varied low-tier actions when no need is hot   (Unit 4)
```

## Testing

- **Pure unit tests:** on-shift detection (work==bid & open); `workplace_purpose_lift` makes a `use(forge)`
  goal out-score `use(ale)` for an on-shift smith; satiety damps a repeated `use`; furnisher afford-stamp
  puts `purpose` on a post anchor; live-builder retains `purpose` on a post object.
- **Emergence guard:** `tests/mind` + `tests/society` stay green (modulator neutrality, emergence).
- **Live playtest (before/after):** re-run the tavern + smithy driver; assert (a) the smith `use`s the
  forge / the keeper tends bar, (b) idle-action variety up and "grab a mug" frequency down, (c) balanced
  pull — a stranger entering doesn't pull the on-shift worker off, but addressing him does.

## Risks

- **Mind-core regression:** Units 2 & 4 touch `goals.py`/`value.py`/`act.py`; the full suite + emergence
  tests must stay green.
- **Tuning:** `workplace_purpose_lift`, idle-action payoffs, and satiety strength need live-LLM tuning
  (numbers land in `PB`, not code).
- **Furnisher top-up:** Unit 3 writes afford onto pooled objects — must be an idempotent afford-only pass
  (not a full re-furnish that would rewrite `worlds.db`); scope it to post anchors + shop wares.

## Increments (each green → commit → deploy)

1. **On-shift + keep-working duty** (Units 1–2) with a guaranteed forge affordance shim for the test
   building, unit-tested. *First visible win: workers work.*
2. **Work affordances across the pool** (Unit 3 furnisher top-up + live-builder retain-purpose).
3. **Idle repertoire + satiety** (Unit 4).
4. *(optional)* **Shop customers** (Unit 3 wares afford).
