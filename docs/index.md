# AI-DnD Engine

A text-tactical **D&D 5e** engine with a persistent simulated world, LOD NPC simulation,
and local **LLM agents** — a vertical slice of *Lost Mine of Phandalin*.

- **[Architecture](architecture.md)** — the nine layers and the full turn pipeline.
- **[Agent roles](agents.md)** — the eleven LLM roles and their deterministic fallbacks.
- **[Gameplay](gameplay.md)** — how to play, commands, map, pacing, dialogue.

## Core principle: determinism is separated from language

Dice, rules, and world state are deterministic, auditable code. The LLM only **parses
intent** and **renders results** — it never decides outcomes. Every model path has a
deterministic fallback, so the engine plays end-to-end **without a model server**, and the
same seed + inputs reproduce the same `state_hash()` (golden replay).

```bash
uv sync && uv run aidnd          # play offline, no model required
uv run aidnd serve               # web UI + live map at /map
```
