from aidnd.combat.model import from_npc, from_pc


def test_pc_weapon_bonus_adds_to_damage_only():
    ab = {"str": 12, "dex": 12}
    base = from_pc(ab, 20, 20, weapon={"quality": "fine"})
    boosted = from_pc(ab, 20, 20, weapon={"quality": "fine", "bonus": 3})
    assert boosted.dmg_bonus == base.dmg_bonus + 3        # derived attack → damage bonus
    assert boosted.dmg_dice == base.dmg_dice              # dice come from quality, unchanged
    assert from_pc(ab, 20, 20, weapon={"quality": "fine"}).dmg_bonus == base.dmg_bonus  # legacy: no bonus key → 0


def test_npc_weapon_bonus_backward_compatible():
    m = {"abilities": {"str": 12, "dex": 10}, "traits": {"bravery": 0.5}}
    base = from_npc("n", "N", m, weapon={"quality": "plain"})
    boosted = from_npc("n", "N", m, weapon={"quality": "plain", "bonus": 2})
    assert boosted.dmg_bonus == base.dmg_bonus + 2
