from aidnd.server.play.engine.world import _pc_heard


def test_zoneless_everyone_hears_L1():
    heard = _pc_heard(None, ["a", "b"], lambda p: "room", {}, [])
    assert heard == {"a": "L1", "b": "L1"}


def test_zoned_near_hears_far_does_not():
    # two zones with centroids; player at z1, 'near' at z1, 'far' at a distant z2
    z1 = {"id": "z1", "name": "z1", "cx": 0, "cy": 0}
    z2 = {"id": "z2", "name": "z2", "cx": 40, "cy": 40}   # far enough to be inaudible
    zn = {"z1": z1, "z2": z2}
    place = {"near": "z1", "far": "z2"}
    heard = _pc_heard(z1, ["near", "far"], lambda p: place[p], zn, [z1, z2])
    assert heard.get("near") == "L1"
    assert "far" not in heard   # too far → inaudible → not a hearer
