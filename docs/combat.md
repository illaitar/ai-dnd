# Combat

`src/aidnd/combat` — BG-lite on top of 5e. One engine for all combat: player, city duel,
NPC sortie without player. [Principle 3](README.md): unified Combatant, no special cases.

## Combatant — unified combat projection

`from_monster` (bestiary) / `from_npc` (its mechanics + best weapon) / `from_pc` (hero +
weapon from bag): hp/ac/speed/to-hit/damage dice/type/resistances/immunities/CR/statuses.
Bestiary — `content/bestiary.json`: 322 stat blocks from SRD with variations (data, not code).

## Encounter (engine.py)

Grid with obstacles · initiative d20+dex · turn = movement (BFS, 8 directions) + action
(attack/defend/flee/maneuver) · crits/resistances/immunities · morale (flee when broken) ·
**ranged combat** "like in BG3": bows/crossbows, disadvantage at close range, AI kites. Round = **5 seconds**
of game time; world at minute scale is static. Combat log — line by line, UI — full-screen
overlay with grid.

## Auto-resolve (auto.py)

Combats without the player run through the same engine to completion: morning NPC lair clearances,
execution of board clear contracts. Enemy selection — `encounters.py` by CR + environment;
`dungeon.py` — lair waves.

## World around combat

- **5 lairs** in open terrain around the city; clearance = world flag + loot + guild
  treasury ([quests.md](quests.md)).
- City duels: death is REAL — corpse is looted, witnesses remember, guards search
  (manhunt: wanted points, penalty/jail — PB table).
- Magic in combat: circle law with mechanics (dice/aoe/status) — [magic.md](magic.md); combat
  spellcasting in front of witnesses = taboo (wanted).

## Player Death

**PERMADEATH**: death = destruction of the player's world (record is erased; next session —
new city from scratch). Fleeing from combat — legitimate escape. Player hp persists; rest
restores it ([loop.md](loop.md) rest).

## Next

- Ranged magic/spells in tactics; companions/party hiring (decided: none for now).
- Procedural dungeon interiors: bring up the old battlemap generator (archetype + cellular automaton)
  as a room generator for guild sorties.

Related: [quests.md](quests.md) (guild/lairs) · [items.md](items.md) (weapons/loot) ·
[magic.md](magic.md)
