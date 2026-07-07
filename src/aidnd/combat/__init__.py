"""Боевой модуль (5e-lite, дух BG упрощённо): единый Combatant из бестиария/NPC/игрока,
пошаговый движок на гриде, ИИ, энкаунтеры из данных, авторезолв для офскрин-зачисток.

    from aidnd.combat import Encounter, from_pc, from_npc, from_monster, pick_encounter, resolve

Key functions
-------------
Combatant : unified combat model for players, NPCs, and monsters (stats, inventory, morale).
Encounter : manages grid-based combat with turn order, initiative, and AI decisions.
from_pc(player) -> Combatant : create combatant from player character.
from_npc(npc) -> Combatant : create combatant from NPC.
from_monster(key) -> Combatant : create combatant from bestiary entry.
resolve(encounter) : auto-resolve entire encounter and return outcome.
"""

from __future__ import annotations

from . import dungeon
from .auto import resolve
from .encounters import lair_name, pick_encounter
from .engine import Encounter, roll_dice
from .model import Combatant, bestiary, from_monster, from_npc, from_pc

__all__ = ["Combatant", "Encounter", "bestiary", "from_monster", "from_npc", "from_pc",
           "pick_encounter", "lair_name", "resolve", "roll_dice", "dungeon"]
