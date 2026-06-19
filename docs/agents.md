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
