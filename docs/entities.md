# Data Entities

What EXISTS in the world and where it lives. Two storage layers — a hard rule
([principle 8](README.md)): **content** (pools, forged offline, in git) and **state**
(runtime worlds, never committed).

## Databases

**`data/worlds.db`** — POOLS (git, ~7 MB). Runtime tables in it are empty and must remain empty.

| table | what | volume |
|---|---|---|
| `people` | NPC bank: `mech` (traits/abilities/hp/**race**) + `persona` (origin/voice/quirks/secret/values) + `portraits` (4 emotions) | 1354 (portraits ~500) |
| `building_pool` | building factsheets: kind `key` (significant, by type-hint) / `res` (residential) / `city_name` | 599 + 100 names |
| `item_pool` | seed-templates for world items (rarity weights) | data |

**`data/live.db`** — RUNTIME (gitignored). `user_worlds` (user→world_id, seed) ·
`buildings` (dealt key buildings) · `placements` (npc→node/house/job — `crof`, the ring-B
positions, self-heal on generator changes) · `items` + `inventory`
(holders `pc` / `<npc>` / `cont:<id>`) · `purse` (purses) · `pc_state` / `npc_state`
(state blobs; `pc_state` carries **`gt`**—the game clock is write-through, so a restart never
rewinds time) · `contracts` · `journal` (the player Хроника) · `flags` (universal world key-value:
`grim|<hash>`, `crimes|pc`, `dead|<pid>`, `cleared|<lair>`, `seen|<bid>` (a building's interior
learned), `jmet|<pid>` (an NPC actually met—gates name vs. descriptor), `coffer|<npc>`,
`journal_purged`, LLM counters…). **Transit walkers** (`_S["transit"]`) are ephemeral scene rows,
NOT persisted.

Service DB (Postgres, [service.md](service.md)): users, sessions, invite codes.
It's about accounts, not the world.

## World

`world_id` + `seed` per user. From seed, the city graph grows deterministically
([worldgen.md](worldgen.md)); key buildings and residents are dealt from pools; city name is from a name pool.
Hero death = **world destruction** (permadeath: record is wiped, next visit — new city). Game time `gt`
(minutes) moves only by player actions at costs from `PB`; combat lives on its own scale (round = 5 sec).

## Person (NPC and player — one entity)

Core — `mind.NpcState` ([mind.md](mind.md)): `config` (immutable: traits ×11, abilities ×6,
role, hp, **race**) + position + FSM mode + needs ×7 + emotions ×5 (anger/fear/joy/distress/**disgust**,
with addressee) + relationships (trust/affinity/fear per person) + memory (`MemoryStore`) +
routine-plan + agendas. On top — `persona` from pool (voice/quirks/aspirations/secret) and portraits.
Player — same `NpcState` + purse/bag/mana/exhaustion/glyphs; special branches — UI only. The player is
never auto-seeded a relationship from mere co-presence—stays a stranger until real interaction ([mind.md](mind.md)).
Acquaintance — graph of 'who knows whom' (`jmet|<pid>`): an unmet NPC renders by DESCRIPTOR
(«мужчина со шрамом») via `_display`, name only after meeting; a stranger is depersonalized until introduced.

## Building

Factsheet from pool: type/floor/age/condition/features/services + `sub_rooms` (mini-graph of rooms —
for now one space) + `containers` (containers with contents; key — with owner). Entry/exit —
`inside` state; fog of war — 'arrived or learned from people'. Room zones and streets,
item-objects in them, runtime scenes — [locations.md](locations.md).

## Item

Factsheet: `surface` (what's visible — MAY LIE) + `hidden` (truth behind inspection gate) +
observer knowledge (`known`). Craftsmanship quality ≠ rarity (two axes); `unique` from pool
doesn't respawn. Materials — items themselves, craft — path through transition graph. Coins and keys —
real items. Details: [items.md](items.md).

## Contract

Delegated NPC need: a chain of steps-**predicates over the real world**
(`bring/deliver/visit/befriend/dead` + guild `clear` + `done_any`—any-of predicate), born from an
agenda, reward is real (purse coins or poor man's item), completion — fact of the world. A contract
also carries **`bid`/`node`/`patron`** so incidents can pin it to a building, place and issuer.
[quests.md](quests.md).

## Journal row (Хроника)

The player's chronicle in live.db, one row per beat: `kind=quest` · `prov=beat` · `refs=[cid]`
(the contract id it bridges). **Quest-only now**—no longer a firehose of every deed; a beat is written
only when a real quest milestone advances (honest Milestone bridge, [quests.md](quests.md)).
`journal_purged` flag clears it on world reset.

## Circle Law (magic)

Law manifested by LLM from circle drawing and clamped by budget; cache — grimoire-per-world
(`flags: grim|<canonical hash of drawing>`). [magic.md](magic.md).

## Knowledge and Memory

Person's memory — list of memories (importance/freshness/type: observation/heard/note/…),
retrieval recency·importance·relevance (+optional LLM-rerank). Gossip spreads facts between NPCs.
Map fog and item `known` — player knowledge. Plot truth is hidden from the player
([plot.md](plot.md)).

## Further (approved, not implemented)

- ✔ **Deed** v1 (2026-07-06): append-only journal `deeds(gt, actor, verb, object,
  place, witnesses, status, data)` in live.db (`engine/deeds.py`). Written: scene thefts (with
  witnesses), PROMISES (promise-tool of mind: 'give word' with what/when/where, deadline clamp
  by phases, place matches real city points). Consumers: scene gossip (town_talk in 'what the town
  talks about'), reminder 'YOU GAVE YOUR WORD' in debtor's prompt, routine leads BOTH sides to
  meeting place in time (society-place 'appointment'), resolve done/broken moves trust and memory
  of both sides. FURTHER: guard-investigators by deeds, contract predicates, chronicle-UI, street salience.
- **Typed Session** instead of dict-blob `_S` ([structure.md](structure.md)).
- Parchment-mask of unexplored areas in geom; hero stat growth.

Related: [loop.md](loop.md) · [mind.md](mind.md) · [worldgen.md](worldgen.md)
