"""Scene geometry: the render coordinate layer over the city, and current-position zone lookup.

Key functions
-------------
_build_geom(city, xy, n2b, vis) -> dict : Light interactive render layer — road points, key-building
    labels, board post.
_scene_zones() -> list[dict] : Zones of current player position — live scene zones, else the
    building/street template.
"""

from __future__ import annotations

from aidnd.citygraph.model import NodeKind

from ..core import _binfo
from ..session.state import _S


def _build_geom(city, xy, n2b, vis) -> dict:
    """Light interactive layer over rich visual: coordinate system — render canvas 0 0 W H.
    Houses/streets/river/walls drawn by SVG itself (vis['inner']); click house → its NEAREST
    road point (h2n = h.node, NOT crossroad). Building labels above; _xy — node→xy for routing."""
    h2n = {h.id: h.node for h in city.houses.values()}
    road = (NodeKind.CROSSROAD, NodeKind.POINT, NodeKind.BRIDGE, NodeKind.GATE)
    points = [
        {
            "id": n,
            "x": round(xy[n][0], 1),
            "y": round(xy[n][1], 1),
        }  # ALL road nodes (not just crossroads)
        for n in xy
        if city.node_kind(n) in road
    ]
    keys = []
    for bid, kb in sorted(city.key_buildings.items()):
        keys.append(
            {
                "node": kb.node,
                "x": round(kb.x, 1),
                "y": round(kb.y, 1),
                "label": _binfo(bid)["label"],
                "bid": bid,
            }
        )
    cx, cy = vis["W"] / 2, vis["H"] / 2  # BOARD-POST: crossroad closest to center
    cross = [n for n in xy if city.node_kind(n) == NodeKind.CROSSROAD]
    plaza = min(cross, key=lambda n: (xy[n][0] - cx) ** 2 + (xy[n][1] - cy) ** 2) if cross else None
    if plaza is not None:
        keys.append(
            {
                "node": plaza,
                "x": round(xy[plaza][0], 1),
                "y": round(xy[plaza][1], 1),
                "label": "Доска",
                "bid": "board:plaza",
            }
        )
    return {
        "viewBox": [0, 0, vis["W"], vis["H"]],
        "svg": vis["inner"],
        "h2n": h2n,
        "points": points,
        "keys": keys,
        "plaza": plaza,
        "_xy": {n: [round(xy[n][0], 1), round(xy[n][1], 1)] for n in xy},
    }


def _scene_zones() -> list[dict]:
    """Zones of CURRENT player position — wherever: live scene (interior OR street) — truth;
    no scene — building template or street template of node. Single source for intent."""
    lv = _S.get("live") or {}
    if lv.get("zones") and lv.get("loc") == _S.get("loc"):
        return lv["zones"]
    from aidnd.server.play.engine.zones import building_zones
    if _S.get("inside"):
        return building_zones(_S["inside"])[1]
    bid = (_S.get("cr2b") or {}).get(_S.get("loc"))
    if bid:
        return building_zones(bid)[1]
    from aidnd.worldgen.furnish import zones_for
    kind = "площадь" if _S.get("loc") == (_S.get("geom") or {}).get("plaza") else "улица"
    return zones_for(kind, {}, kind="street")
