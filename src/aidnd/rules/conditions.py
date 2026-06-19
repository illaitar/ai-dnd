"""Состояния как статус-эффекты с механическими хуками (док 09 §7).

Хуки кормят движок модификаторов из дока 07 §6. Длительность отслеживается
раундами, save-ends либо привязкой к концентрации.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Condition:
    name: str
    duration_kind: str = "rounds"   # rounds | save_ends | concentration | until_stable
    rounds_left: int = 1
    save_ability: str | None = None
    save_dc: int | None = None
    source: str | None = None


# механические хуки состояний (док 09 §7)
CONDITION_HOOKS = {
    "prone": {"melee_attacks_against": "advantage", "ranged_attacks_against": "disadvantage",
              "own_attacks": "disadvantage", "speed": 0},
    "frightened": {"own_attacks": "disadvantage", "own_checks": "disadvantage"},
    "restrained": {"attacks_against": "advantage", "own_attacks": "disadvantage", "speed": 0},
    "poisoned": {"own_attacks": "disadvantage", "own_checks": "disadvantage"},
    "stunned": {"incapacitated": True, "attacks_against": "advantage",
                "auto_fail": ["str", "dex"]},
    "unconscious": {"incapacitated": True, "attacks_against": "advantage",
                    "melee_crit_against": True, "speed": 0},
    "blinded": {"own_attacks": "disadvantage", "attacks_against": "advantage"},
    "grappled": {"speed": 0},
    "dodging": {"attacks_against": "disadvantage"},
    "helped": {"own_next_check": "advantage"},
}


def is_incapacitated(conditions: list[Condition]) -> bool:
    return any(CONDITION_HOOKS.get(c.name, {}).get("incapacitated") for c in conditions)


def advantage_from_conditions(
    conditions: list[Condition], role: str,
) -> int:
    """role: 'own_attacks' | 'attacks_against' | 'own_checks' ...
    Возвращает +1 (adv), -1 (dis) либо 0. adv и dis взаимно гасятся (5e)."""
    adv = dis = False
    for c in conditions:
        hook = CONDITION_HOOKS.get(c.name, {}).get(role)
        if hook == "advantage":
            adv = True
        elif hook == "disadvantage":
            dis = True
    return (1 if adv else 0) - (1 if dis else 0)


def speed_override(conditions: list[Condition]) -> int | None:
    for c in conditions:
        if CONDITION_HOOKS.get(c.name, {}).get("speed") == 0:
            return 0
    return None
