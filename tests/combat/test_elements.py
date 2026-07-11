from aidnd.combat import Encounter
from aidnd.combat.model import Combatant, _resist_types


def test_resist_types_now_parses_elemental():
    assert _resist_types("acid, lightning") == {"acid", "lightning"}   # were silently dropped before
    assert "thunder" in _resist_types("thunder and fire")
    assert _resist_types("fire") == {"fire"}                            # the ones that already worked


def test_weapon_elements_maps_ru_to_english():
    from aidnd.server.play.mechanics.combat import _weapon_elements

    w = {"kind": "weapon", "form": "клинок", "attrs": {"горючесть": {"surface": 50, "true": 50}}}
    assert _weapon_elements(w) == [{"type": "fire", "amount": 2, "ru": "огонь"}]  # 50 → band 2
    assert _weapon_elements({"kind": "weapon", "name": "палка"}) == []            # legacy → none


class _Rng:
    """Constant rng: to-hit lands (not 1/20), damage is fixed — isolates the elemental delta."""
    def randint(self, a, b):
        return 10


def _atk(on_hit):
    return Combatant(id="pc", name="Ты", side="party", hp=20, max_hp=20, to_hit=20, range=20,
                     dmg_dice="1d6", dmg_bonus=0, dmg_type="slashing", on_hit=on_hit)


def _foe(immune=(), resist=()):
    return Combatant(id="g0", name="Гоблин", side="foes", hp=40, max_hp=40, ac=1,
                     immune=set(immune), resist=set(resist))


def _hp_drop(on_hit, **foe):
    enc = Encounter([_atk(on_hit)], [_foe(**foe)], seed="el")
    enc.rng = _Rng()                                        # deterministic AFTER spawn/initiative
    enc.acted = False
    before = enc.units["g0"].hp
    enc.act_attack(enc.units["pc"], "g0")
    return before - enc.units["g0"].hp


def test_on_hit_elements_honor_resist_and_immune():
    base = _hp_drop([])                                     # physical only
    fire = [{"type": "fire", "amount": 2, "ru": "огонь"}]
    assert _hp_drop(fire) == base + 2                       # plain target: +2 fire
    assert _hp_drop(fire, immune=["fire"]) == base          # fire-immune: +0
    assert _hp_drop(fire, resist=["fire"]) == base + 1      # fire-resist: halved to +1
