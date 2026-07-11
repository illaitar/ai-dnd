# Finishing the graph integration — design spec

**Status:** approved (decisions locked with the user). Date: 2026-07-11.
**Builds on:** the shipped craft/combat/trade convergence + regeneration (all items graph-backed).
Closes the three remaining edges. Suite 337 green on prod.

## Increment 1 — Commission on the graph + worth reconciliation + delete `craft.py`

**Goal:** the pay-an-NPC-to-craft path (`commission`) and `repair` stop using the old `craft()` engine
and use the derivation graph; then `craft.py` is deleted entirely, and the stored-vs-derived worth
divergence is reconciled.

- **`commission`** (`handlers/inventory.py`): map the artisan's role → a target graph node
  (`_ROLE_NODE = {кузнец: "нож", знахарка: "целебный отвар", сапожник: "сапоги",
  дубильщик: "кожаный жилет", охотник: "лук", оружейник: "меч", …}`). Roll the NPC's mastery
  (`_npc_cap(p)` ability + a seeded d20) → reuse `_craft_band` → forge via `_put_graph_item(node,
  quality, masterwork=…)`. Returns a real attribute-bearing item (with its derived worth).
- **`repair`** (`handlers/inventory.py`): graph-native. If the item's `прочность` has `true < surface`
  (a crafted flaw) → a smith restores `true = surface` (mends the crack); else if it has legacy
  `durability` → restore `current = max` (keep the old behaviour). Gate by NPC role, as now.
- **Delete `craft.py`** (`craft`, `repair`, `mastery`, `Recipe`, `ROLE_RECIPES`, `STATIONS`, …) once
  nothing imports it; remove its `__init__.py` exports and `_npc_cap`'s `ROLE_RECIPES` use.
- **Worth reconcile:** in `_graph_enrich`, after attaching attrs, set `it["worth"]` and
  `it["apparent_worth"]` to the reconciled worth (`max(derived, authored)` — the same floor `view`
  uses) so every non-trade reader (weapon-pick, gift, theft, reward, coins) agrees with trade.
- **Tests:** commission forges a graph item for a kнец/знахарка; repair mends a flaw; a legacy item
  with durability still restores; enriched item's stored worth == its view worth; `craft.py` gone,
  imports clean, full suite green.

## Increment 2 — NPC combat reads the graph (weapon + armor) + tune

**Goal:** an armed NPC fights with its real gear's derived stats, not just persona tier.

- **`_npc_weapon`** (`mechanics/combat.py`): resolve `gear["weapon"]["name"]` via `node_lookup` →
  `node_item(nid, quality).attrs` → derived `attack` amount → set `weapon["bonus"]` (the hook
  `from_npc` already reads). Quality from the persona tier (existing `_TIER_QUALITY`).
- **NPC armor → AC:** in `_combatant_from_npc`, resolve `gear["armor"]`/`garb` → derived `defense`
  (best single piece) → `combatant.ac += that`. Mirrors `_pc_combatant`.
- **Balance:** every armed NPC now hits +0..3 harder and armored ones are tougher. Add a `PB` HP/CR
  nudge if needed; **playtest a combat** (a graph-armed NPC vs the PC) and tune `PB` so fights stay
  fair. Dual-path: NPCs whose gear name doesn't resolve keep the current behaviour (bonus 0).
- **Tests:** an NPC with a resolvable weapon gets a derived `bonus`; armor raises its AC; an
  unresolvable-gear NPC is unchanged. Live combat playtest.

## Increment 3 — Bespoke craft: deterministic combine + LLM invention tier

**Goal:** the top of the craft ladder becomes real novelty — combine arbitrary things (deterministic),
and, rarely, invent something genuinely new (LLM).

- **Deterministic novel-combine** (primary): the arbiter parses a combine-intent ("привяжи заряд к
  стреле", "смажь клинок ядом", "соедини X и Y") → inputs (held items) + a joining process
  (`привязать`/`покрыть`/`наполнить`/`сборка`) → `combine_item(inputs, process)`. The spark roll still
  gates success/quality (waste/flaw/clean/…); form inherits from the primary input. The novel item
  joins the bag (and the pool as an ad-hoc entry). No LLM. Reuses the built `combine()`.
- **LLM invention tier** (rare): when the attempt can't be expressed by the graph vocabulary *and* the
  spark lands in the top band with high inspiration, an LLM smith proposes a NEW node/material
  (`{id, name, kind, form, from, process}` or a material with a banded profile), **validated through
  the same graph-lint** used by the wave generation (refs resolve, `node_attrs` computes, id disjoint),
  then added to `itemgraph` (in-memory + persisted) and forged. The only runtime-LLM item path; errors
  honestly if no model.
- **Tests:** a combine-intent yields the expected novel item (острота + взрыв → exploding); the spark
  still gates it (low roll → waste); the LLM-mint path validates + rejects a malformed node (stub
  smith in tests); a minted node round-trips through `node_attrs`. Live playtest of a novel combine.

## Global constraints

- No hardcoded gameplay numbers in play-layer code (tunables in `PB`).
- No LLM at runtime except the Increment-3 invention tier (validated + honest-error).
- Dual-path everywhere (unresolved names / legacy items unchanged).
- Full suite green before each ship; deploy via `/deploy`; Opus review per increment.

## Sequence & risk

**1 (cleanup, unblocks) → 2 (NPC combat, balance-sensitive) → 3 (bespoke, most novel/risky).**
Risks: Inc-2 balance (mitigate: playtest + `PB` tune); Inc-3 LLM-mint graph mutation (mitigate: lint
validation, gate to top band, reuse wave-merge guards); Inc-1 repair dual-path (legacy durability vs
graph flaw — cover both in tests).
