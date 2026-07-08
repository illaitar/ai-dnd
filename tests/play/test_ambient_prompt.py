"""The narrator snapshot carries audible ambient phrases so the DM can weave them
into prose (docs/sound-attention.md, Pillar 1)."""

from aidnd.server.play.engine.resolve import _ambient_note


def test_ambient_note_lists_phrases():
    zones = [{"id": "z0", "kind": "hall", "cx": 0.0, "cy": 0.0},
             {"id": "z1", "kind": "forge", "cx": 2.0, "cy": 0.0}]
    lv = {"zones": zones, "zonemap": {"P": "z0"}, "occ": {"z0": 1}}
    note = _ambient_note(lv, listener_zone=zones[0], occupancy={"z0": 1, "z1": 0})
    assert "слышно:" in note and "ковк" in note


def test_ambient_note_empty_when_silent():
    lv = {"zones": [{"id": "z0", "kind": "hall", "cx": 0.0, "cy": 0.0}]}
    assert _ambient_note(lv, listener_zone=lv["zones"][0], occupancy={"z0": 1}) == ""
