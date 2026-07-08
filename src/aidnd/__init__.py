"""AI-DnD.

Russian-language AI-D&D game: a living city (~900 NPCs with minds/memories/agendas),
per-user world from pre-generated pools, turn-based world (player action = tick).

Core principles (canon — docs/README.md):
- LLM is required: no offline fallbacks (no model → LLMUnavailable, stubs only in tests);
- LLM proposes — code clamps: dice, budgets, inventory, combat — deterministic code;
- general abstract systems, not special cases; player is the same agent as NPC.
"""

__version__ = "0.1.0"
