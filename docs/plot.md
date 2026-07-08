# Main Plot — Regressor Player

`src/aidnd/plot` — design doc fixed, package **NOT in runtime** (data model + validator +
casting ready; integration ahead). Plot — a book unfolded across the LIVING city: not a second
world, but threading onto existing people (~80% of cast — placed NPCs from pool; newcomers — only
where the matcher couldn't find a person).

## Core Idea

**Player — REGRESSOR**: already lived through this nightmare. The drama isn't "who's the villain,"
but "how to stop it, knowing everything yet being nobody":

- Knows only the GENERAL (3-6 broad strokes: the cult exists, disappearances aren't random,
  disaster follows a schedule, the guard can't be trusted, how it ended) + 2-6 VAGUE faces.
  **The truth of the scripture is hidden even from the player** — uncovered anew.
- **No proof** (go to the guard — you're a foreign slanderer, and the guard is bought);
  **no power** (12+ enemies, they have hierarchy and money); **memory is imperfect** — at least one
  node where memory LIES ("this time it's different" — mandatory reversal); **allies don't remember** —
  recruit from scratch, knowing more about them than they know about themselves.

## Plot Bible

The role of `plot_architect` [LLM]: seed (city profile) + factions + slice of placed NPCs → structural
JSON for the world: theme · conflict · mystery (for the city) · truth (regressor knows from prologue) ·
previous cycle · delta (nodes where memory lies) · cast in three categories (enemies/allies/important
neutrals). **Hierarchy** and **narrative importance** — two DIFFERENT dimensions. Generation —
lazy in the background after world construction; until ready, the city lives its ordinary life.

Casting (`casting.py`): matching roles from the bible to real residents by persona/traits.
Validator (`validate_bible`) — strict structural rules.

## Integration (plan)

Plot lives INSIDE existing mechanics: hooks → predicate contracts
([quests.md](quests.md)), recruitment = befriend/trust ([mind.md](mind.md)), clues = items
with hidden ([items.md](items.md)), encounters = combat ([combat.md](combat.md)), plot-handler
in tick ([loop.md](loop.md)). Regressor's memory — book prologue in UI.

**No-fallback duty:** `StubArchitect` (valid template "cult of victims") stays alive for now as
reference architect — upon plot integration, it goes to tests, runtime builds only
LLM-architect ([principle 1](README.md)).

Related: [quests.md](quests.md) · [mind.md](mind.md) · [entities.md](entities.md)
