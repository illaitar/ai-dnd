# The item derivation graph — design spec

**Status:** approved design pending user review of this doc. Date: 2026-07-11.
**Supersedes:** the "catalog = offline LLM re-forge of ~10k names" approach sketched in
[2026-07-10-item-attribute-graph-design.md](2026-07-10-item-attribute-graph-design.md) §U5 / phase 4.
That is replaced by a **hand-authored derivation graph** (~100 canonical nodes) plus **world content
regenerated from the graph** — no per-item LLM generation.
**Builds on (shipped):** Phase 1 (`ATTRS`, `attrgraph.json`, `compose`, `derive_effects`) and Phase 2
(surface/true deception, inspection reveals groups, `view()`), both on prod.

## Problem

The world's item names are ~10k near-unique free-text strings (SEED_POOL 24, NPC gear ~1514, décor
~8495). Forging a factsheet for each via LLM is expensive, inconsistent, and never converges. But the
underlying *reality* is small: a few dozen materials and a finite tree of things made from them.
`materials.json` already encodes the skeleton of that tree (`руда → слиток → клинок`, `шкура → кожа →
доспех`) — but it's tiny (13 nodes), carries no attributes, and nothing derives along it.

## Design decision (locked with the user)

- **A single hand-authored derivation graph** is the backbone: ~30 base materials + the full
  production chains that make things from them (~100 nodes total). Items *are* nodes.
- **Full production chain** — every step (`руда`, `слиток`, `клинок`, `меч`) is a real, holdable,
  tradeable, craftable item. The graph is simultaneously the attribute model **and** the craft-recipe
  tree (`craft_path` walks the same edges).
- **World content is regenerated from the graph** — NPC gear, loot, and décor become node picks, not
  free-text. An instance = **canonical node (mechanics/attributes) + a flavor epithet (display
  name)**, so `«Зазубренный нож мясника»` = node `нож` + epithet, keeping charm without losing
  consistency.
- **Attributes propagate down the graph** and reuse the shipped `derive_effects` for the
  vector→effects step. Change iron once → every iron thing shifts.

## Architecture

### Node model (`itemgraph.json`, authored)

One node type; each node is **raw** or **derived**:

```
node = {
  id:       "стальной_клинок",
  name:     "стальной клинок",       # canonical display noun
  kind:     "weapon|armor|tool|trinket|consumable|material|component|valuable|misc",
  form:     "клинок",                # optional; gates effect expression (Phase 1)
  # raw leaf:
  base_attrs: {твёрдость: 20, вес: 60, прочность: 30},   # authored profile
  # OR derived:
  from:     ["железный_слиток"],     # input node ids (1+; multiple = assembly)
  process:  "ковка",                 # the edge's transform (see processes)
  # optional per-node overrides / craft gates:
  treatments: ["заточка"],           # extra attribute deltas (Phase 1 vocab)
  tier:     "raw|refined|component|finished",
  worth_hint: null,                  # usually derived; override for oddities
}
```

### Attribute propagation

```
node_attrs(id):                      # memoized
  raw     → base_attrs
  derived → combine( node_attrs(x) for x in from )     # per-attribute MAX across inputs
            |> apply process transform (processes[process] deltas)
            |> apply treatments (Phase-1 treatment deltas)
            |> form does NOT change attrs (it gates effects, per Phase-1 decision)
```

- **processes** (`itemgraph.json` `processes`) are the derivation edges' attribute transforms —
  `плавка → +твёрдость −вес(slag)`, `легирование → +твёрдость +прочность`, `ковка → (enables the
  blade to hold острота)`, `дубление → +гибкость +прочность`, `прядение/ткачество`, `сборка →
  (merge, no delta)`. This is the same shape as Phase-1 treatments, promoted to graph edges.
- **forms** and **effect rules** stay exactly as Phase 1: `derive_effects(item)` turns the final
  vector + form into attack/defense/worth/etc. A `меч` node's attack is **computed** by walking
  `руда → слиток → сталь → клинок (+рукоять)`, never authored.
- `compose(parts, quality)` (Phase 1) is the flat 1-level case; `node_attrs(id)` is the general
  recursive case. Both feed `derive_effects`.

### Node resolution

`node_lookup(name) -> node_id | None` — resolves a display name/alias to a node (for wiring existing
items). Since world content is regenerated *from* the graph, most items already carry their `node`
id; `node_lookup` is the bridge for anything that doesn't.

### Instance model

A world item instance = `{node: id, epithet: str, quality: crude|plain|fine|exquisite, condition,
attrs (materialized = node_attrs × quality, with surface/true for deception), known}`. `attrs` is
computed at materialization from `node_attrs(node) × quality`; deception (surface≠true) is applied
per-instance (a forged ring: node `перстень·золото` surface, node `перстень·латунь` true).

## The authored graph (scope of the pre-fill)

~30 materials (metals, woods, animal, plant/cloth, mineral, organic) + full chains:
metal arms (`руда→слиток→сталь→клинок`+`рукоять`→`нож/меч/топор`), leather armor
(`шкура→кожа→жилет/сапоги/пояс`), wood+string (`кряж→доска→древко/цевьё`; `цевьё+тетива→лук`), cloth
(`лён→нить→полотно→рубаха/плащ`), brew&bake (`травы→зелье`; `зерно→мука→хлеб`), precious
(`слиток+самоцвет→перстень/амулет`). ~100 nodes total. Numbers are authored data, tuned later.

## World integration (regeneration)

- **peoplegen** — NPC gear is picked from graph nodes by role + tier (a кузнец holds a `молот`/`нож`,
  a стражник a `меч`+`доспех`), dressed with a flavor epithet; replaces the free-text `gear` names.
- **loot / SEED_POOL** — pools reference graph nodes (with rarity/tier); `_pool_draw` materializes
  node attrs.
- **furnish / décor** — zone objects reference graph nodes; épithets keep flavor.
- **materialization paths** (`_pool_draw`, `_put_item`, `_materialize_npc`, `_materialize_zones`)
  resolve `node` → `node_attrs × quality` and attach the vector; unmatched legacy items fall back to
  their existing factsheet (dual-path during migration).

## Relationship to `materials.json` / the old craft path

`itemgraph.json` **is** the evolved `materials.json` (superset: base_attrs + processes + item nodes).
`craft_path` re-points to it in subsystem 3 (crafting = walking these edges). The rich `craft()`
engine (NPC commission) is subsumed by graph crafting later. Increment 1 adds the new graph +
traversal WITHOUT breaking `materials.json`/`_do_craft` (they stay until subsystem 3 migrates them).

## Increment sequence (each its own plan)

1. **Graph + engine** — author `itemgraph.json` (materials + full chains) + `node_attrs` traversal +
   `node_lookup`; reuse `compose`/`derive_effects`. Pure, unit-tested. No world change.
2. **Materialization references nodes** — instances carry `node`+`epithet`; the 4 materialization
   paths attach `node_attrs × quality` (dual-path); inspection/worth (Phase 2) light up.
3. **Regenerate worldgen from the graph** — peoplegen gear, loot pools, furnish décor pick nodes +
   epithets; re-run gen; commit `worlds.db`.
4. **Consumers + craft** — combat/trade read `derive_effects`; `PB` override; crafting walks the
   graph (subsystem 3 convergence).

## Global constraints

- **No hardcoded gameplay numbers in play-layer code** — attribute profiles, process deltas, and node
  definitions live in `itemgraph.json` (data); effect coefficients stay in `attrs.py` `DEFAULT_RULES`.
- **No LLM at materialization/runtime** — node attributes are computed by deterministic traversal;
  epithets are authored offline (worldgen). Crafting's bespoke-tier LLM extension (subsystem 3) is the
  only LLM item path, and it errors honestly if no model.
- **Full suite green** before each ship: `uv run pytest /Users/nik/Desktop/dnd-ai/tests` (abs path).

## Testing

- `node_attrs`: a `меч` computes a plausible vector down its chain; `плавка` raises `твёрдость`;
  changing iron's `base_attrs` propagates to every downstream node; an assembly merges inputs (max
  per attr); cycles/missing inputs error clearly; memoization returns stable values.
- Effects: a graph-derived `меч` yields an attack mod via `derive_effects`; a `лук` yields ranged; a
  `перстень·золото` yields worth/appearance; a forged instance (surface `золото`, true `латунь`)
  deflates on appraisal (reuses Phase-2 deception).
- Integration (later increments): a materialized NPC weapon reads its attack from `node_attrs`;
  regenerated gear keeps a flavor epithet.

## Risks

- **Authoring effort & tuning.** ~100 nodes + ~30 material profiles + process deltas is real work;
  numbers will need a tuning pass. Mitigate: data-only, iterate; anchor a few known items with tests.
- **World regeneration churn.** Re-running peoplegen/furnish rewrites `worlds.db` gear/décor. Mitigate:
  keep epithets for flavor; do it as its own increment with before/after spot-checks; dual-path
  materialization so a half-migrated world still runs.
- **Two graphs during migration** (`materials.json` + `itemgraph.json`). Mitigate: increment 1 is
  additive; `materials.json` retires only when subsystem 3 re-points `craft_path`.
- **Variant explosion** (longsword vs saber). Mitigate: author canonical types first; variants become
  quality/size modifiers, not new nodes.
