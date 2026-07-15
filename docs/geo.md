# Geo: NPC geographic knowledge

`server/play/engine/geo.py`. When the player asks «где …?» / «где купить X?» / «где дом Y?», the NPC
answers with a **geometry-true** direction he can trust: one mind-call decides whether he helps and
which place/person he names (bounded to what he could plausibly know), code computes the actual route
facts, and a share reveals the building on the map. Pure module, no stored state — everything is
derived per query from `_S` (city/people/placements) + citygraph + relationships. Fixes the live bug
where two townsfolk gave contradictory improvised directions to the same house. Ships as-built per
[the geo-knowledge spec](superpowers/specs/2026-07-13-npc-geo-knowledge-design.md).

## `known_places(pid)` — 6 source rules

The NPC's plausibly-known places; first rule to claim a bid wins, each entry tagged `why_known`:

1. **home** — his home node's building (`живу`).
2. **work** — his work building (`работаю`), carries a `goods` hint for «купить X».
3. **routine venues** — nearest tavern/temple/market to home by route (`хожу`, approximation of
   `worldsim._candidates`).
4. **town landmarks** — every tavern/temple/market + wells/guild/gates/mills (`все знают`).
5. **kin, friends & coworkers** — homes of surname-kin, friends (`aff > geo_friend_aff`), and
   same-work coworkers (`свои`).
6. **neighbors** — homes within `geo_neighbor_hops` graph hops of his home (`соседи`).

Arbitrary houses and hidden places are deliberately absent — referral covers those gaps.

## `direction_line(from_node, bid)` — one always-true sentence

A thin formatter over `City.route` (which already runs A*, heading, nearest-building, landmarks). It
computes nothing new — it renders three route facts into RU: **minutes** (steps × `step_min`, numeral
words 1–10 then round idioms like «минут двадцать») + **compass side** (8-wind → «к северу» …) +
**nearest landmark** («за рыночной площадью» for a square, «у колодца» for a point; + river/wall/
gate/bridge if the target sits at one). A disconnected target → the `FAR_LINE` constant («это на
другом конце города»), exported so callers (e.g. `incidents.py`) compare against it, not a literal.

## The router — ONE mind-call

`geo_answer(pid, text, from_node)` is the stable `say()` seam: `None` if not a geo question (say
runs unchanged), else a dict with a `geo_line` for the voice and an optional `reveal` to mark the map.
Its body is `route_geo_ask` — **one** `narrator` call (temp 0.2) that IS the mind: it decides BOTH
willingness AND which place/person, from persona + relationship (aff/trust/fear) + memories, bounded
to the code-provided place & acquaintance sets. **Willingness lives entirely in the prompt** — no
`PB` willingness key, no roll, no formula ([no mechanical gates](README.md)).

Code clamps the LLM's choice before anything is spoken: `bid` must match a known place (by id OR
exact name), `refer_pid` a real acquaintance — otherwise nulled. Four outcomes:

- **share** — a validated place → voice the immutable `direction_line`; **on share only**, mark the
  building on the map (`_mark_seen`). If the target bid equals the building the player is already
  standing in → «да ты уже здесь» (no fabricated route, no reveal).
- **refer** — no place, but names a real kin/friend/coworker + where to find them (their home he
  knows). No map mark.
- **refuse** — his nature/enmity says no; an in-character brush-off. No mark.
- **deflect** — parse failure / hallucinated id / uncertainty; vague words, `манера` dropped so no
  half-formed direction leaks. No mark.

**A geo share marks the MAP only — it writes no journal row.** The journal is quest-only now
([journal.md](journal.md)), and `_mark_seen` no longer writes any row; the share path reveals the
building on the fog-of-war map and nothing else. (The as-built code overrides the older spec, which
had proposed a `told` journal row.)

## Framer integration

The quest framer ([quests.md](quests.md)) whitelists the giver's `known_places` names into its
`allowed` set, and when a pitch names a place the giver knows, appends its real `direction_line` —
so a quest pitch can never send the player to a place the giver has no route to.

## Next

- NPC-to-NPC gossip grounding / biographical lies (separate workstream).
- Escort / «вести за собой» pathfinding rather than a name + where-line.

Related: [quests.md](quests.md) (grounded pitches) · [journal.md](journal.md) (map vs journal) ·
[locations.md](locations.md) (citygraph route) · [mind.md](mind.md) (persona/relationships)
