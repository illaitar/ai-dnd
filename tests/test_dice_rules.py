"""Кости и правила 5e — детерминизм, adv/dis, крит/фамбл, модификаторы (док 07, main §7)."""

from aidnd.inventory.container import armor_class
from aidnd.rules.checks import attack_modifier, passive_check
from aidnd.rules.dice import (
    RollRequest,
    double_dice,
    parse_expr,
    roll_expr,
    validate_player_roll,
)
from aidnd.rules.engine import d20_test
from aidnd.rules.srd import ability_modifier


def test_expr_parsing():
    assert parse_expr("2d6+3") == (2, 6, 3)
    assert parse_expr("1d20") == (1, 20, 0)
    assert parse_expr("1d8-1") == (1, 8, -1)
    assert parse_expr("5") == (0, 0, 5)
    assert double_dice("1d8+3") == "2d8+3"


def test_dice_determinism():
    a = roll_expr("r", "1d20", seed=42, modifier=5)
    b = roll_expr("r", "1d20", seed=42, modifier=5)
    assert a.total == b.total and a.raw == b.raw


def test_advantage_takes_higher():
    r = roll_expr("r", "1d20", seed=7, advantage=1)
    assert r.nat == max(r.raw)
    r2 = roll_expr("r", "1d20", seed=7, advantage=-1)
    assert r2.nat == min(r2.raw)


def test_ability_modifier_5e():
    assert ability_modifier(10) == 0
    assert ability_modifier(16) == 3
    assert ability_modifier(8) == -1
    assert ability_modifier(20) == 5


def test_d20_semantics_crit_fumble():
    class R:  # фейковый результат
        def __init__(self, nat, total): self.nat, self.total = nat, total
    assert d20_test(R(20, 5), dc=99, is_attack=True)["crit"] is True
    assert d20_test(R(1, 99), dc=1, is_attack=True)["fumble"] is True
    assert d20_test(R(12, 15), dc=13, is_attack=False)["success"] is True
    assert d20_test(R(12, 10), dc=13, is_attack=False)["success"] is False


def test_player_roll_uses_server_modifier(world):
    # игрок не может подменить модификатор — он берётся серверный
    req = RollRequest("x", "pc:hero", "attack", "1d20", modifier=5, advantage=0, dc=15)
    res = validate_player_roll(req, [18])
    assert res.total == 23 and res.nat == 18


def test_pc_attack_modifier_and_ac(world):
    # PC: STR 16 (+3) + proficiency +2, длинный меч → атака +5
    mod, adv = attack_modifier(world, "pc:hero")
    assert mod == 5
    # AC: кольчужная рубаха 13 + DEX 2 + щит 2 = 17
    assert armor_class(world, "pc:hero") == 17


def test_passive_perception(world):
    # PC proficient в perception: 10 + WIS(+1) + prof(+2) = 13
    assert passive_check(world, "pc:hero", "perception") == 13
