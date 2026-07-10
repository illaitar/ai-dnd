from aidnd.server.play.engine.world import _afford_need


def test_post_object_retains_purpose_over_comfort():
    # a hot forge affords both comfort and purpose; at a post it must surface PURPOSE
    assert _afford_need({"comfort": 0.3, "purpose": 0.1}, "workshop", True) == "purpose"


def test_non_post_object_uses_max_afford():
    assert _afford_need({"comfort": 0.3, "purpose": 0.1}, "tables", False) == "comfort"


def test_fatigue_remaps_to_comfort_outside_beds():
    assert _afford_need({"fatigue": 0.4}, "tables", False) == "comfort"
