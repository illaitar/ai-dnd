# Architecture

## Nine layers

| Layer | Package | Responsibility |
|---|---|---|
| L1 World State | `world/` | ECS, event log, knowledge graph, spatial graph, environment |
| L2 LOD | `lod/` | LOD tiers, salience, smart objects, off-screen fast-forward |
| L3 Cognition | `cognition/` | NPC memory, relationships (affinity/trust/fear/respect), reflection |
| L4 Inference | `inference/` | model client, agent prompts + schemas, structured output |
| L5 Rules | `rules/` | deterministic 5e checks + dice |
| Combat | `combat/` | tactical grid combat (pathfinding, LoS, cover, surfaces, spells) |
| L7 Generation | `gen/` | NPCs, items, quests, discovery, map-info beliefs |
| L6/L8 Runtime | `runtime/` | orchestrator (game loop), director (pacing), snapshots |
| L9 Presentation | `server/` | FastAPI + WebSocket + web UI |

State changes are **event-sourced**: `world.commit(verb, …)` appends an `Event` and applies
it through `_h_*` handlers. Read-models (scene context, region map, journal) are derived,
never authoritative. This gives auditable history and golden replay.

## The turn pipeline

What happens after the player submits text. Agent roles are in **bold**; each has a
deterministic fallback so the same flow runs with no model.

```mermaid
flowchart TD
  IN([player types text]) --> H["GameSession.handle(text)"]
  H --> CB{combat active?}
  CB -- yes --> CMB["combat commands only"] --> VV
  CB -- no --> PI["_parse_intent"]

  subgraph PARSE["intent parsing — keyword-first, LLM-validated"]
    PI --> KW["_keyword_intent\nobserver? buyinfo? direction?\nVERB_KEYWORDS (attack/intimidate/persuade before talk)"]
    KW -- match --> ACT["Action(verb, target, tone)"]
    KW -- no match --> LLM["**intent**: agents.parse_intent\nvalidate verb in _VERBS"]
    LLM -- ok --> ACT
    LLM -- none/invalid --> DEF["address NPC? then talk\nelse freeform"]
    DEF --> ACT
  end

  ACT --> DISP{dispatch _do_verb}
  DISP --> MOVE["move: path_between then travel time/risk"]
  DISP --> TALK["talk: cognition.retrieve then\n**cognition** policy then\n**narrator** render_dialogue then\n**reflection** maybe_reflect"]
  DISP --> SOC["persuade/intimidate:\nfear-gate or skill check"]
  DISP --> ATK["attack: start combat\n(**tactician** on monster turns)"]
  DISP --> SRCH["search/loot/scan:\ndiscovery (seeded+persisted)\nplus **item_smith**"]
  DISP --> BUY["buy/buyinfo:\nmap beliefs (true/false/incomplete)"]
  DISP --> FREE["freeform:\n**plausibility** feasibility gate then\n**narrator** render_scene"]

  subgraph RESOLVE["resolution (roll mid-step)"]
    NEED{roll needed?} -- yes --> SUS["_suspend then RollRequest"] --> ROLL["player/server roll"] --> ADJ["submit_roll then adjudicate"]
    NEED -- no --> ADJ
  end

  SOC --> RESOLVE
  ATK --> RESOLVE
  SRCH --> RESOLVE
  ADJ --> COMMIT
  TALK --> COMMIT
  MOVE --> COMMIT
  BUY --> COMMIT
  FREE --> COMMIT

  COMMIT["world.commit(verb) then append Event then apply _h_*"]
  COMMIT --> COG["cognition.observe/appraise\n(relationship sliders)\nplus **lore_keeper** validates new content"]
  COG --> NARR["**narrator**: render outcome (numbers unchanged)"]
  NARR --> POST["_post: eventful? reset quiet\nelse quiet++ then **director** ambient_beat (pacing)"]
  POST --> VV["build view:\nscene, region_map, pacing, journal, quests"]
  VV --> OUT([response to player])
```

### Stage notes

- **Intent parsing** is keyword-first and deterministic; the `intent` model is consulted
  only for unmatched free text and is validated against the engine's verb set. Hostile and
  persuade keywords are matched before `talk` so "intimidate… speak!" is not misread as
  chat. Truly free-form input becomes a `freeform` action.
- **Feasibility gate** (`plausibility`): free-form actions are checked for whether they can
  happen here and now; impossible feats are refused before any narration. Offline, a rule
  list handles obvious impossibilities.
- **Resolution** can pause mid-step: when a roll is needed the turn suspends with a
  `RollRequest` and resumes on the result (server-animated or manual). Numbers are computed
  by the rules engine — never by the model.
- **Cognition**: every interaction is observed and appraised, evolving the per-NPC
  relationship vector; gates decide whether secrets are shared or fear triggers flight.
  NPCs periodically **reflect** to form higher-level beliefs.
- **Pacing** (`director`): after each non-combat turn a "quiet" counter tracks the lull;
  when it grows and the location permits, the probability of a context-appropriate random
  event rises (threat cues in the wild, social beats in town). Beats are narrative-only, so
  replay stays reproducible.

## Determinism

Anything that must replay identically is seeded with a `blake2b` sub-seed hierarchy
(`subseed(seed, scope, *parts)`) and committed through the event log. Model output,
pacing beats, and rendered narration are flavor/read-only and are excluded from
`state_hash()`.
