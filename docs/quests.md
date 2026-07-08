# Quests: contracts, board, guild

`server/play/mechanics/contracts.py` + board-handler. A quest is NOT a script: **delegated
NPC need**, a want-predicate over real world state ([principle 9](README.md)).
Completion — by world fact, no matter HOW achieved.

## Contract

Birth: NPC agenda ([mind.md](mind.md)) → mechanic collects REAL candidates (contents of other
buildings' containers, other people's valuables, city locations) → LLM in giver's character
chooses a task and formulates a request (`pitch`) → code validates each step (the goal must
exist literally).

- **Step types**: `bring` (acquire thing) · `deliver` (deliver OWN thing to person) · `visit`
  (go-look) · `befriend` (win over person) · `dead` (only REAL enemy of giver — affinity < threshold;
  dark — if nature permits).
- **Multi-stage**: chain of 2-3 steps AND-sequence (trees — later).
- **Real reward**: coins from giver's wallet; poor person pays with thing (best of their own).
- Personal request in conversation: once per person (flag), won't offer to obvious enemy.
- Completion: `give`/world fact; contract persists (`contracts` in live.db).

## Board of Notices

Post on square (its own graph point). Ad cap (PB `board_max_ads`), lifecycle:
NPCs post from agendas, **NPC passersby take and close orders themselves** (probability
`board_npc_fulfill`, execution — auto-resolve/facts), board news feed.

## Adventurers' Guild

Building + till + clear-orders by CR on 5 lairs ([combat.md](combat.md)).

- **5 ranks**, progressive; rank = **credentials-ITEM** (token).
- Foreign token WORKS, but guild checks lie: Insight vs Deception;
  fail = confiscation + blacklist.
- NPC parties go on sorties via same combat engine (enhanced — win ~65%);
  morning clears return lairs' "life" to economy.

## Next

- Step trees (now AND-chains); quests-hooks from street events.
- Guild sends beyond city into procedural interiors ([combat.md](combat.md) "next").
- Plot tasks over same mechanism ([plot.md](plot.md)).

Related: [mind.md](mind.md) (agendas) · [items.md](items.md) (bring/deliver targets) ·
[entities.md](entities.md) (contracts in DB)
