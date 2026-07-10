"""Bridge to procedural generator (Voronoi diagram, etc.) → clean city graph.

The generator itself (`citygraph/render.py`, citygen.js port) is not exposed: external code works
only with City/CityParams. Here we merely extract neutral geometry (streets, houses, bridges,
river, wall, gates) and hand it to the graph.

Key functions
-------------
generate(params) -> City : run the Voronoi generator and wrap the raw geometry into a movement
    graph. The single public entry for "make me a city".
visual(params, ...) -> dict : the RICH SVG the /citydebug stand and the game map both render
    (full houses/river/walls); returns inner-SVG + canvas W×H so the interactive player layer
    overlays without coordinate shifts.
_citygen() : return the self-contained `render` module (build_city / render_svg). Kept as a thin
    accessor so call sites (routes_citydebug, this file) stay unchanged after the move out of
    server/web; it now backs a normal package import instead of the old importlib-by-path hack.
_extract / _gate_points : raw generator dict → neutral geometry contract, honouring river/walls.
"""

from __future__ import annotations

from . import render as _render_mod
from .graph import City
from .params import CityParams


def _citygen():
    """Self-contained generator (build_city / render_svg) — now a normal package module."""
    return _render_mod


def _gate_points(gate_edges, wall_poly) -> list:
    """Gates → points. Generator's gate_edges — INDICES of wall contour edges (take edge midpoint)."""
    out, n = [], len(wall_poly)
    for ge in gate_edges or []:
        try:
            if isinstance(ge, int):
                if 0 <= ge < n:
                    a, b = wall_poly[ge], wall_poly[(ge + 1) % n]
                    out.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
            elif isinstance(ge, dict) and ge.get("a") and ge.get("b"):
                a, b = ge["a"], ge["b"]
                out.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
            elif isinstance(ge, (list, tuple)) and len(ge) >= 2:
                a, b = ge[0], ge[1]
                out.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
        except (TypeError, IndexError, ValueError):
            pass
    return out


def _extract(m: dict, p: CityParams) -> dict:
    """Raw generator geometry → neutral contract for City. Honors river/walls flags."""
    streets = m.get("streets") or {"nodes": [], "adj": []}
    nodes = [(float(x), float(y)) for x, y in streets["nodes"]]
    adj = [list(a) for a in streets["adj"]]
    houses = [{"id": h["id"], "x": h["x"], "y": h["y"]} for h in m.get("hits", []) if h.get("house")]
    keys = [{"id": h.get("id"), "name": h.get("name", ""), "kind": h.get("kind", ""),
             "x": h["x"], "y": h["y"]} for h in m.get("hits", []) if h.get("landmark")]
    if p.river:
        river = {"pts": [(float(x), float(y)) for x, y in (m.get("river_pts") or [])],
                 "w": float(m.get("river_w", 0) or 0)}
        bridges = [(float(b["cross"][0]), float(b["cross"][1]))
                   for b in (m.get("bridges") or []) if b.get("cross")]
    else:
        river, bridges = {"pts": [], "w": 0}, []
    wall_poly = m.get("wall_poly") or []
    walls = [(float(x), float(y)) for x, y in wall_poly] if p.walls else []
    gates = _gate_points(m.get("gate_edges"), wall_poly) if p.walls else []
    return {"nodes": nodes, "adj": adj, "houses": houses, "keys": keys,
            "river": river, "bridges": bridges, "walls": walls, "gates": gates}


def generate(params: CityParams) -> City:
    """Generate city by parameters and return a ready graph with movement system."""
    p = params.normalized()
    m = _citygen().build_city(p.seed, p.width, p.height, buildings=[], key_houses=[])
    return City(p, _extract(m, p))


def visual(params: CityParams, chrome: bool = True, interactive: bool = False) -> dict:
    """Rich city visual — SAME render as on /citydebug (full houses with roofs, river,
    walls, bridges, plaza, districts). Same build_city(seed,W,H) → one coordinate system 0 0 W H
    with graph, so interactive layer (player figure) sits on top without coordinate shifts.

    interactive=True — each house becomes a clickable polygon `class="h" data-id="<house-id>"`
    (by this id the graph returns the house's intersection). Built-in render script/style is removed in this case —
    the game front handles clicks itself. Returns INNER SVG content + canvas dimensions W×H.
    """
    p = params.normalized()
    cg = _citygen()
    m = cg.build_city(p.seed, p.width, p.height, buildings=[], key_houses=[])
    full = cg.render_svg(m, chrome=chrome, marks=False, interactive=interactive)
    si = full.find("<style>.h{")                    # strip embedded interactive style+script
    if si != -1:
        se = full.find("</script>", si)
        full = full[:si] + (full[se + 9:] if se != -1 else full[si:])
    inner = full[full.index(">", full.index("<svg")) + 1: full.rindex("</svg>")]
    # clickable polygons (houses + townhall/castle keep) — the raster ID-map is painted from
    # these, so PNG-map clicks resolve to the same ids the old interactive .h layer used
    polys = []
    for w_ in m["wards"]:
        if w_.get("special") == "townhall":
            hid = next((h_["id"] for h_ in m["hits"] if h_.get("kind") == "townhall"), None)
            if hid:
                polys.append({"id": hid, "poly": w_["building"]})
            continue
        if w_.get("special") == "castle":
            hid = next((h_["id"] for h_ in m["hits"] if h_.get("kind") == "castle"), None)
            if hid:
                polys.append({"id": hid, "poly": w_["keep"]})
            continue
        for h_ in w_.get("houses", []):
            if not h_.get("garden"):
                polys.append({"id": h_["id"], "poly": h_["poly"]})
    return {"inner": inner, "W": int(m["W"]), "H": int(m["H"]),
            "hits": m["hits"], "polys": polys}
