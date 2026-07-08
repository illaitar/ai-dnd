"""Adapter between world and society: builds available locations from real buildings/graph for
each NPC and runs their routine (aidnd.society). Here — only "translation" of world to candidates;
selection logic lives in society.

routine_step() — cheap recalculation of spots for ALL residents based on needs (replacement for
hardcoded _routine_spot). Called on time phase change from world tick (see engine.world._world_tick).

Key functions
-------------
routine_step(people, crof) -> None : Recalculate where each NPC is based on
  needs/traits/time; mutates placement and needs state.
predict(pid, phase=None) -> dict : Forecast NPC direction and purpose (node,
  kind, route) in a phase; deterministic query with no stored state.
forecast(pid) -> dict : Daily schedule as {phase: activity_kind} for UI
  display; shows how NPC spends each day phase.
crosses(pid, node, phase=None) -> bool : Check if NPC route passes through
  node in a phase; used for ambush planning.
set_commit(pid, kind, node=None, until_gt=None) -> None : Override routine
  with commitment (follow/shift/errand); can expire.
clear_commit(pid) -> None : Remove commitment override, freeing routine.
"""

from __future__ import annotations

import random

from aidnd import society
from aidnd.server.play.engine.core import _S, _gt, _phase, _store, _wid


def _place_index(people, keynode: dict) -> dict:
    """City nodes by place types (from building fact sheets): {kind: [node,...]}. Computed once per step."""
    idx: dict = {}
    for bid, node in keynode.items():
        data = (_store().get_building(_wid(), bid) or {}).get("data") or {}
        for kind in society.kinds_of(data):
            idx.setdefault(kind, []).append(node)
    return idx


def _gate_ok(kind: str, p) -> bool:
    """Who a place applies to: work — if employed; patrol — guards; prowl — rogues/malice."""
    pk = society.PLACE[kind]
    if pk.gate == "job":
        return bool(p.work)
    if pk.gate == "guard":
        return p.role == "стражник"
    if pk.gate == "rogue":
        return (
            p.role in ("головорез", "бродяга", "наёмник")
            or p.state.config.traits.get("malice", 0.5) > 0.6
        )
    return True


_BCAP: dict = {}
_NOT_SOCIAL = {"private", "storage", "cell", "beds"}   # not "common hall" — don't count as crowd
_NONCRAFT = {"горожанин", "дитя", "старик"}            # no craft — homes NOT productive (D2 dependents)


def _building_cap(bid) -> int:
    """Building capacity = Σ cap of social zones (places "where you can be with people"); cached by bid."""
    if bid not in _BCAP:
        from aidnd.server.play.engine.zones import building_zones
        _zd, zs = building_zones(bid)
        cap = sum(int(z.get("cap", 0)) for z in zs if z.get("kind") not in _NOT_SOCIAL)
        _BCAP[bid] = max(6, cap) if zs else 14        # reasonable default without zones
    return _BCAP[bid]


def _candidates(p, place_idx: dict, keynode: dict, kps: list, rng,
                work_kinds: dict | None = None, load: dict | None = None,
                n2b: dict | None = None) -> list:
    """Available places for this NPC as list of society.Candidate. Home/work personal;
    tavern/temple/market — "own" from city (seeded choice); street/patrol/prowl — graph node."""
    out = []
    home = p.home if p.home is not None else (rng.choice(kps) if kps else None)
    if home is not None:
        out.append(society.Candidate("home", home))
    if p.work:
        wk = (work_kinds or {}).get(p.work)          # establishment window: tavern calls in evening
        out.append(society.Candidate("work", keynode.get(p.work, home), window_kind=wk))
    elif home is not None and p.role not in _NONCRAFT:  # craftsman works AT HOME (historical norm)
        out.append(society.Candidate("work", home))
    for kind in ("tavern", "temple", "market"):  # tied to buildings places
        nodes = place_idx.get(kind)
        if nodes and _gate_ok(kind, p):
            node = nodes[hash((p.state.config.id, kind)) % len(nodes)]
            if load is not None and n2b is not None:  # capacity: full building doesn't call
                bid = n2b.get(node)
                if bid and load.get(node, 0) >= _building_cap(bid):
                    continue
            out.append(society.Candidate(kind, node))
    for kind in ("street", "patrol", "prowl"):  # mobile places — graph node
        if kps and _gate_ok(kind, p):
            out.append(
                society.Candidate(
                    kind, kps[hash((p.state.config.id, kind, _gt() // 1440)) % len(kps)]
                )
            )
    return out


def _place_context(people: dict):
    """Context of city places (building index, work windows) — shared for routine_step and predict."""
    keynode, kps = _S.get("keynode") or {}, _S.get("kps") or []
    place_idx = _place_index(people, keynode)
    work_kinds = {}                                  # bid → establishment type (work window)
    for bid in keynode:
        data = (_store().get_building(_wid(), bid) or {}).get("data") or {}
        ks = society.kinds_of(data)
        if ks:
            work_kinds[bid] = ks[0]
    return keynode, kps, place_idx, work_kinds


# ── LAYER A: INTENT as FORECAST (docs/citysim.md §A) — query-shaped, zero persist ──


def predict(pid: str, phase: str | None = None) -> dict:
    """Where and WHY an NPC is headed in a phase (run utility forward by CURRENT needs + phase
    windows; approx — phase windows dominate daily rhythm). Commitments override utility.
    Returns {node, kind, route}. Zero stored state — deterministic query."""
    people = _S.get("people") or {}
    crof = _S.get("crof") or {}
    p = people.get(pid)
    if p is None:
        return {"node": None, "kind": None, "route": []}
    phase = phase or _phase()
    node = _commit_node(pid, phase, people, crof)     # commitment (follow/shift/appt)?
    kind = None
    if node is None:
        keynode, kps, place_idx, work_kinds = _place_context(people)
        rng = random.Random(f"pred|{pid}|{phase}|{_gt() // 30}")
        cands = _candidates(p, place_idx, keynode, kps, rng, work_kinds=work_kinds)
        c = society.routine.choose_c(p.state.needs, p.state.config.traits, cands, phase, rng,
                                     stay=crof.get(pid))
        if c is not None:
            node, kind = c.node, c.kind
    else:
        kind = (_S.get("commit") or {}).get(pid, {}).get("kind", "appointment")
    cur = crof.get(pid)
    route = []
    if node is not None and cur is not None and cur != node:
        city = _S.get("city")
        if city is not None:
            r = city.route(cur, node)
            route = list(r.nodes) if getattr(r, "found", False) else [cur, node]
    return {"node": node, "kind": kind, "route": route}


def forecast(pid: str) -> dict:
    """NPC's daily schedule: {phase: activity_kind} — for schedule card (observability)."""
    return {ph: predict(pid, ph)["kind"] for ph in ("morning", "day", "evening", "night")}


def crosses(pid: str, node: int, phase: str | None = None) -> bool:
    """Does NPC route pass through node in phase — intercept/ambush at PLAN level, not position."""
    pr = predict(pid, phase)
    return node in (pr["route"] or []) or pr["node"] == node


def set_commit(pid: str, kind: str, node: int | None = None, until_gt: int | None = None) -> None:
    """Commitment (follow/shift/errand) — routine override for external systems.
    kind=follow: node dynamic (player node); crit-need still pulls away to eat/sleep."""
    _S.setdefault("commit", {})[pid] = {"kind": kind, "node": node, "until": until_gt}


def clear_commit(pid: str) -> None:
    (_S.get("commit") or {}).pop(pid, None)


_CRIT = {"fatigue": 0.85, "hunger": 0.82}             # need above — overrides follow (RimWorld)


def _commit_node(pid: str, phase: str, people: dict, crof: dict) -> int | None:
    """Node override by commitment (priority flee>appointment>shift>follow>errand).
    follow yields to crit-need (hungry companion leaves to eat). None — routine free."""
    c = (_S.get("commit") or {}).get(pid)
    if not c:
        return None
    if c.get("until") is not None and _gt() > c["until"]:
        clear_commit(pid)
        return None
    kind = c["kind"]
    if kind == "follow":
        st = people.get(pid)
        if st is not None and any(st.state.needs.get(n, 0) >= thr for n, thr in _CRIT.items()):
            return None                               # crit-need matters more — leaves follow
        return _S.get("loc")                          # to player (dynamic)
    return c.get("node")


def routine_step(people: dict, crof: dict, pin: set | None = None) -> None:
    """Recalculate where each resident is based on needs/traits/time. Cheap (no LLM/DB in loop):
    one building index + O(people×places) utility. Mutates crof (spot) and needs in people[*].state.
    `pin` — residents present in the player's live scene (ring A owns them): skipped here so ring A
    and ring B never both move the same NPC (docs/loop.md LOD rings)."""
    phase = _phase()
    keynode, kps, place_idx, work_kinds = _place_context(people)
    gt = _gt()
    node2kind = {}  # where NPC stands now → place type (sates needs)
    for kind, nodes in place_idx.items():
        for n in nodes:
            node2kind.setdefault(n, kind)
    from aidnd.server.play.engine import deeds as _deeds

    # commitments: on time routine pulls both to meeting; overdue = promise broken
    appts: dict = {}
    for d in _deeds.promises_active():
        node = d["data"].get("node")
        due = d["data"].get("due")
        if node is None:
            continue
        if due == phase:
            appts.setdefault(d["actor"], node)
            appts.setdefault(d["obj"], node)
        elif gt > d["data"].get("made_gt", gt) + 300 and due != phase:
            both = crof.get(d["actor"]) == node and crof.get(d["obj"]) == node
            _deeds.promise_resolve(d, both)
            actor_p, obj_p = people.get(d["actor"]), people.get(d["obj"])
            if actor_p and obj_p:
                if both:
                    actor_p.state.memory.add(f"я сдержал(а) слово ({obj_p.name})", gt // 10, 0.55,
                                             about=[d["obj"]])
                    obj_p.state.memory.add(f"{actor_p.name} сдержал(а) слово", gt // 10, 0.55,
                                           about=[d["actor"]])
                    obj_p.state.rel(d["actor"])["trust"] = min(
                        1.0, obj_p.state.rel(d["actor"]).get("trust", 0) + 0.15)
                else:
                    obj_p.state.memory.add(f"{actor_p.name} НЕ сдержал(а) слово", gt // 10, 0.6,
                                           about=[d["actor"]])
                    obj_p.state.rel(d["actor"])["trust"] = max(
                        -1.0, obj_p.state.rel(d["actor"]).get("trust", 0) - 0.25)
    n2b = _S.get("cr2b") or {}
    kind_of: dict = _S.setdefault("crof_kind", {})    # pid → activity kind (for GIF/observability)
    load: dict = {}                                   # node → how many already there (for capacity)
    last = _S.setdefault("needs_gt", {})
    order = sorted(people.items(), key=lambda kv: (kv[1].work is None, kv[0]))  # workers first
    for pid, p in order:
        if pin and pid in pin:  # ring A owns present NPCs — don't move them from the sim (no A/B overlap)
            continue
        st = p.state
        mins = max(0, gt - last.get(pid, gt - 360))  # time since last step (start: ~phase)
        here = node2kind.get(crof.get(pid))  # where stood → what sated
        if here is None and crof.get(pid) == p.home:
            here = "home"
        rng = random.Random(f"rout|{pid}|{phase}|{gt // 30}")
        # needs advance ALWAYS (even under commitment — else follow won't yield to crit-need)
        society.advance(st.needs, mins,
                               society.PLACE[here].sates if here in society.PLACE else {})
        cnode = appts.get(pid) or _commit_node(pid, phase, people, crof)  # commitment?
        if cnode is not None:                         # override: meeting place/shift/after player
            node, akind = cnode, ((_S.get("commit") or {}).get(pid, {}).get("kind")
                                  or "appointment")
        else:
            cands = _candidates(p, place_idx, keynode, kps, rng, work_kinds=work_kinds,
                                load=load, n2b=n2b)
            node, akind = society.routine.choose(st.needs, st.config.traits, cands, phase, rng,
                                                 stay=crof.get(pid)), None
            if node is not None:
                akind = next((c.kind for c in cands if c.node == node), None)
        if node is not None:
            crof[pid] = node
            kind_of[pid] = akind
        if node is not None and n2b.get(node):        # stood in building — took spot
            load[node] = load.get(node, 0) + 1
        last[pid] = gt
