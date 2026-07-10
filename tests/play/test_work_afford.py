from aidnd.server.play.engine.world import _afford_need


def test_post_object_retains_purpose_over_comfort():
    # a hot forge affords both comfort and purpose; at a post it must surface PURPOSE
    assert _afford_need({"comfort": 0.3, "purpose": 0.1}, "workshop", True)[0] == "purpose"


def test_non_post_object_uses_max_afford():
    assert _afford_need({"comfort": 0.3, "purpose": 0.1}, "tables", False)[0] == "comfort"


def test_fatigue_remaps_to_comfort_outside_beds():
    assert _afford_need({"fatigue": 0.4}, "tables", False)[0] == "comfort"


def test_fatigue_only_rate_does_not_keyerror_and_matches_source_value():
    # original bug: rate lookup on the REMAPPED need ("comfort") would KeyError against
    # an afford dict that only has "fatigue" — rate must come from the fatigue entry itself.
    need, rate = _afford_need({"fatigue": 0.4}, "tables", False)
    assert (need, rate) == ("comfort", 0.4)


def test_post_purpose_rate_is_purposes_own_magnitude_not_the_beaten_need():
    # purpose (0.1) is NOT the argmax (comfort=0.3 wins on magnitude) but the post-priority
    # branch still picks purpose — rate must be purpose's OWN value, not comfort's.
    need, rate = _afford_need({"comfort": 0.3, "purpose": 0.1}, "workshop", True)
    assert (need, rate) == ("purpose", 0.1)
