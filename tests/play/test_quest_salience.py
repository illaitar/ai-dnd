"""Salience воспроизводит арифметику §5 Step 2 число-в-число: A=3.14 > B=2.60."""
import math

from aidnd.server.play.engine.quests import salience as SAL


def _deeds(gt):
    return {"d123": {"id": "d123", "gt": gt - 1440, "verb": "promise",
                     "data": {"made_gt": gt - 1440}}}


def _seed(pattern, giver, villain):
    return {"pattern": pattern, "giver": giver, "cast": {"villain": villain},
            "evidence": ["d123"]}


def test_helpers_reproduce_spec_numbers():
    assert SAL.rarity(0) == 1.0
    assert SAL.rarity(1) == 0.5
    assert SAL.freshness(0, 1440) == 0.8            # возраст 1 день → 1 − 1/5
    assert SAL.proximity(7, 7, False) == 1.0
    assert SAL.proximity(4, 7, True) == 0.6
    assert SAL.proximity(4, 7, False) == 0.2


def test_score_A_gt_B_number_for_number(monkeypatch):
    from aidnd.server.play.engine.core import PB
    for k, v in {"quest_w_rare": 1.0, "quest_w_peak": 1.0, "quest_w_near": 0.6,
                 "quest_w_fresh": 0.8}.items():
        monkeypatch.setitem(PB, k, v)
    gt = 3 * 1440
    ctx = {"recent": {"kin_debt": 0, "broken_promise": 1},
           "aff_edges": {("npc:dunn", "npc:ralf"): -0.4, ("npc:marta", "npc:ralf"): -0.6},
           "deeds": _deeds(gt), "prox": {"npc:dunn": 1.0, "npc:marta": 0.6}, "now_gt": gt}
    a = SAL.score(_seed("kin_debt", "npc:dunn", "npc:ralf"), ctx)
    b = SAL.score(_seed("broken_promise", "npc:marta", "npc:ralf"), ctx)
    assert math.isclose(a, 3.14, abs_tol=1e-9)
    assert math.isclose(b, 2.60, abs_tol=1e-9)
    assert a > b


def test_score_resolves_prefixed_deed_and_ignores_agenda_anchor():
    ctx = {"recent": {}, "aff_edges": {}, "deeds": _deeds(1440), "prox": {}, "now_gt": 1440}
    bare = SAL.score(_seed("kin_debt", "npc:dunn", "npc:ralf"), ctx)
    prefixed = _seed("kin_debt", "npc:dunn", "npc:ralf")
    prefixed["evidence"] = ["deed:d123", "agenda:npc:dunn:0"]
    assert SAL.score(prefixed, dict(ctx, deeds=_deeds(1440))) == bare
