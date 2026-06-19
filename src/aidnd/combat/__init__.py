"""Combat — тактическая боевая подсистема «как в Baldur's Gate» (док 09 + док 10)."""

from . import spells, surfaces, tactician
from .engine import CombatEngine
from .grid import BattleGrid
from .state import Combatant, CombatState, Surface, TurnBudget

__all__ = ["CombatState", "Combatant", "TurnBudget", "Surface", "BattleGrid",
           "CombatEngine", "tactician", "surfaces", "spells"]
