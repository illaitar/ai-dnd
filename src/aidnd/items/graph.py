"""Item derivation graph: raw materials + processes + item nodes → any node's attribute vector by
traversal. `node_attrs` walks the chain from raw materials up (memoized, cycle-safe); `combine`
resolves NOVEL combinations deterministically — no LLM. Reuses the Phase-1 attribute vocabulary and
the clamp/quality machinery; the resulting vector feeds `derive_effects` for effects/worth.

Key functions
-------------
item_graph() -> dict : Load/cache the authored materials/processes/nodes graph.
node_attrs(id) -> dict : Attribute vector {attr:int} for a node, computed by derivation.
combine(ids, process) -> dict : Ad-hoc combination of nodes under a process (novel items).
combine_item(ids, process, ...) -> dict : combine → an item factsheet ready for derive_effects.
node_item(id, quality) -> dict : Materialize a node into a factsheet (attrs = node_attrs × quality).
node_lookup(name) -> id | None : Resolve a display name/alias to a node id.
"""

from __future__ import annotations

import json
import os
import re

from .attrs import QUALITY_MUL, _clamp
from .model import ATTRS

_GRAPH = None
_GPATH = os.path.join(os.path.dirname(__file__), "itemgraph.json")


def item_graph() -> dict:
    global _GRAPH
    if _GRAPH is None:
        with open(_GPATH, encoding="utf-8") as f:
            _GRAPH = json.load(f)
    return _GRAPH


def _clean(acc: dict) -> dict:
    return {a: _clamp(v) for a, v in acc.items() if a in ATTRS and _clamp(v) > 0}


def _merge(vectors) -> dict:
    """Combine input vectors: the strongest input wins per attribute (max)."""
    acc: dict = {}
    for v in vectors:
        for a, val in v.items():
            acc[a] = max(acc.get(a, 0), val)
    return acc


def _apply(acc: dict, deltas: dict) -> dict:
    for a, dv in (deltas or {}).items():
        acc[a] = acc.get(a, 0) + dv
    return acc


def node_attrs(node_id: str, graph: dict | None = None, _memo=None, _stack=None) -> dict:
    """Attribute vector for a node. Raw material → its base profile; derived node →
    max-combine(inputs) + process deltas + treatment deltas. Memoized per call; raises on a cycle or
    an unknown id. Clamped 0–100, zero attrs omitted."""
    g = graph or item_graph()
    memo = _memo if _memo is not None else {}
    if node_id in memo:
        return memo[node_id]
    if node_id in g["materials"]:
        memo[node_id] = _clean(dict(g["materials"][node_id]))
        return memo[node_id]
    node = g["nodes"].get(node_id)
    if node is None:
        raise KeyError(f"unknown graph node: {node_id!r}")
    stack = _stack or set()
    if node_id in stack:
        raise ValueError(f"cycle in derivation graph at {node_id!r}")
    stack = stack | {node_id}
    acc = _merge([node_attrs(f, g, memo, stack) for f in node.get("from", [])])
    _apply(acc, g["processes"].get(node.get("process", ""), {}))
    for t in node.get("treatments") or []:
        _apply(acc, g["processes"].get(t, {}))
    memo[node_id] = _clean(acc)
    return memo[node_id]


def node_form(node_id: str, graph: dict | None = None) -> str:
    g = graph or item_graph()
    return (g["nodes"].get(node_id) or {}).get("form", "")


def combine(input_ids: list, process: str, graph: dict | None = None) -> dict:
    """Resolve a NOVEL combination with no authored node: max-combine the inputs' vectors + the
    process deltas. Deterministic, no LLM. Returns {attr:int}."""
    g = graph or item_graph()
    acc = _merge([node_attrs(i, g) for i in input_ids])
    _apply(acc, g["processes"].get(process, {}))
    return _clean(acc)


def _as_attrs(vec: dict) -> dict:
    return {a: {"surface": v, "true": v} for a, v in vec.items()}


def combine_item(input_ids: list, process: str, form: str | None = None,
                 kind: str = "misc", name: str = "", graph: dict | None = None) -> dict:
    """combine() → an item factsheet {kind, name, form, attrs}. form defaults to the first input's
    form (the primary object being modified), so «стрела + заряд» stays a projectile."""
    g = graph or item_graph()
    f = form if form is not None else (node_form(input_ids[0], g) if input_ids else "")
    return {"kind": kind, "name": name or " + ".join(input_ids), "form": f,
            "attrs": _as_attrs(combine(input_ids, process, g))}


def node_item(node_id: str, quality: str = "plain", graph: dict | None = None) -> dict:
    """Materialize a node into an item factsheet — attrs = node_attrs × quality — ready for
    derive_effects / normalize."""
    g = graph or item_graph()
    node = g["nodes"].get(node_id) or {}
    mul = QUALITY_MUL.get(quality, 1.0)
    vec = {a: _clamp(v * mul) for a, v in node_attrs(node_id, g).items()}
    return {"kind": node.get("kind", "misc"), "name": node.get("name", node_id),
            "form": node.get("form", ""), "quality": quality, "attrs": _as_attrs(vec)}


def _toks(s: str) -> set:
    return set(re.findall(r"[а-яёa-z]+", s.lower()))


def node_lookup(name: str, graph: dict | None = None) -> str | None:
    """Resolve a display name/alias to a node id: exact, then case-insensitive exact, then whole-token
    containment — every WORD of the node id must appear as a word in the name (so «Кривой нож» → «нож»
    but «Порог таверны» does NOT match «рог»). A last-resort bridge; explicit `node` ids are primary.
    Prefers the most specific (longest) id. None if nothing matches."""
    g = graph or item_graph()
    keys = list(g["nodes"]) + list(g["materials"])
    if name in keys:
        return name
    nl = name.lower().strip()
    for k in keys:
        if k.lower() == nl:
            return k
    nt = _toks(name)
    best = None
    for k in keys:
        kt = _toks(k)
        if kt and kt <= nt and (best is None or len(k) > len(best)):   # all of the id's words are present
            best = k
    return best
