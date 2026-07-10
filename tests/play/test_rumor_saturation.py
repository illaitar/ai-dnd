from aidnd.server.play.engine.session.config import PB
from aidnd.server.play.engine.world import _pick_rumor


def test_pick_rotates_by_seed():
    pool = ["a", "b", "c"]
    picks = {_pick_rumor(pool, ("n1", w), {}, 1.0) for w in range(6)}
    assert picks <= set(pool) and len(picks) > 1          # not a single constant


def test_pick_skips_hot_subjects():
    pool = ["a", "b"]
    for _ in range(10):
        assert _pick_rumor(pool, ("n1", 0), {"a": 1.0}, 1.0) == "b"   # 'a' hot → never picked


def test_pick_none_when_all_hot():
    assert _pick_rumor(["a", "b"], ("n1", 0), {"a": 1.0, "b": 1.0}, 1.0) is None


def test_pick_none_on_empty_pool():
    assert _pick_rumor([], ("n1", 0), {}, 1.0) is None


def test_saturation_over_repeated_offers():
    # a subject offered ~rumor_hot/rumor_warm times crosses hot then, after cooling, returns
    pool = ["x"]
    heat = {}
    offered = 0
    while _pick_rumor(pool, ("n", 0), heat, PB["rumor_hot"]) is not None:
        heat["x"] = heat.get("x", 0.0) + PB["rumor_warm"]     # simulate the tick's warm step
        offered += 1
        assert offered < 100                                  # guard
    assert offered >= 2                                       # moderate: lingers a few offers
    # cool it back below hot → offered again
    for _ in range(int(PB["rumor_hot"] / PB["rumor_cool"]) + 1):
        heat["x"] = max(0.0, heat["x"] - PB["rumor_cool"])
    assert _pick_rumor(pool, ("n", 0), heat, PB["rumor_hot"]) == "x"
