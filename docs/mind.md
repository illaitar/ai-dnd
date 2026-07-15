# NPC Mind and Society

`src/aidnd/mind` (pure package: does not know about server/DB/city graph) + `src/aidnd/society`
(needs→places→routine). Behavior is **emergent**: no role branches or scripts—only
goals × utility × personality ([principle 3](README.md)).

## Decision Pipeline (Mechanical Core)

```
perceive(state, world) → Percept(here, exits, present, nearby, me)
  → appraise_present: read each present Body's SURFACE → Impression → emotion delta   appraisal.py
  → urges (need × trait-weight → urgency)         modulators.py
  → modulators ×6: arousal/valence/dominance/resolution/selection_threshold/securing
  → propose_goals: 9 goal types                   goals.py
      need · acquire · harm · safe · trade · affiliate · protect · inform · converse
      (from standing needs + threats + predatory opportunities + social pulls + agendas)
  → utility(action|goal): goal-type dispatcher    value.py  (unified BAL config; + proxemics term)
  → softmax top-k (PROBABILISTIC choice, not argmax) act.py
  → apply → world event                           llm_agent.apply_actions / mind.apply
  → appraise (event appraisal → emotion deltas) → decay (needs grow, emotions fade)
```

**7 primitives**—the entire action vocabulary: `move · attack · take · give · say · use · wait`
(`say` is speech acts: chat/threat/flatter/ask/counter/accept). Flight, extortion,
ambush, theft-without-witnesses, ally defense—these are *which primitive wins under which goal*,
not special code. Covered by emergence tests (`tests/mind/test_emergent.py`, 10 scenarios).

**Mode FSM** (fsm.py): `routine ↔ leisure ↔ converse ↔ threat`—transition on urgency stakes
with hysteresis; mode colors the plan, does not replace utility.

## Perception & Appraisal (`appraisal.py`, in production)

Before choosing, an entity **reads the room**. `appraise_present` runs each tick over everyone
visibly present: for each other Body it computes an `impression`—a pure read of the observer's
traits × the other's visible SURFACE (race, squalor, charisma, armed, marks) combined with two more
tiers, ordered **personal > culture > personality**:

- **A — traits × surface** (zero authoring): `revulsion = pride × (1−appearance) × squalor`,
  `warmth = sociability × charisma`, `wary = (1−bravery) × armed`, `contempt = malice × (1−honesty)`.
- **B — culture**: `race_sentiment` from `content/race_relations.json` (a dwarf distrusts orcs),
  amplified by the observer's `malice`. Non-human NPCs are seeded into the pool (`worldgen/seed_races.py`).
- **C — personal**: an existing `relationship` dominates—"he's an orc *(hate)* but he saved my life
  *(trust)*" resolves to warmth.

The `Impression{valence, emo, prior, remember}` feeds `appraise()` (emotion delta, incl. **disgust**,
the 5th emotion driven by `pride`) and, **once on first encounter**, seeds a relationship prior and a
short memory ("замызганный оборванец у очага"). A proud citizen recoils from a beggar with nothing
authored—it falls out of his traits meeting the beggar's surface. Positioning follows: a `_proxemics`
term in the move utility (`value.py`, `BAL["proxemics"]`, small—never overrides needs/safety) pulls
seats away from the disliked and toward the liked.

**Player parity, one exception (new this session):** `appraise_present(..., skip_seed_id=player_id)`
never auto-seeds a relationship prior or memory toward the PLAYER from **mere co-presence**—a stranger
stays mechanically a stranger until a REAL interaction (talk/deal/combat) earns trust. Emotion still
moves each tick either way; only the silent prior/memory seeding is skipped for the player. `decide_hybrid`
threads `player_id` in via `ctx`; the module is otherwise player-agnostic (read, never role-checked).

Salience of *who thinks in a crowd* is **reason-based**, not a cap: an NPC deep in a busy scene wakes
for a new arrival, something spoken, or a goal-relevant actor—not for every passer-by
(cross-ref [citysim.md](citysim.md) · [sim-stitching](structure.md) · attention economy Pillar 2,
[sound-attention.md](sound-attention.md)).

## LLM Hybrid (Player Scene Ring A)

`decide_hybrid` (llm_agent.py): mechanics give top-5 ranked URGES → LLM chooses
IN CHARACTER (persona from pool, relations, memory, action history, time), adds a line and
description of "what I do". Bad response → retry → `LLMBadOutput` (no fallback to mechanics).
`apply_actions` executes tools: movement, attack, REAL theft (moves corpse loot),
speech (into memory and hist of both sides), note, self-regulation of emotions/needs.

## Memory

`MemoryStore` (memory.py): memories with importance/type (observation/heard/note/…);
retrieval = recency (half-life ~1 day) · importance · lexical relevance → shortlist →
optional LLM-rerank (cognition role). Without reranker—mechanical order (this is
ranking, not content—authorized). Recall refreshes memory. Gossip (`_gossip`
in world.py) spreads vivid facts among present NPCs.

## Agendas (Long-term Goals)

`plan_agenda` [LLM, rare call]: nature+memory+environment → one life agenda
(wealth/courtship/ambition/revenge/predation) with milestones; each milestone is a MECHANICAL goal
(need/affiliate/trade/acquire/harm) with completion predicate (wealth N / dead X /
affinity X / have item / at place). Core pulls current milestone reactively; `advance_agendas`
moves cursor by world facts. Agendas are the source of contracts ([quests.md](quests.md)).

## Society: Routine from Needs (Ring B)

`society/`—declarative catalogs: 7 needs (growth rate × scale from traits) and place types
(what closes need, day-phase window, trait sympathies, gate any/job/guard/rogue).
`routine.step`: grow needs over minutes → score candidates
`window(phase) × sympathy(traits) × Σ(closure·pressure)` → node. Laborer at lathe by day,
home by night; sociable one in tavern; rogue with malice on prowl at night. Zero hardcoded roles.
City adapter—`server/play/engine/worldsim.py`. Inside a building the same scoring
recurses on ZONES of location via afford-objects—[locations.md](locations.md).

## Quality Assurance

`tests/mind` + `tests/society` (modulator neutrality, shift systemicity, emergence,
catalog consistency) · benches `scripts/bench_archetypes.py`, `mind_sim*.py` (15 archetypes,
live LLM). Practice rule: NPC behavior tested with LIVE model, not just units.

Related: [loop.md](loop.md) · [entities.md](entities.md) (NpcState) ·
[quests.md](quests.md) (agendas → contracts)
