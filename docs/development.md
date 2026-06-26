# Development

## Source layout

```
src/aidnd/
  world/        # L1 ECS, event log, knowledge graph, spatial graph, environment
  lod/          # L2 LOD tiers, salience, smart objects
  cognition/    # L3 memory, relationships, reflection
  inference/    # L4 model client, agent prompts+schemas, structured output
  rules/        # L5 deterministic 5e rules, dice, progression, factions
  combat/       # tactical combat (grid, surfaces, spells, tactician)
  gen/          # L7 generation: NPCs, items, quests, factions, locations, discovery
  runtime/      # L6/L8 orchestrator (game loop), leveling, director, persistence
  content/      # authored Phandalin/Cragmaw content, classes, factions, board, quests
  server/       # L9 FastAPI + WebSocket + web UI (game, /map, /city, /world, /eval)
  eval/         # LLM-as-judge scene/conversation harness
tests/          # pytest suite (deterministic, model-off)
docs/           # documentation site (Zensical)
datasets/       # training data per role (build.py → <role>.jsonl)
training/       # LoRA pipeline (prepare → train → export → eval), config.env
scripts/        # asset generation, local setup, deploy
```

## Testing & determinism

```bash
uv run pytest -q       # the suite is deterministic — it runs model-off
uv run ruff check .    # lint
```

`tests/test_replay.py` guards **golden replay**: an identical seed + inputs reproduce an
identical `state_hash()`. Anything that must replay identically is seeded with a `blake2b`
sub-seed hierarchy (`subseed(seed, scope, *parts)`) and committed through the event log.
Model output, pacing beats, and rendered narration are flavor/read-only and are excluded
from the hash, so they never perturb replay.

## Docs site

Built with [Zensical](https://zensical.org):

```bash
uv run zensical serve      # live preview
uv run zensical build      # static site
```
