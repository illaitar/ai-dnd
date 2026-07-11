class _P:
    def __init__(self, gear):
        self.persona = {"gear": gear}


def test_npc_gear_bonus_resolves_and_dual_path():
    from aidnd.server.play.mechanics.combat import _npc_gear_bonus

    assert _npc_gear_bonus("старый нож мясника", "fine", "attack") > 0     # нож → derived attack
    assert _npc_gear_bonus("кожаный жилет", "fine", "defense") > 0         # armor → derived defense
    assert _npc_gear_bonus("несуществующая-дрянь-щщ", "fine", "attack") == 0   # unresolved → 0
    assert 0 <= _npc_gear_bonus("стальной меч", "exquisite", "attack") <= 3    # bounded


def test_npc_weapon_carries_derived_bonus():
    from aidnd.server.play.mechanics.combat import _npc_weapon

    w = _npc_weapon(_P({"weapon": {"name": "стальной меч", "tier": "comfortable"}}))
    assert w["quality"] == "fine" and w["bonus"] >= 1     # a steel sword bites
    assert _npc_weapon(_P({})) is None                    # no weapon → None
