"""Inc3 — transit as derived state. A short hop is an instant crof flip; a long hop writes a transit
row and defers the flip to arrive_gt. _transit_node derives position O(1); _here is transit-aware
(mid-transit at the derived node; lazy flip on arrival) while _here_settled excludes walkers so a
venue who-set is unaffected. A street scene sees a pass-through walker. No LLM."""
from aidnd.server.play.engine import core, worldsim
from aidnd.server.play.engine.core import _here, _here_settled
from aidnd.server.play.engine.session.config import PB


def _reset():
    d = core._S._d()
    saved = dict(d)
    d.clear()
    d.update(gt=21360, transit={})
    return saved, d


def test_transit_node_derivation_at_three_timestamps():
    row = {"from": 12, "to": 47, "depart_gt": 21360, "arrive_gt": 21365,
           "path": [12, 19, 26, 33, 40, 47]}
    assert worldsim._transit_node(row, 21360) == 12          # step 0
    assert worldsim._transit_node(row, 21362) == 26          # step 2 (step_min=1)
    assert worldsim._transit_node(row, 21365) == 47          # arrived → destination
    assert worldsim._transit_node(row, 99999) == 47          # clamped past the end


def test_here_transit_aware_and_lazy_flip():
    saved, d = _reset()
    try:
        crof = {"p_mara": 12}                                # origin still in crof
        d["crof"] = crof
        d["transit"] = {"p_mara": {"from": 12, "to": 47, "depart_gt": 21360, "arrive_gt": 21365,
                                   "path": [12, 19, 26, 33, 40, 47]}}
        d["gt"] = 21362
        assert "p_mara" in _here(26, crof)                   # mid-transit: at derived node 26
        assert "p_mara" not in _here(47, crof)               # not yet at destination
        assert _here_settled(12, crof) == []                 # settled view: NOT at origin (en route)
        d["gt"] = 21365
        assert "p_mara" in _here(47, crof)                   # arrival → at destination
        assert crof["p_mara"] == 47                          # lazy flip mutated crof
        assert "p_mara" not in d["transit"]                  # row deleted on flip
    finally:
        d.clear(); d.update(saved)


def test_short_hop_is_instant_no_row():
    saved, d = _reset()
    try:
        assert PB["transit_min_steps"] == 3
        # a 1-step hop [44,47] < 3 → routine_step must flip crof immediately, write no row.
        # (verified structurally: worldsim._plan_move returns instant for a short path — see impl)
        node, row = worldsim._plan_move("p_roza", 44, [44, 47], 21360)
        assert row is None and node == 47                    # instant flip, no transit row
        # a 5-step hop ≥ 3 → a row, crof stays at origin (node None means 'do not flip now')
        node2, row2 = worldsim._plan_move("p_mara", 12, [12, 19, 26, 33, 40, 47], 21360)
        assert node2 is None and row2 is not None
        assert row2["arrive_gt"] == 21360 + 5 * PB["step_min"]
    finally:
        d.clear(); d.update(saved)


def test_venue_who_set_unaffected_by_a_cross_town_walker():
    saved, d = _reset()
    try:
        crof = {"host": 47, "guest": 47, "p_mara": 12}
        d["crof"] = crof
        d["transit"] = {"p_mara": {"from": 12, "to": 99, "depart_gt": 21360, "arrive_gt": 21400,
                                   "path": [12, 19, 26, 99]}}   # crosses none of {47}
        d["gt"] = 21362
        assert set(_here_settled(47, crof)) == {"host", "guest"}   # venue who-set: settled only
    finally:
        d.clear(); d.update(saved)


def test_transit_of_reports_in_transit():
    saved, d = _reset()
    try:
        d["transit"] = {"p_mara": {"from": 12, "to": 47, "depart_gt": 21360, "arrive_gt": 21365,
                                   "path": [12, 19, 26, 33, 40, 47]}}
        d["gt"] = 21362
        t = worldsim.transit_of("p_mara")
        assert t and t["kind"] == "в пути" and t["node"] == 26 and t["to"] == 47
        assert worldsim.transit_of("nobody") is None
    finally:
        d.clear(); d.update(saved)
