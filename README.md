# AI-DnD Engine

A text-tactical **D&D 5e** engine with a persistent, simulated world, level-of-detail (LOD)
NPC simulation, and a set of local **LLM agents** — built as a vertical slice of *Lost Mine
of Phandalin* (Phandalin town + the Cragmaw region). Backend in Python, presentation in JS.

**Determinism is separated from language.** Dice, rules, and world state are deterministic,
auditable code; the LLM only *parses intent* and *renders results* — it never decides
outcomes or computes mechanics. Every model path has a deterministic fallback, so the engine
plays end-to-end **with no model server**, and the same seed + inputs reproduce the same
`state_hash()` (golden replay).

![Generated town maps](docs/assets/city_maps.png)

## Highlights

- **Deterministic world** — procedural, seeded town maps (Watabou-style: Voronoi wards,
  walls, a river, key buildings). The model adds flavor (names, descriptions), never the
  layout. → [Maps](docs/maps.md)
- **Event-sourced state** — `world.commit(verb, …)` appends an `Event` applied through
  `_h_*` handlers; read-models are derived, never authoritative. Auditable history + golden
  replay. → [Architecture](docs/architecture.md)
- **LOD NPC simulation** — per-NPC memory, relationships (affinity/trust/fear/respect) and
  reflection; off-screen NPCs fast-forward by routine. → [Architecture](docs/architecture.md)
- **LLM agent roles** — each a system prompt + JSON schema (structured decoding at
  temperature 0) with a deterministic fallback. → [Agent roles](docs/agents.md)

## Models

Per-role **LoRA adapters** over a shared base, trained with QLoRA, exported to Ollama and
published on Hugging Face. Each upgrades one role where wired in; all have deterministic
fallbacks, so the engine runs fully without them. Details, datasets and the training
pipeline: → [Models & training](docs/models.md).

| Adapter | Role | Base | Hugging Face |
|---|---|---|---|
| `aidnd-router` | parse player intent → verb / target / tone | Qwen3.5-9B | [Illaitar/aidnd-router](https://huggingface.co/Illaitar/aidnd-router) |
| `aidnd-arbiter` | adjudicate free-form actions | Qwen3.5-9B | [Illaitar/aidnd-arbiter](https://huggingface.co/Illaitar/aidnd-arbiter) |
| `aidnd-consequence` | world effects of a resolved action | Qwen3.5-9B | [Illaitar/aidnd-consequence](https://huggingface.co/Illaitar/aidnd-consequence) |
| `aidnd-narrator` | render outcomes + dialogue as prose | Qwen3.5-9B | [Illaitar/aidnd-narrator](https://huggingface.co/Illaitar/aidnd-narrator) |
| `aidnd-quest` | side-quest framing + giver lines | Qwen3.5-9B | [Illaitar/aidnd-quest](https://huggingface.co/Illaitar/aidnd-quest) |
| `aidnd-location` | location descriptions (parameters → prose, with sub-locations) | Qwen3-14B | [Illaitar/aidnd-location](https://huggingface.co/Illaitar/aidnd-location) |

Base models in Ollama: `qwen3.5:9b` (most roles) · `qwen3:14b` (location) · `qwen3.5:2b`
(fast intent classifier).

## Quickstart

```bash
uv sync                      # runtime + dev group (pytest, ruff, zensical)
uv run aidnd                 # play in the terminal — offline, no model required
uv run aidnd serve           # web UI at http://127.0.0.1:8000  (live map at /map)
uv run aidnd doctor          # check the model server (optional)
uv run pytest -q             # deterministic test suite (runs model-off)
```

No `uv`? A `.venv` + `pip install -e .` works too, or use `./run.sh`. To run the models on
your own hardware (Ollama, no remote box), see [Running locally](docs/running.md).

## Docs

Built with [Zensical](https://zensical.org) — `uv run zensical serve` (or `build`). Source
in [`docs/`](docs/):

- **[Architecture](docs/architecture.md)** — the nine layers, the full turn pipeline, determinism.
- **[Agent roles](docs/agents.md)** — every LLM role, its schema, where it fires, and its fallback.
- **[Models & training](docs/models.md)** — the adapters, datasets, and the LoRA→GGUF→Ollama pipeline.
- **[Maps](docs/maps.md)** — procedural town and dungeon generation.
- **[Gameplay](docs/gameplay.md)** — how to play: commands, map, pacing, dialogue.
- **[Running locally](docs/running.md)** — Ollama setup and model environment variables.
- **[Development](docs/development.md)** — source layout, testing, and golden replay.
