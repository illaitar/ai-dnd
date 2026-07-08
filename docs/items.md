# Items

`src/aidnd/items`. An item is not a loot string, but a **factsheet with a hidden layer** + observer
knowledge. Coins and keys are also real items ([principle 9](README.md)).

## Factsheet: surface / hidden / known

- **surface** — what's visible: name, material, weight, `apparent_worth` — CAN LIE.
- **hidden** — truth behind the gate: `{prop, value, fact, gate {via, dc, req}, mods}`.
  Gates `via`: glance/handle/**appraise**/lore/**craft_eye**/tool/context/use/**expert**
  (expert-NPC inspection). Revelation is written to `known` of the observer — knowledge is individual.
- **Mod/Gate/Capability**: modifiers affect price/stats upon revelation; inspector capability
  = abilities + role competencies (blacksmith sees metal, herbalist sees poisons).

## Two axes of value

- **Craftsmanship quality**: crude/plain/fine/exquisite → damage die in combat, price.
- **Rarity** (separate axis!): common/rare/epic/**unique** — weight in the world pool;
  `unique` is marked after pickup and NO LONGER RESPAWNS from the pool.

## Holders: every item has its place

`inventory(world, item, holder)` — one table for all slots in the world: `pc` · `<pid>` (NPC
pocket) · `cont:<bid>:<name>` (container) · `zone:<bid>/<zid>` (**zone fixtures**) · `used`
(spent). Transfer = `inv_move` — theft/loot/purchase/gift/pickup all use one mechanism.

**Fixture materialization** (2026-07-06): pool zone objects → real items in live.db
LAZILY on first entry to building; idempotent (id from seed + `INSERT OR IGNORE` on world key)
— taken items do NOT return to place. Scene reads live zone stock (`_zone_stock`).
Player picks loose items from their zone ("ITEMS NEARBY" in arbiter context); with establishment
employee present — witnesses via `_witness_crime`, stealthily — Dexterity check; `fixed` items cannot be taken.
NPC pickup from zone ground — also real `inv_move` (monitored by ground diff).

## World item pool

`item_pool` per world: seed templates (data) + everything forged by the game (`made:<name>` — craft/trophy
added to pool). Spawn: container loot, NPC pockets (materialization on demand —
corpse/theft/contract), events (caravan `caravan_chance`, merchant restock after clearing).

## Forging — item_smith [LLM]

`LLMSmith.forge(ItemCtx{kind, name_hint, source, quality_band, region})` → factsheet with
hidden nature ("looks like X, actually Y"); tabular skeleton of quality/price/DC — code.
Lazy forging `_forge` — cache by seed (same world string = one item).

## Crafting via material graph

Materials are themselves items; transition graph is a data table (`content/`, gen_materials).
Crafting = **path through graph with gates**: location (workshop with station: anvil/forge/workbench/
cauldron/tannery — by building keywords), skill (unfamiliar craft → Int roll vs
`PB[craft_skill_dc]`), time (sum of edges), leaf-materials consumed from bag. Result —
own forging, enters world pool. Repair/commission — commission/repair (inventory-handler).

## Next

- Mastery and durability (slice 2 of items).
- More stations/recipes from data; rare spawns from new events.

Related: [entities.md](entities.md) · [worldgen.md](worldgen.md) (seed pool) ·
[combat.md](combat.md) (weapons) · [quests.md](quests.md) (bring/deliver targets)
