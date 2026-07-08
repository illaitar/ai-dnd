# NPC Mind and Society

`src/aidnd/mind` (pure package: does not know about server/DB/city graph) + `src/aidnd/society`
(needs→places→routine). Behavior is **emergent**: no role branches or scripts—only
goals × utility × personality ([principle 3](README.md)).

## Decision Pipeline (Mechanical Core)

```
perceive(state, world) → Percept(here, exits, present, nearby, me)
  → urges (need × trait-weight → urgency)         modulators.py
  → modulators ×6: arousal/valence/dominance/resolution/selection_threshold/securing
  → propose_goals: 9 goal types                   goals.py
      need · acquire · harm · safe · trade · affiliate · protect · inform · converse
      (from standing needs + threats + predatory opportunities + social pulls + agendas)
  → utility(action|goal): goal-type dispatcher    value.py  (unified BAL config, 27 coeffs.)
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
