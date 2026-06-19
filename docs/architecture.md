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

Node colour: 🟣 LLM-backed (deterministic fallback) · 🟡 decision · 🟢 in / out.

```mermaid
flowchart TD
  IN([Player types text]):::io --> H["GameSession.handle"]:::core
  H --> CB{In combat?}:::dec
  CB -- yes --> CMB["Combat commands only"]:::core --> OUT
  CB -- no --> KW["Keyword parser<br/>observer? · buyinfo? · direction?<br/>attack · intimidate · persuade before talk"]:::core

  KW -- clear command --> ACT["Action<br/>verb · target · tone"]:::core
  KW -- unclear --> LLM["intent model — small Qwen<br/>map free text → closest command"]:::llm
  LLM -- confident --> ACT
  LLM -- unsure / other --> DEF["named NPC → talk<br/>else → freeform"]:::core
  DEF --> ACT

  ACT --> DISP{Dispatch verb}:::dec
  DISP --> MOVE["move<br/>path-find · travel time & risk"]:::core
  DISP --> TALK["talk<br/>cognition policy · narrator · reflection"]:::llm
  DISP --> SOC["persuade / intimidate<br/>fear-gate or skill check"]:::core
  DISP --> ATK["attack → combat<br/>tactician drives monsters"]:::llm
  DISP --> SRCH["search / loot / scan<br/>seeded discovery · item_smith"]:::llm
  DISP --> BUY["buy / buyinfo<br/>map beliefs: true · false · partial"]:::core
  DISP --> FREE["freeform<br/>feasibility gate (plausibility) · narrator"]:::llm

  SOC --> ROLL{Roll needed?}:::dec
  ATK --> ROLL
  SRCH --> ROLL
  ROLL -- yes --> SUS["suspend → RollRequest<br/>→ roll → adjudicate"]:::core --> COMMIT
  ROLL -- no --> COMMIT
  MOVE --> COMMIT
  TALK --> COMMIT
  BUY --> COMMIT
  FREE --> COMMIT

  COMMIT["world.commit → Event → apply<br/>event-sourced · lore_keeper validates content"]:::core
  COMMIT --> COG["cognition observe / appraise<br/>relationship sliders"]:::core
  COG --> NARR["narrator renders outcome<br/>numbers never change"]:::llm
  NARR --> POST["pacing — quiet streak<br/>director ambient_beat"]:::llm
  POST --> OUT([Response to player]):::io

  classDef io fill:#1f6f4a,stroke:#5fd39a,color:#eafff4,font-weight:bold;
  classDef llm fill:#3a2f6b,stroke:#9d8cff,color:#efeaff;
  classDef dec fill:#7a5b16,stroke:#e6b84a,color:#fff7e6;
  classDef core fill:#2b2f37,stroke:#6b7480,color:#eef1f5;
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
