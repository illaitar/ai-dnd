"""Pure audibility math and fidelity helpers (no server/DB).

Key tests
---------
test_same_zone_is_l1        : a normal voice in your own zone is heard verbatim (L1).
test_distance_drops_tier    : the same voice two zones away drops to a lower tier.
test_far_zone_inaudible     : far enough → None (inaudible).
test_missing_centroid_none  : a zone without a centroid is treated as inaudible.
test_boost_lifts_tier       : boost=1 lifts L2→L1 (the listen primitive).
test_boost_promotes_l3_to_l2 : boost=1 lifts L3→L2 (wiring check for `listen`, Task 7).
"""

from aidnd.server.play.engine.sound import (
    audibility,
    audible_ambient,
    cutout,
    overheard_line,
    zone_source,
)


def _z(zid, cx=None, cy=None):
    z = {"id": zid}
    if cx is not None:
        z["cx"], z["cy"] = cx, cy
    return z


def _z_rank(t):
    """Numeric rank of a fidelity tier string ("L1"->1 ... "L3"->3); lower = louder/closer."""
    return int(t[1])


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


def test_boost_promotes_l3_to_l2():
    # heard = 0.8 - 0.045*12 = 0.26 -> in [t3=0.12, t2=0.35) -> L3 unboosted.
    # boost=1 lifts one tier -> L2. Neither call is None: the assertion is unambiguous.
    a, b = _z("z0", 0.0, 0.0), _z("z1", 12.0, 0.0)
    base = audibility(a, b, 0.8)
    boosted = audibility(a, b, 0.8, boost=1)
    assert base == "L3"
    assert boosted == "L2"
    assert _z_rank(boosted) < _z_rank(base)  # boost never lowers fidelity


def test_zone_source_by_object():
    z = {"id": "z0", "kind": "hall", "objects": [{"name": "очаг", "kind": "очаг"}]}
    src = zone_source(z)
    assert src and src["ambient_ru"] == "потрескивает очаг"


def test_zone_source_by_kind():
    assert zone_source({"id": "z1", "kind": "forge"})["loudness"] == 0.85


def test_zone_source_none():
    assert zone_source({"id": "z2", "kind": "table"}) is None


def test_cutout_is_deterministic():
    t = "караван из Хельгарда так и не пришёл третий день жду"
    assert cutout(t, "s1") == cutout(t, "s1")           # stable for a fixed seed
    assert "…" in cutout(t, "s1")                        # something was masked


def test_overheard_l1_verbatim():
    text, w = overheard_line("привет друг", "L1", "у очага", "s")
    assert text == "привет друг" and w == 0.18


def test_overheard_l3_presence_only():
    text, w = overheard_line("секрет", "L3", "у дальнего стола", "s")
    assert "секрет" not in text and "у дальнего стола" in text


def test_ambient_includes_near_source():
    zones = [{"id": "z0", "kind": "hall", "cx": 0.0, "cy": 0.0},
             {"id": "z1", "kind": "forge", "cx": 3.0, "cy": 0.0}]
    out = audible_ambient(zones, zones[0], {"z0": 1, "z1": 0})
    assert any("ковк" in s for s in out)               # the forge carries to the listener


def test_ambient_drops_distant_quiet_source():
    zones = [{"id": "z0", "kind": "hall", "cx": 0.0, "cy": 0.0},
             {"id": "z1", "kind": "hearth", "cx": 30.0, "cy": 0.0}]
    out = audible_ambient(zones, zones[0], {"z0": 1, "z1": 0})
    assert not any("огонь" in s for s in out)          # quiet hearth too far → silent
