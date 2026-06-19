"""Движок модификаторов: сборка из всех систем (док 07 §6).

Один движок собирает статы и proficiency, экип (док 04), состояния (правила),
отношения (док 02) и правдоподобие (док 06). Так бросок Persuasion на торг
включает отношение к торговцу, бросок атаки — магическое оружие, бросок при
frightened идёт с disadvantage.
"""

from __future__ import annotations

from ..world.components import Relationships, Stats5e
from .conditions import Condition, advantage_from_conditions
from .srd import SKILL_ABILITY, SOCIAL_SKILLS, ability_modifier


def ability_mod(world, eid: str, ability: str) -> int:
    st = world.ecs.get(eid, Stats5e)
    if st is None:
        return 0
    return ability_modifier(st.ability(ability))


def proficiency_bonus(world, eid: str) -> int:
    st = world.ecs.get(eid, Stats5e)
    return st.proficiency if st else 2


def skill_modifier(world, eid: str, skill: str) -> int:
    ability = SKILL_ABILITY.get(skill, skill if skill in {"str", "dex", "con", "int", "wis", "cha"} else "wis")
    mod = ability_mod(world, eid, ability)
    st = world.ecs.get(eid, Stats5e)
    if st and skill in st.proficient_skills:
        mod += st.proficiency
    return mod


def save_modifier(world, eid: str, ability: str) -> int:
    mod = ability_mod(world, eid, ability)
    st = world.ecs.get(eid, Stats5e)
    if st and ability in st.proficient_saves:
        mod += st.proficiency
    return mod


def equipment_bonus(world, eid: str, kind: str) -> int:
    """Бонус к атаке/урону от экипированного магического оружия (док 04)."""
    try:
        from ..inventory.container import attack_bonus_from_equipment
        return attack_bonus_from_equipment(world, eid, kind)
    except Exception:
        return 0


def conditions_of(world, eid: str) -> list[Condition]:
    return world.conditions.get(eid, [])


def relationship_advantage(world, npc_id: str, actor_id: str) -> int:
    """Высокий trust к актору облегчает соц.проверки против NPC (док 07 §6)."""
    rels = world.ecs.get(npc_id, Relationships)
    if not rels:
        return 0
    edge = rels.edges.get(actor_id)
    if not edge:
        return 0
    if edge.trust >= 0.4 or edge.affinity >= 0.5:
        return 1
    if edge.trust <= -0.4 or edge.fear >= 0.6:
        return -1
    return 0


def assemble_modifier(
    world, eid: str, *, skill: str | None = None, ability: str | None = None,
    is_attack: bool = False, target: str | None = None, kind: str = "skill",
) -> tuple[int, int]:
    """Возвращает (mod, advantage) для броска. Главная точка интеграции (док 07 §6)."""
    mod = 0
    if skill:
        mod += skill_modifier(world, eid, skill)
    elif ability:
        mod += save_modifier(world, eid, ability) if kind == "save" else ability_mod(world, eid, ability)

    # экип
    if is_attack:
        mod += equipment_bonus(world, eid, "attack")

    # состояния атакующего/проверяющего
    role = "own_attacks" if is_attack else "own_checks"
    adv = advantage_from_conditions(conditions_of(world, eid), role)

    # отношения для социальных проверок
    if skill in SOCIAL_SKILLS and target:
        adv += relationship_advantage(world, target, eid)

    return mod, max(-1, min(1, adv))


def passive_check(world, eid: str, skill: str, adv: int = 0) -> int:
    """10 + модификатор (+5 adv / -5 dis), без броска (док 07 §5)."""
    return 10 + skill_modifier(world, eid, skill) + 5 * adv


def attack_modifier(world, attacker: str, target: str | None = None) -> tuple[int, int]:
    """Модификатор броска атаки: мод характеристики оружия + proficiency + магия +
    advantage из состояний (док 07 §6, док 09 §5)."""
    from ..inventory.container import equipped_weapon_key
    from ..rules.srd import WEAPONS
    wkey = equipped_weapon_key(world, attacker)
    weapon = WEAPONS.get(wkey, WEAPONS["unarmed"])
    abil = weapon.ability
    if "finesse" in weapon.properties:           # finesse — лучшая из STR/DEX
        abil = "str" if ability_mod(world, attacker, "str") >= ability_mod(world, attacker, "dex") else "dex"
    mod = (ability_mod(world, attacker, abil) + proficiency_bonus(world, attacker)
           + equipment_bonus(world, attacker, "attack"))
    adv = advantage_from_conditions(conditions_of(world, attacker), "own_attacks")
    if target:
        adv += advantage_from_conditions(conditions_of(world, target), "attacks_against")
    return mod, max(-1, min(1, adv))
