# Agent roles

Each role is a system prompt + a JSON schema decoded under constraint, defined in
`inference/agents.py`. Every role is guarded by server availability and has a deterministic
fallback, so the engine behaves identically (if less colorfully) offline.

| Role | Wired in | Purpose | Fallback |
|---|---|---|---|
| `intent` | `runtime/orchestrator._parse_intent` | parse free text into a verb/target/tone | keyword parser |
| `plausibility` | `orchestrator.feasibility` | feasibility of a free-form player action in context | impossible-feat rule list |
| `narrator` | `orchestrator._narrate_outcome` / `_npc_*` | render outcomes and dialogue without changing numbers | grounded templates |
| `cognition` | `cognition.policy` | NPC action under relationship gates | trust/fear gate table |
| `reflection` | `cognition.maybe_reflect` | summarize memories into beliefs | single aggregating reflection |
| `character_gen` | `gen/npc_gen` + `gen/discovery` | enrich personas and spawn context-fitting NPCs | skeleton persona |
| `item_smith` | `gen/item_gen.spawn_item(smith=…)` | name/describe an item instance (cosmetic only) | template name |
| `tactician` | `combat/engine.auto_turn` | choose a monster's tactical action | deterministic target AI |
| `director` | `runtime/director` | pacing: hooks + lull-driven random events | heuristics + seeded beats |
| `quest_writer` | `runtime/director.generate_side_quest` | framing + giver lines for side quests | template framing |
| `lore_keeper` | `gen/pipeline.commit_with_validation` | validate generated content vs invariants | invariant checks |

## Hard guarantees

- The model **never** changes mechanics: dice, hit/miss, damage, rarity, and bonuses come
  from deterministic code. `narrator` and `item_smith` prompts forbid altering numbers.
- The model **never** decides existence of secrets/loot/observers — that is the seeded,
  persisted discovery system (`gen/discovery.py`); the model only flavors what already is.
- A trusted secret is only voiced if it is actually disclosable at the current trust
  (`content/knowledge.disclosable`), so a model cannot leak a fact below its gate.

## Connecting a model

```bash
uv run aidnd doctor     # prints OLLAMA_HOST and whether the server is reachable
```

Expose a local Ollama server (e.g. via SSH tunnel). When reachable, wired roles upgrade
narration, NPC reasoning, item flavor, quests, and tactics; otherwise the fallbacks run.

Several roles are fine-tuned LoRA adapters (`router`, `arbiter`, `consequence`, `narrator`,
`quest_writer`, `location_writer`) — see [Models & training](models.md).

## Role detail

Grouped by where each fires in the [turn pipeline](architecture.md).

### `intent` — understand the player
- **Fires at:** *Parse intent*, only when the keyword parser is unsure.
- **In:** player text + scene context (place, present NPCs, exits, affordances).
- **Out:** `{ verb, target, tone, needs_clarification }` (`verb` is an enum of engine commands).
- **Logic:** snaps to the nearest engine verb; a named NPC means `talk`, otherwise `freeform`.
- **Fallback:** keyword parser (verbs, directions, aliases).

### `plausibility` — feasibility gate
- **Fires at:** *Resolve* for free-form/ambiguous actions, before anything is narrated.
- **In:** the proposed action + world context.
- **Out:** `{ plausibility 0..1, drivers, verdict_note }`.
- **Fallback:** a rule list of impossible feats.

### `narrator` — render the result
- **Fires at:** *Narrate*, for dialogue replies **and** mechanical outcomes.
- **In:** the structured outcome (verb, damage + damage type, dialogue decision, scene).
- **Out:** prose narration — **never changes numbers**; no anachronisms, no invented NPC lines.
- **Fallback:** grounded templates.

### `cognition` — how an NPC reacts
- **Fires at:** *World reacts*, during `talk`/social.
- **In:** retrieved NPC memory + the relationship edge (trust/fear/affinity) + player verb/tone.
- **Out:** an action policy `{ action, info_disclosed, rationale_tags }`; disclosure gated by trust/fear.
- **Fallback:** a trust/fear gate table.

### `reflection` — NPC belief synthesis
- **Fires at:** *World reacts*, when an NPC's memory tree summarizes.
- **In:** leaf observations. **Out:** higher-level reflections, each citing the observation ids.
- **Fallback:** one aggregating reflection.

### `character_gen` — fill the NPC pool
- **Fires at:** lazily, at an NPC's first promotion (and when spawning passersby).
- **In:** a skeleton persona. **Out:** `{ voice, traits }`; spawns satisfy world invariants.
- **Fallback:** the deterministic skeleton persona.

### `item_smith` — flavor an item instance
- **Fires at:** *Resolve* for `search`/`loot`, when an item is spawned.
- **In:** the item template + world context. **Out:** `{ name, description, properties }` — **cosmetic only**.
- **Fallback:** the template name.

### `tactician` — monster turns
- **Fires at:** the *Combat loop*, on each monster's turn.
- **In:** a battle-state digest + the monster's stat block. **Out:** `{ intent, target, move_to, ability }`.
- **Fallback:** deterministic target selection / heuristic AI.

### `director` — pacing
- **Fires at:** *Pacing*, after a turn and during lulls.
- **In:** a world digest, active quests, recent events, the quiet streak.
- **Out:** a directive or an ambient beat; raises random-event odds the longer nothing happens.
- **Fallback:** heuristics + seeded ambient beats.

### `quest_writer` — side-quest text
- **Fires at:** when a side quest is assembled.
- **In:** the template, filled slots, world facts. **Out:** framing + giver/objective/completion text.
- **Fallback:** template framing.

### `lore_keeper` — invariant guard
- **Fires at:** *Commit*, validating proposed/generated content.
- **In:** the proposed content + the world knowledge graph. **Out:** a verdict with concrete fixes.
- **Fallback:** direct invariant checks.

### `faction_gen` — flesh out a faction
- **Fires at:** lazily, the first time the player inspects a per-world faction.
- **In:** the faction archetype + seed + the town. **Out:** `{ name, blurb, goals, values }`, persisted via an event.
- **Fallback:** the archetype defaults.

### `location_writer` — describe a place
- **Fires at:** world enrichment, for notable places (and their sub-locations).
- **In:** the location parameters (type, size, sensory fields, …). **Out:** persistent prose description.
- **Fallback:** the short `ambiance` line. Fine-tuned as [`aidnd-location`](models.md) on the 14B base.
