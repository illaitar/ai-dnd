"""Live scene zones: choose zone by NEEDS — recursion of society-scoring into building
(docs/locations.md, case 13: hungry to table, tired to bed, antisocial to shade).

Scoring and choosing — pure functions (tested without server and LLM). building_zones —
resolve building layout: world → pool by name → pool by type (bridge before materialization step 2).

Key functions
--------------
building_zones(bid) -> tuple : Resolve zones by name or type from pool.
zone_score(state, zone, load) -> float : Score zone fit by needs and capacity.
choose_zone(state, zones, load, rng, ...) -> str : Best zone with hysteresis.
assign_zones(states, zones, seed, ...) -> dict : Deterministic placement.
"""

from __future__ import annotations

import random

POST_BONUS = 3.0            # worker post holds worker
CROWD_PENALTY = 0.35        # crowding beyond capacity repels
MOVE_HYSTERESIS = 0.22      # relocate only if new zone is NOTICEABLY better
SERVICE_KINDS = {"private", "storage", "cell"}   # service zones — not for visitors


def building_zones(bid) -> tuple[dict, list]:
    """Building layout with zones: world → pool by name → pool by type. ({}, []) if no zones."""
    from aidnd.server.play.engine.core import _pool, _store, _wid
    if not bid:
        return {}, []
    data = (_store().get_building(_wid(), bid) or {}).get("data") or {}
    if not data.get("zones"):
        t = str(data.get("type") or "").lower()
        cand = [r for r in _pool().pool_buildings("key") if r["data"].get("zones")]
        row = (next((r for r in cand if r["data"].get("name") == data.get("name")), None)
               or next((r for r in cand
                        if t and str(r["data"].get("type") or "").lower() == t), None)
               or next((r for r in cand
                        if t and (t in r["btype"].lower() or r["btype"].lower() in t)), None))
        if row:
            data = {**data, "zones": row["data"]["zones"], "layout": row["data"].get("layout")}
    return data, (data.get("zones") or [])


def zone_score(state, zone: dict, load: int = 0) -> float:
    """How much zone covers person's needs: afford of its ITEMS × pressure of needs
    + privacy to taste (antisocial drawn to shade, sociable to noise) − crowding."""
    s = 0.04
    needs = getattr(state, "needs", None) or {}
    for o in zone.get("objects") or []:
        for need, rate in (o.get("afford") or {}).items():
            s += rate * max(0.0, needs.get(need, 0.0) - 0.2) * 2.0
    traits = getattr(getattr(state, "config", None), "traits", None) or {}
    soc = traits.get("sociability", 0.5)
    s += zone.get("privacy", 0.3) * (0.55 - soc) * 0.5
    s -= zone.get("noise", 0.4) * max(0.0, 0.45 - soc) * 0.25
    cap = zone.get("cap", 4)
    if load >= cap:
        s -= CROWD_PENALTY * (1 + load - cap)
    return s


def choose_zone(state, zones: list, load: dict, rng: random.Random,
                role: str = "", works_here: bool = False, current: str | None = None):
    """Zone for person: worker post holds; else best by needs; hysteresis
    against jitter (moved — means had reason). Don't offer locked zones."""
    if works_here and role:
        rl = role.lower()
        zp = next((z for z in zones
                   if z.get("post") and (z["post"] in rl or rl in z["post"])), None)
        if zp is not None:
            return zp["id"]
    open_z = [z for z in zones if not z.get("lockable")
              and (works_here or z["kind"] not in SERVICE_KINDS)]
    if not open_z:
        open_z = [z for z in zones if not z.get("lockable")]
    if not open_z:
        return None
    best = max(open_z,
               key=lambda z: zone_score(state, z, load.get(z["id"], 0)) + rng.uniform(0, 0.03))
    if current:
        cur = next((z for z in open_z if z["id"] == current), None)
        if cur is not None and (zone_score(state, best, load.get(best["id"], 0))
                                < zone_score(state, cur, load.get(current, 0)) + MOVE_HYSTERESIS):
            return current
    return best["id"]


def assign_zones(states: dict, zones: list, seed: str,
                 roles: dict | None = None, workers: set | None = None) -> dict:
    """Initial placement of party by zones — deterministic by seed, posts first."""
    rng = random.Random(seed)
    out: dict = {}
    load: dict = {}
    ordered = sorted(states, key=lambda p: (p not in (workers or set()), p))
    for pid in ordered:
        zid = choose_zone(states[pid], zones, load, rng,
                          role=(roles or {}).get(pid, ""),
                          works_here=pid in (workers or set()))
        out[pid] = zid
        if zid:
            load[zid] = load.get(zid, 0) + 1
    return out
