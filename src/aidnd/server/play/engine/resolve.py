"""Arbiter of free-form input — single resolve(text) (docs/loop.md "Further", principle 3).

Facade: arbiter (PRIMITIVES, prompt, context assembly, resolve/normalize) now lives in
action/arbiter.py — re-imported here so existing importers are untouched. Context assembler
feeds arbiter MAXIMUM scene facts (people, containers, bag, zones, nearby items, city locations,
time) — arbiter parses intent and goals itself; executors (primitive×manner×gates) live in
handlers/freeform._attempt.

Key functions
-------------
resolve(text: str, sc: dict) -> dict | None : Parse player input to verb-target-manner plan via LLM arbiter.
assemble_context(sc: dict) -> str : Gather scene facts (NPCs, items, zones) for arbiter.
normalize_plan(out: dict, cap: int = 3) -> dict : Validate and clean arbiter response into executable plan.
_voice(p, rel, kind, player_text) -> str : NPC speaks in-character (LLM narrator) — folds in persona,
    memory of the player, grudges and world-lookup facts; records the player's tone. [moved from world.py]
_world_lookup(query, from_node) -> str : truthful world facts (buildings with a route, locals) for the
    know/ask tool — never lets the model invent the city. [moved from world.py]
_dm_snapshot(sc: dict) -> str : narrator snapshot of the live scene (place/time, who is where, audible
    lines, nearby items) so the DM describes THIS world, not an invented one. [moved from world.py]
"""

from __future__ import annotations

from aidnd.server.play.engine.action.arbiter import _FIELD_HINT as _FIELD_HINT
from aidnd.server.play.engine.action.arbiter import PRIMITIVES as PRIMITIVES
from aidnd.server.play.engine.action.arbiter import _sys_prompt as _sys_prompt
from aidnd.server.play.engine.action.arbiter import assemble_context as assemble_context
from aidnd.server.play.engine.action.arbiter import normalize_plan as normalize_plan
from aidnd.server.play.engine.action.arbiter import resolve as resolve
from aidnd.server.play.engine.narrator.lookup import _world_lookup as _world_lookup
from aidnd.server.play.engine.narrator.snapshot import _ambient_note as _ambient_note
from aidnd.server.play.engine.narrator.snapshot import _dm_snapshot as _dm_snapshot
from aidnd.server.play.engine.narrator.voice import _STANCE as _STANCE
from aidnd.server.play.engine.narrator.voice import _VOICE as _VOICE
from aidnd.server.play.engine.narrator.voice import _voice as _voice
