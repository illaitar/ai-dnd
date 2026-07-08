"""World-lookup service — the narrator/arbiter "know/ask" tool call.

Key functions
-------------
_world_lookup(query: str, from_node: int | None = None) -> str : Truthful world facts (buildings
    with a route, locals) for the know/ask tool — never lets the model invent the city.
"""

from __future__ import annotations

from ..session.state import _S


def _world_lookup(query: str, from_node: int | None = None) -> str:
    """World lookup for know/ask tool call: buildings (with route from point), people (locals know locals).
    Answers ONLY with real graph/pool facts — never lets LLM hallucinate about the city."""
    from ..core import _binfo, _mark_seen  # lazy: core.py imports narrator.voice at module top

    city, people = _S.get("city"), _S.get("people") or {}
    if city is None:
        return "не припомню"
    q, outs = query.lower(), []
    for bid, kb in sorted(city.key_buildings.items()):
        info = _binfo(bid)
        nm = info["name"]
        words = (nm + " " + info["kind"]).lower().replace("«", " ").replace("»", " ").split()
        if any(w[:5] in q for w in words if len(w) > 3):
            _mark_seen(bid)  # told it — now you know, mark on map
            if from_node is not None:
                r = city.route(from_node, kb.node)
                if r.found:
                    outs.append(
                        f"{nm}: {r.bearing or 'недалеко'}, ~{max(1, len(r.nodes) - 1)} мин ходу"
                    )
                    continue
            outs.append(nm)
    for _pid, p in sorted(people.items()):
        first = p.name.split()[0].lower()
        if p.role in q or first in q or p.name.lower() in q:
            place = _binfo(p.work)["name"] if p.work else None
            outs.append(f"{p.name} — {p.role}" + (f", обычно в «{place}»" if place else ""))
        if len(outs) >= 3:
            break
    return "; ".join(outs[:3]) if outs else "точно не скажу — не знаю такого"
