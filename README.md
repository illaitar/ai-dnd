# AI-DnD

Russian-language AI-D&D game: living frontier town (~1354 NPCs — minds, memory, needs, agendas),
per-user worlds from pre-generated pools, turn-based world (player action = world tick).
LLM parses intent, resolves ambiguity, speaks in character voices, and arbitrates freeform play;
deterministic code owns dice, budgets, inventories, and combat — and clamps everything the model
proposes. The town is stitched: people arrive and leave a scene, walk the streets between places,
fill taverns to capacity, and every session is recorded to a full text replay.

**The engine does not work without an LLM.** There are no offline fallbacks: no model → error,
not fake content. Stubs exist only in tests.

![Generated town maps](docs/assets/city_maps.png)

## Running

```bash
uv sync
uv run aidnd serve           # web UI: http://127.0.0.1:8000
uv run pytest -q
```

## Documentation

**[docs/README.md](docs/README.md)** — documentation map and core principles. From there:
[entities](docs/entities.md) · [game loop](docs/loop.md) · [NPC minds](docs/mind.md) ·
[city simulation](docs/citysim.md) · [sim stitching](docs/sim-stitching.md) ·
[world generation](docs/worldgen.md) · [combat](docs/combat.md) · [magic](docs/magic.md) ·
[items](docs/items.md) · [quests](docs/quests.md) · [journal](docs/journal.md) ·
[NPC geography](docs/geo.md) · [service & replay](docs/service.md) · [code structure](docs/structure.md)
