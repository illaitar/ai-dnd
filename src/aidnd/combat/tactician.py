"""Мораль монстров (док 09 §9).

Позиционный ИИ монстра (выбор цели, сближение, атака/каст) реализован прямо в
CombatEngine.auto_turn детерминированно. Здесь — только проверка морали: на низком
HP малоинтеллектуальный монстр может обратиться в бегство. LLM-роль Combat
Tactician (main §12.6, agents.choose_tactic) остаётся доступной как опция поверх.
"""

from __future__ import annotations

from ..rules.srd import ability_modifier, get_stat_block
from ..world.components import Persona, Stats5e

MORALE_HP_FRACTION = 0.25
MORALE_INT_MAX = 8
MORALE_DC = 12


def morale_check(world, dice, state, monster_id: str) -> str:
    """'flee' если монстр глуп (Int ≤ 8), на низком HP и провалил спасбросок морали."""
    persona = world.ecs.get(monster_id, Persona)
    sb = get_stat_block(persona.stat_block_ref) if persona else get_stat_block("srd:commoner")
    st = world.ecs.get(monster_id, Stats5e)
    if st and st.hp < st.max_hp * MORALE_HP_FRACTION and sb.intelligence_score <= MORALE_INT_MAX:
        res = dice.roll_seeded("save", "1d20", modifier=ability_modifier(sb.wis),
                               dc=MORALE_DC, roller=monster_id)
        if res.total < MORALE_DC:
            return "flee"
    return "fight"
