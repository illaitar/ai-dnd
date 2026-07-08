"""Zone centroids — store each zone's floorplan-rect center on its record.

The floorplan (plan_location) is deterministic, so we solve geometry once at
furnish time and persist (cx, cy) per zone; the runtime scene then has spatial
positions for audibility (docs/sound-attention.md) without recomputing layout.

Key functions
-------------
store_centroids(data) -> data : write cx,cy onto every zone present in the floorplan.
"""

from .floorplan import plan_location


def store_centroids(data: dict) -> dict:
    """Mutate data['zones'], setting cx,cy = rect center for each placed zone."""
    plan = plan_location(data)
    rects = {r["id"]: r for fl in plan.get("floors", []) for r in fl.get("zones", [])}
    for z in data.get("zones", []):
        r = rects.get(z["id"])
        if r:
            z["cx"] = r["x"] + r["w"] / 2
            z["cy"] = r["y"] + r["h"] / 2
    return data
