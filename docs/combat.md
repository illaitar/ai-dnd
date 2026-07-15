# Combat

`src/aidnd/combat` (engine) + `server/play/mechanics/combat.py` + `handlers/board.py` /
`handlers/dungeon.py` (loop). BG-lite on top of 5e. One engine for every fight: player duel, lair
delve, dungeon room, city incident, hired murder, NPC morning sortie. [Principle 3](README.md):
one unified Combatant, no special cases.

## Combatant — unified combat projection

`from_monster` (bestiary) / `from_npc` / `from_pc`: hp/ac/speed/to-hit/damage dice+type/resistances/
immunities/CR/statuses/range. Bestiary — `content/bestiary.json`: SRD stat blocks with variations
(data, not code). **Gear is resolved through the item derivation graph** ([items.md](items.md)): a
combatant's weapon/armour name resolves to a graph node, and its derived острота → attack bonus,
best armour piece's derived defense → AC, and a weapon's elemental attributes (горючесть/мороз/…) →
typed on-hit payloads (`_weapon_elements`, `_npc_gear_bonus`). Unresolved gear contributes 0 — a
dual-path that leaves legacy items unchanged.

## Encounter (engine.py)

Grid with obstacles · initiative d20+dex · turn = movement (BFS, 8 directions, blocked by
obstacles/occupied cells) + one action (attack / dodge / flee / end). Attack d20+to-hit vs AC
(dodge or shooting-in-melee = disadvantage), damage dice+bonus, nat-20 crit doubles the dice, nat-1
auto-miss; resist halves, immune zeroes — per damage type AND per elemental payload. **Ranged**
"like in BG3": bows/crossbows, disadvantage adjacent, AI kites to keep distance. **Statuses**
bound/asleep/afraid fade at end of the bearer's turn; a landed hit wakes a sleeper; afraid units kite
and don't attack. **Morale**: a weak monster (CR<2) below 30% hp checks and flees to the map edge.
Round = 5 s of game time (world stays static at minute scale); combat over `MAX_ROUNDS`=40 → draw.

## Auto-resolve (auto.py)

Fights without the player run through the SAME engine to completion (`resolve`): NPC morning lair
clears, hired blood-deals, board contracts executed off-screen. Enemy selection — `encounters.py` by
CR + environment; `dungeon.py` — lair waves.

## Entry points — everything is a delve

`POST /delve` (`handlers/board.py`) is the single gate into a fight:
- **Lair** → `delve_enter` builds a real dungeon ([dungeons.md](dungeons.md)); if the player isn't on
  a contract the guild gates on rank/badge at the site; **if the job was untaken it is auto-taken**
  on delve (`_take_incident`).
- **City incident** (`inc|…`) → `incident_delve` — a small dungeon populated with REAL townsfolk
  (chief in the goal room, captive in a stash); resolving the goal closes the incident and pays.
- Dungeon traversal (`dungeon_move` / `dungeon_loot` / `dungeon_exit`) walks rooms with fog-of-war,
  telegraphed traps, wanderers (time pressure), and per-room `Encounter`s from the room's shape; the
  boss sits on the lair perimeter (guild credit / cleared flag / trophy loot).

`combat_act` runs the player's action, then spins AI (and spawns waves) until the player's turn or the
fight ends. An **errored action returns early WITHOUT ending the turn** (unknown action, out of range,
already acted) — the turn is not burned. `combat_state` exposes the live view.

## Lairs, guild & the world around combat

- **Lairs** ring the city, deterministic from bestiary data (CR rising with distance); clearance =
  world flag + coin/item loot + guild reward + merchant restock ([quests.md](quests.md)).
- **Guild**: coin/rank ladder (Медь→Золото), a badge is a real credential item (rank/owner in flags,
  survives theft); using someone else's badge triggers a steward insight check; a black mark blocks
  work until a fine is paid; promotion by closed-contract count, credit only under your OWN badge.
- **City duels**: death is REAL — the corpse is looted, coins move to the victor, witnesses remember,
  and a killing with witnesses stacks wanted points → manhunt (surrender pays a vira, or flee on a
  Dex check into a fresh guard fight).
- **Magic in combat**: circle law with mechanics (dice/aoe/status) — [magic.md](magic.md); combat or
  dark spellcasting before townsfolk is taboo → bounty.
- **NPC delves** (`_npc_delves`): brave idle NPCs pair off, take the top board contract, and
  auto-resolve it each morning — the board empties and the world lives without the player.

## Player death — permadeath (roguelike, intended)

Death (duel, lair, dungeon room, trap) = **full world reset**: the player's world record is destroyed
and the session dropped; the next visit to `/play` builds a new city from scratch (dev world advances
its seed). This is a deliberate roguelike stake, confirmed current. Fleeing a fight is a legitimate
escape (hp persists; rest restores it — [loop.md](loop.md)); losing without dying only costs coins.

## Next

- Ranged magic/spell tactics deeper into the AI; companions/party hiring (decided: none for now).
- Richer dungeon interiors from the battlemap generator per room archetype.

Related: [quests.md](quests.md) (guild/lairs/incidents) · [dungeons.md](dungeons.md) ·
[items.md](items.md) (gear/loot through the graph) · [magic.md](magic.md)
