# Craft / combat / trade on the derivation graph — design spec

**Status:** approved design pending user review. Date: 2026-07-11.
**Builds on (shipped):** the item derivation graph (`itemgraph.json` 241 mat / 8293 nodes, `graph.py`:
`node_attrs`/`combine`/`node_item`/`node_lookup`), Phase-1 attrs + `derive_effects`, Phase-2
inspection/deception. **Subsystems delivered here:** 2 (luck & inspiration) + 3 (emergent craft) + the
Phase-3 consumer conversion (combat/trade read `derive_effects`).

## Goal

Close the loop: **craft an item (a graph node → real attrs) → wield it (combat reads derived
attack/defense) → sell it (trade reads derived worth).** Crafted items are the first graph-attr items
in the live world, so this is the first *visible* payoff of the whole rework. Luck (earned karma) and
inspiration (a fleeting spark) move the craft roll.

## Global constraints

- **No hardcoded gameplay numbers in play-layer code** — every threshold/coefficient (spark base, band
  cutoffs, karma weights, inspiration duration/size, luck scale) lives in `PB` (`session/config.py`).
- **No LLM at runtime except the bespoke craft rung** — feasibility, base, modified, and combine() are
  deterministic; only a genuinely novel material/node calls the LLM (and errors honestly if no model).
- **Dual-path safety** — combat/trade read `derive_effects` **only** when the item has an attribute
  vector; legacy items (no `attrs`) keep their exact current behavior. No live item has attrs yet, so
  the running game is unchanged until the player crafts.
- **Full suite green** each increment: `uv run pytest /Users/nik/Desktop/dnd-ai/tests` (abs path).

## Unit A — Luck & inspiration (PC traits)

State in `pc_state` (like mana): `karma:int` (default 0), `insp:float` (default 0), `insp_gt:int`.

- **Karma** moved by **deed tags**. Crimes already flow through `_witness_crime` (`core.py:301`) — hook
  a negative karma delta there (weight-scaled). Add `_pc_karma_add(delta)` and tag **good deeds** where
  they happen: fulfilling a quest/contract (`_contract_on_give`), a gift/overpayment (trade `give`),
  sparing a foe (combat wrap-up), helping when asked. Deed weights in `PB` (`karma_crime`,
  `karma_gift`, `karma_quest`, `karma_mercy`, …).
- **Luck** = a smoothed read of karma: `_pc_luck() -> float` = `clamp(karma / PB["karma_per_luck"],
  -PB["luck_cap"], +PB["luck_cap"])`. Slow to move, bounded.
- **Inspiration** = fast/hidden/fleeting. `_pc_inspire(amount)` sets `insp = amount`, `insp_gt = gt`.
  `_pc_inspiration() -> float` returns `insp` decayed linearly to 0 over `PB["insp_minutes"]` since
  `insp_gt`. Set by the **arbiter flagging an unusual sighting**: in the freeform/tick path, when a
  `salient` event fires in the player's scene (we already compute salience — WS-C), or the arbiter tags
  the player's observation as novel, call `_pc_inspire(PB["insp_spark"])`. Hidden: not shown as a stat;
  surfaces only through better craft outcomes.
- Exposed to craft; loot/dice are later consumers (out of scope here).

## Unit B — Craft spark ladder (rework `_do_craft` onto the graph)

Replace the `materials.json`/`craft_path`/`_put_item(tier="fine")` body with a graph resolver:

1. **Resolve target + inputs.** `node_lookup(detail)` → target node; gather the bag items that match
   the target's `from` (or, for a free combination, the named held items). Feasibility: the player
   holds the inputs, and is at a station whose process matches (reuse the existing station gate).
2. **Roll the spark:** `spark = PB["craft_base"] + mastery + material + luck + inspiration + roll`
   where `mastery` = `_PC_CAP` ability/competency for the process, `material` = mean of the input
   nodes' relevant attrs (÷ a `PB` divisor), `luck` = `_pc_luck()`, `inspiration` = `_pc_inspiration()`,
   `roll` = seeded d-something. All weights in `PB`.
3. **Band → outcome** (cutoffs in `PB`): 
   - `waste` — consume the inputs, produce nothing (bad roll).
   - `flawed` — `node_item(target, "crude")` + a **hidden flaw**: surface `прочность` normal, true
     `прочность` low (a crack, revealed by `craft_eye`) — reuses the Phase-2 surface≠true deception.
   - `clean` — `node_item(target, "plain")`.
   - `modified` — `node_item(target, "fine"|"exquisite")` (quality from how far over the line).
   - `bespoke` — `combine(inputs, process)` for a deterministic novel result, **or** if truly novel,
     the LLM mints a new node/material appended to the graph; tiered by overshoot. The invention is
     added to `itemgraph` (in-memory + persisted) so it echoes onward.
4. **Apply:** consume inputs from the bag; `normalize` + save the result (with its `attrs`); place in
   the bag. A bad roll may waste **and** flaw per the downside rule.

The crafted item carries `attrs` → `derive_effects` gives it real stats/worth immediately.

## Unit C — Combat & trade read `derive_effects` (dual-path)

- **Combat** (`combat.py`): `_pc_combatant` / `_combatant_from_npc` — when the equipped weapon/armor has
  `attrs`, source the attack/defense bonus from `derive_effects(item)` (map the `attack`/`defense` mod
  amount into the combatant's damage/AC); else the current persona/legacy path. One seam: a helper
  `_weapon_bonus(item)` / `_armor_bonus(item)` that returns the derived amount or the legacy value.
- **Trade** (`trade.py`): already prices off `view()["worth"]`, which is derived for attr-items
  (Phase 2). Confirm `rarity_price` still layers on top; add attr-item coverage tests. Minimal change.

## Testing

- **A:** karma rises on a tagged good deed, falls on a crime; `_pc_luck` clamps and smooths;
  `_pc_inspiration` decays to 0 over `PB["insp_minutes"]`; an unusual sighting spikes it.
- **B:** the spark bands map correctly (low spark → waste/flaw; high spark + luck/inspiration → modified/
  bespoke); a flawed item has surface `прочность` > true (revealed by `craft_eye`); inputs are consumed;
  a novel `combine` yields the expected node; deterministic under a fixed seed.
- **C:** a graph weapon's derived `attack` raises PC combatant damage vs a legacy weapon of equal worth;
  a graph item's trade price tracks its derived worth; legacy items unchanged (byte-identical combat/
  trade for today's items).
- Live playtest: craft at a station with/without inspiration; wield the result; sell it.

## Increment sequence (each its own plan → SDD)

1. **Luck & inspiration** (Unit A) — karma scalar + deed tags + inspiration buff, `PB` tunables, tests.
2. **Craft spark ladder** (Unit B) — the graph resolver replacing `_do_craft`, consuming A.
3. **Combat + trade** (Unit C) — dual-path `derive_effects` reads.

## Risks

- **Combat balance.** Deriving weapon damage from attrs may shift fights. Mitigate: dual-path (only
  crafted/graph items affected now); tune the attack→damage mapping in `PB`; anchor with a test vs a
  legacy weapon.
- **Craft resolver ambiguity.** Free-text "make X" may not resolve to a node. Mitigate: `node_lookup`
  fuzzy match + a clear "can't tell what you're making" message (like today); the arbiter can help.
- **Bespoke graph-extension drift.** Runtime LLM node-minting could bloat/゚inconsistency. Mitigate:
  gate it to the top band only, validate the minted node through the same lint (`node_attrs` computes,
  refs resolve) before adding; reuse the wave merge's guards.
- **materials.json retirement.** `_do_craft` moving to `itemgraph` orphans `materials.json`/`craft_path`
  — leave them until nothing references them, then delete in a cleanup.
