"""Боевые статусы (М-4): связан/спит пропускают ход, напуган пятится, урон будит спящего, тик на исходе хода."""

from __future__ import annotations

from aidnd.combat.engine import Encounter
from aidnd.combat.model import Combatant


def _duo():
    pc = Combatant(id="pc", name="Герой", side="party", hp=20, max_hp=20, dmg_dice="1d1", to_hit=20)
    foe = Combatant(id="g1", name="Гоблин", side="foes", hp=10, max_hp=10, kind="monster")
    enc = Encounter([pc], [foe], seed="t")
    enc.order = ["g1", "pc"]
    enc.ti = 0
    return pc, foe, enc


def test_bound_skips_and_ticks():
    pc, foe, enc = _duo()
    pc.x, pc.y, foe.x, foe.y = 1, 1, 2, 1
    foe.status["bound"] = 2
    before = pc.hp
    enc.ai_turn(foe)                       # связан — бьёт мимо, ход теряет
    assert pc.hp == before
    assert foe.status.get("bound") == 1    # тик на исходе своего хода


def test_asleep_woken_by_damage():
    pc, foe, enc = _duo()
    pc.x, pc.y, foe.x, foe.y = 1, 1, 2, 1
    foe.status["asleep"] = 3
    enc.act_attack(pc, "g1")
    assert "asleep" not in foe.status
    assert foe.hp < foe.max_hp


def test_afraid_does_not_attack():
    pc, foe, enc = _duo()
    pc.x, pc.y, foe.x, foe.y = 3, 3, 3, 4
    foe.status["afraid"] = 1
    before = pc.hp
    enc.ai_turn(foe)
    assert pc.hp == before


def test_view_exposes_status():
    _pc, foe, _enc = _duo()
    foe.status["bound"] = 2
    assert foe.view().get("status") == {"bound": 2}
    assert foe.incapacitated()
