"""L5 Rules — детерминированный движок 5e + кости (main §7, док 07)."""

from .checks import assemble_modifier, passive_check, save_modifier, skill_modifier
from .conditions import CONDITION_HOOKS, Condition, is_incapacitated
from .dice import (
    DiceService,
    RollRequest,
    RollResult,
    double_dice,
    parse_expr,
    roll_expr,
    validate_player_roll,
)
from .engine import Action, Outcome, RulesEngine, d20_test
from .srd import SKILL_ABILITY, WEAPONS, StatBlock, ability_modifier, get_stat_block

__all__ = [
    "DiceService", "RollRequest", "RollResult", "roll_expr", "parse_expr",
    "double_dice", "validate_player_roll", "ability_modifier", "get_stat_block",
    "SKILL_ABILITY", "WEAPONS", "StatBlock", "assemble_modifier", "passive_check",
    "skill_modifier", "save_modifier", "Condition", "CONDITION_HOOKS",
    "is_incapacitated", "RulesEngine", "Action", "Outcome", "d20_test",
]
