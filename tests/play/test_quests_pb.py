from aidnd.server.play.engine.core import PB


def test_inc2_quest_pb_present():
    assert PB["quest_topk"] == 4
    assert PB["quest_offer_days"] == 2
    assert PB["quest_w_rare"] == 1.0
    assert PB["quest_w_peak"] == 1.0
    assert PB["quest_w_near"] == 0.6
    assert PB["quest_w_fresh"] == 0.8
    assert PB["quest_twist_p"] == 0.7
