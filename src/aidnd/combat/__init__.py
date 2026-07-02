"""Боевой модуль (5e-lite, дух BG упрощённо): единый Combatant из бестиария/NPC/игрока,
пошаговый движок на гриде, ИИ, энкаунтеры из данных, авторезолв для офскрин-зачисток.

    from aidnd.combat import Encounter, from_pc, from_npc, from_monster, pick_encounter, resolve
"""

from __future__ import annotations

from . import dungeon
from .auto import resolve
from .encounters import lair_name, pick_encounter
from .engine import Encounter, roll_dice
from .model import Combatant, bestiary, from_monster, from_npc, from_pc

__all__ = ["Combatant", "Encounter", "bestiary", "from_monster", "from_npc", "from_pc",
           "pick_encounter", "lair_name", "resolve", "roll_dice", "dungeon"]
