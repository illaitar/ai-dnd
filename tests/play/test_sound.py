"""Pure audibility math and fidelity helpers (no server/DB).

Key tests
---------
test_same_zone_is_l1        : a normal voice in your own zone is heard verbatim (L1).
test_distance_drops_tier    : the same voice two zones away drops to a lower tier.
test_far_zone_inaudible     : far enough → None (inaudible).
test_missing_centroid_none  : a zone without a centroid is treated as inaudible.
test_boost_lifts_tier       : boost=1 lifts L2→L1 (the listen primitive).
"""

from aidnd.server.play.engine.sound import audibility


def _z(zid, cx=None, cy=None):
    z = {"id": zid}
    if cx is not None:
        z["cx"], z["cy"] = cx, cy
    return z


def test_same_zone_is_l1():
    z = _z("z0", 5.0, 5.0)
    assert audibility(z, z, 0.8) == "L1"


def test_distance_drops_tier():
    a, b = _z("z0", 0.0, 0.0), _z("z1", 10.0, 0.0)
    assert audibility(a, b, 0.8) == "L2"          # heard = 0.8 − 0.045·10 = 0.35


def test_far_zone_inaudible():
    a, b = _z("z0", 0.0, 0.0), _z("z1", 40.0, 0.0)
    assert audibility(a, b, 0.8) is None          # heard = 0.8 − 1.8 < 0


def test_missing_centroid_none():
    a, b = _z("z0", 0.0, 0.0), _z("z1")           # b unplaced
    assert audibility(a, b, 0.8) is None


def test_boost_lifts_tier():
    a, b = _z("z0", 0.0, 0.0), _z("z1", 10.0, 0.0)
    assert audibility(a, b, 0.8, boost=1) == "L1"  # L2 lifted one tier
