from aidnd.server.play.engine.pc.luck import inspiration_decay, luck_from_karma


def test_luck_from_karma_smooth_and_bounded():
    assert luck_from_karma(0, 20, 4.0) == 0.0
    assert luck_from_karma(40, 20, 4.0) == 2.0        # smooth: 40/20
    assert luck_from_karma(1000, 20, 4.0) == 4.0      # capped +
    assert luck_from_karma(-1000, 20, 4.0) == -4.0    # capped −


def test_inspiration_decays_linearly_to_zero():
    assert inspiration_decay(5.0, 0, 90) == 5.0       # fresh
    assert inspiration_decay(5.0, 45, 90) == 2.5      # halfway
    assert inspiration_decay(5.0, 90, 90) == 0.0      # spent
    assert inspiration_decay(5.0, 120, 90) == 0.0     # past its life
    assert inspiration_decay(0.0, 10, 90) == 0.0      # nothing to decay


def test_karma_add_clamps_and_luck_tracks_it():
    from aidnd.server.play.engine.pc.luck import _pc_karma_add, _pc_luck
    from aidnd.server.play.engine.session.config import PB
    from aidnd.server.play.engine.session.state import _S

    _S["karma"], _S["insp"], _S["insp_gt"] = 0, 0.0, 0     # pre-seed → _luck_load is a no-op (no store)
    assert _pc_karma_add(50) == 50
    _pc_karma_add(10_000)                                  # clamps to the ceiling
    assert _pc_karma_add(0) == PB["karma_ceil"]
    assert _pc_luck() == luck_from_karma(PB["karma_ceil"], PB["karma_per_luck"], PB["luck_cap"])
    _pc_karma_add(-10_000)                                 # clamps to the floor
    assert _pc_karma_add(0) == -PB["karma_floor"]
