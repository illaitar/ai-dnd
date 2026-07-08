"""Overheard conversation lines are rendered at the audibility tier between the
speaker's zone and the player's zone.

Key tests
---------
test_same_zone_verbatim : speaker in the player's zone → L1, verbatim feed text.
test_far_zone_presence  : speaker far away → L3, presence-only text (no content).
test_out_of_earshot_none: no centroids / inaudible → None (caller bumps murmur).
"""

from aidnd.server.play.engine.world import _overheard

PZ = {"id": "z0", "cx": 0.0, "cy": 0.0}


def test_same_zone_verbatim():
    tier, text, w = _overheard("тайна каравана", PZ, PZ, "у очага", "seed")
    assert tier == 1 and text == "тайна каравана"


def test_far_zone_presence():
    far = {"id": "z1", "cx": 12.0, "cy": 0.0}
    tier, text, w = _overheard("тайна каравана", PZ, far, "у окна", "seed")
    assert tier == 3 and "тайна" not in text


def test_out_of_earshot_none():
    gone = {"id": "z2", "cx": 99.0, "cy": 0.0}
    assert _overheard("что угодно", PZ, gone, "далеко", "seed")[0] is None
