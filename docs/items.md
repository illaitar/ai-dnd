# Items

`src/aidnd/items` (model + attribute graphs) and `server/play/mechanics/items.py` + `handlers/`
(loop). An item is not a loot string but a **factsheet in two layers of knowledge** — surface (visible,
may lie) + hidden (truth behind inspection gates) — sitting on top of an **intrinsic attribute vector**
that code derives everything else from. Coins and keys are also real items ([principle 9](README.md)).

## Factsheet: surface / hidden / known

- **surface** — what the eye reads: name, material, weight, quality, `apparent_worth` — CAN LIE.
- **hidden[]** — truths behind a gate: `{prop, value, fact, gate {via, dc, req}, mods}`. Props:
  `true_material · true_worth · forgery · provenance · poison · enchant · curse · flaw · compartment ·
  function`. Revelation is written to the **observer's** `known` set — knowledge is individual and
  asymmetric (a jeweller sees the sapphire you can't; a herbalist smells the poison).
- Gate `via`: glance · handle · appraise · lore · craft_eye · tool · context · use · expert
  (an NPC expert inspecting on your behalf).

## Attribute vector — the canonical centre

`ATTRS` (model.py) — 18 intrinsic physical/arcane properties, 0–100: острота, твёрдость, прочность,
вес, гибкость, краса, ценность, чара, мана, святость, скверна, теплостойкость, точность, горючесть,
взрывчатость, едкость, мороз, заряд. Each attribute is stored two-faced: `{surface, true}` (a scalar
means honest, surface == true). Everything an item *does* is **derived** from this vector — the LLM
authors none of it.

### The two derivation graphs (pure, deterministic, no LLM)

- **`attrs.py` + `attrgraph.json`** — `compose(parts, quality)`: an item's `parts`
  (`[{role, material, treatments}]`) → true vector. Strongest part wins per attribute (max),
  treatment deltas sum, quality-scaled (`crude .85 … exquisite 1.25`), clamped 0–100.
- **`graph.py` + `itemgraph.json`** — the **item derivation graph**: raw materials → processes →
  named item nodes. `node_attrs(id)` walks the chain up from raw materials (memoized, cycle-safe:
  max-combine inputs + process deltas + treatment deltas). `combine(ids, process)` resolves a
  **novel** combination with no authored node — deterministically, no LLM (стрела + заряд → an
  exploding arrow). `node_lookup(name)` bridges a display name/alias to a node id (exact → ci-exact →
  whole-token containment, longest wins; «Кривой нож» → «нож» but «Порог» ≠ «рог»).
- **`derive_effects(item, known)`** — the vector + `form` → `{mods, worth, durability}`, all banded:
  attack/defense (form-gated — the form supplies the weights), appearance (краса), poison (скверна,
  hidden), mana (focus forms or consumables), heal (святость, consumables only), elemental on-hit
  payloads (горючесть/взрывчатость/едкость/мороз/заряд on weapon forms), worth (weighted score),
  durability (прочность). Legacy items with no vector yield no derived mods — combat/trade unchanged.

### Attribute groups gate inspection

`ATTR_GROUPS` bundle the vector into **attr:phys · attr:value · attr:arcane**. An inspection reveals a
whole group's TRUE values at once (`inspect.py::_attr_reveal`): `craft_eye → phys`, `appraise → value`,
`lore → arcane`, `expert → all`. A relevant competency (metalwork/gems/trade/faith…) reveals the group
at a glance; otherwise appraise/lore fall to an Int/Wis roll vs DC 12; physical truth always needs the
trained hand (no roll bridges it). `view(item, known)` shows surface values until the group is
revealed, then true. Worth is known only once every worth-feeding group the item actually has is
revealed. **Honest-item floor**: the graph under-values basic goods, so a truthful item's shown worth
never drops below its authored `apparent_worth`; a forgery (surface≠true on a value attr) keeps the
derived number.

## Craftsmanship, rarity, masterwork & flaw

- **Quality** (crude/plain/fine/exquisite) scales the whole vector — damage, worth, durability.
- **Rarity** is a SEPARATE axis (common/rare/epic/unique): a price multiplier (`RARITY_PRICE`) and a
  pool spawn weight (`RARITY_WEIGHT`). `unique` is marked after it spawns and NEVER drops again.
- **Masterwork** (`_mw_attrs`) bumps the strongest attribute (surface+true).
- **Flaw** (`_flaw_attrs`) bakes a HIDDEN crack: surface прочность stays intact, true прочность is
  cut — visible only to a `craft_eye`, and a smith's repair mends it (`true` restored to `surface`).

## Holders: every item has its place

`inventory(world, item, holder)` — one table for every slot in the world: `pc` · `<pid>` (NPC pocket)
· `cont:<bid>:<name>` (container) · `zone:<bid>/<zid>` (fixture) · `used` (spent). Transfer = `inv_move`
— theft, loot, purchase, gift, pickup all ride one mechanism. Building décor and container contents
**materialize lazily** on first entry (`_materialize_zones`, `loot`); idempotent by seed, so taken
items never return. NPC inventory materializes by layer: `visible` (gear+keys, first touch) vs
`pockets` (goods/valuables/coins, on search/theft). `_graph_enrich` retro-fits a legacy item (looted,
NPC-gear, décor) with a graph node's attrs when its name resolves — so it gains real, inspectable,
combat/trade-live stats; unresolved names leave the item unchanged (dual-path). `_sane_name` coerces
dict-shaped pool entries (`{'item': …, 'cost': …}`) to a clean display name instead of leaking a repr.

## Freeform crafting — the spark ladder

Player `craft` (via `/act`, `_do_craft`) walks the derivation graph. Resolve the target node
(`node_lookup`), gather its direct inputs from the bag (a node may need N of the same), gate on station
(`_PROC_STATION` maps process → anvil/forge/bench/cauldron/tannery, matched to the building the player
stands in), then roll one **spark**:
`spark = craft_base + mastery(max dex/int) + material(mean input strength) + luck + inspiration + d20`
→ band: `waste` (inputs lost) / `crude` (+hidden flaw) / `plain` / `fine` / `exquisite` (masterwork).
Inputs are consumed ONLY after the new item exists (no robbery on a failed roll). No authored target →
`_do_combine`: 2+ held items named in the phrase (stem-prefix match, tolerates inflection) fuse under
an inferred process (`_COMBINE_KW`: привяжи/покрой/наполни/отрави/освяти/зачаруй…). Every crafted item
is forged with a real attribute vector and added to the world pool (`_pool_add_new`). `commission`
(NPC artisan crafts their `_ROLE_NODE`, always delivered) and `repair` reuse the same ladder/nodes.

## The honest-take rule

Mechanics decide every transfer; the narration arbiter only ever renders a **real** result. A `take`
that resolves no real target (item not materialized in the zone, or `item=null`) gets an honest refusal
— «Этого здесь нет» — never a phantom pickup. When the player names a specific thing that doesn't
stem-match what the parser resolved, the substitution is rejected and the take refuses rather than
grabbing the wrong object (`_stem_hits_name` guard in `handlers/freeform.py`).

## Trade

**Player ↔ merchant** (`handlers/trade.py`): `/offer` (appraise, name a price), `/sell`, `/wares`
(list stock + prices), `/buy`, `/askkey` (borrow a key, gated by affinity+trust vs greed/honesty).
A merchant appraises with THEIR eye (`_npc_sees` → `inspect(via=expert)`), so prices reflect asymmetric
knowledge. **Price grounding**: `_wares_price` is the single sell-price helper shared by `/wares` and
dialogue's `_price_line`, so a keeper's *spoken* prices are literally the numbers `/wares` charges —
the LLM voice wraps them in character but MUST NOT alter them (`narrator/voice.py`). Keys and personal
valuables are never for sale (those you steal).

**NPC ↔ NPC** (`mechanics/haggle.py` + `world.py::_npc_trade_step`): an emergent value corridor +
multi-tick haggle, all numbers code-owned. `deal_corridor` sets `[seller-minimum, buyer-maximum]` from
each side's money-demand (need + greed/ambition) and how much the buyer wants the good; `open_deal`
anchors seller at his max, buyer at his min; each tick both concede toward the midpoint by
trait-driven fractions (`concession`) until offers meet (`settle` at the mean), patience runs out
(`walk`), or a party/good leaves. Deals open from a mind's own `buy` action (the LLM's choice IS the
want signal) plus a light background hum from commercial agendas. The per-round offers are voiced as
**ephemeral scene speech** (tier-1 feed lines — not journaled); only the **settlement** is durable:
`settle` moves real coins + the item and lands in both parties' memories.

## Enchanting

An item's чара (arcane capacity) lets it hold a **bound circle-law** instead of casting it
([magic.md](magic.md)): `/enchant` reuses the cast pipeline, the item's чара caps the law's budget,
binding costs mana, and the law fires later on `/use` (`_activate_enchant`, deterministic, charges
decrement to zero). Consumables carry no enchant — their `on_use` heal/mana mods are derived from
святость/мана by `derive_effects` and applied on drink.

## Next

- Durability as an active axis (currently legacy `durability.py` + hidden-flaw path); wear from combat.
- More authored graph nodes/processes; rarer spawns from new events.
- PB-override seam for the effect-rule coefficients (currently code-owned constants in `attrs.py`).

Related: [entities.md](entities.md) · [worldgen.md](worldgen.md) (seed pool) ·
[combat.md](combat.md) (gear resolved through the graph) · [magic.md](magic.md) (enchanting) ·
[quests.md](quests.md) (bring/deliver targets)
