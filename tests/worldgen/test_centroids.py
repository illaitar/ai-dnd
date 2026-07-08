"""Zone centroids: furnish stores each zone's floorplan-rect center on the zone record.

Key tests
---------
test_centroid_is_rect_center : every placed zone gets cx,cy = rect (x+w/2, y+h/2).
test_idempotent              : running twice does not change the centroids.
"""

from aidnd.worldgen.centroids import store_centroids

from aidnd.worldgen.floorplan import plan_location


def _building():
    return {"name": "Тестовый двор", "type": "таверна", "size": "medium",
            "zones": [{"id": "z0", "kind": "hall", "name": "общий зал"},
                      {"id": "z1", "kind": "table", "name": "стол у окна"}]}


def test_centroid_is_rect_center():
    data = store_centroids(_building())
    rects = {r["id"]: r for fl in plan_location(data)["floors"] for r in fl["zones"]}
    for z in data["zones"]:
        if z["id"] in rects:
            r = rects[z["id"]]
            assert z["cx"] == r["x"] + r["w"] / 2
            assert z["cy"] == r["y"] + r["h"] / 2


def test_idempotent():
    data = store_centroids(_building())
    snap = [(z.get("cx"), z.get("cy")) for z in data["zones"]]
    store_centroids(data)
    assert [(z.get("cx"), z.get("cy")) for z in data["zones"]] == snap
