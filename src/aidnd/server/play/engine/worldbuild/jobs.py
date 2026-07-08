"""Settlement jobs: who works where, and key-building slot assignment from the pool.

Key functions
-------------
_assign_key_buildings(city) -> None : World created → distribute key building slots FROM POOL by
    slot type-hint (guild → guild). Written to live-DB once; re-entry reads ready data.
_plan_jobs(city, homes, roles) -> dict : DETERMINISTIC — who works at which venue (gravity —
    nearest by home) + who to reclassify.
"""

from __future__ import annotations

import random

from ..core import _binfo, _role_for_building
from ..session.persist import _pool, _store
from ..session.state import _wid


def _assign_key_buildings(city) -> None:
    """World created → distribute key building slots FROM POOL by slot type-hint (guild → guild).
    Written to live-DB once; re-entry reads ready data."""
    store, pool = _store(), _pool()
    have = store.building_ids(_wid())
    todo = [bid for bid in city.key_buildings if bid not in have]
    if not todo:
        return
    from aidnd.worldgen.enrichment import _SIGNIFICANT

    rows = pool.pool_buildings("key")
    rng = random.Random(f"bassign|{_wid()}")
    rng.shuffle(rows)
    used = set()

    def take(hint):
        h = hint.split()[0].lower()  # 'Temple of Fortune' → temple
        for r in rows:  # by type first, then any
            if r["id"] not in used and h in r["btype"].lower():
                used.add(r["id"])
                return r
        for r in rows:
            if r["id"] not in used:
                used.add(r["id"])
                return r
        return rows[0]

    for bid in sorted(todo):
        idx = int(bid.split(":")[1]) - 1
        hint = _SIGNIFICANT[idx % len(_SIGNIFICANT)]
        r = take(hint)
        kb = city.key_buildings[bid]
        store.save_building(_wid(), bid, True, kb.interior, r["data"].get("name"), r["data"])


# Profession categories (role→needs venue vs produces at home). Data in code — small table;
# scale up later to content/professions.json.
_VENUE_NEED = {"трактирщик", "лавочник", "оружейник", "жрец", "маг"}   # no venue ⟹ day laborer
_HOME_PRODUCER = {"дубильщик", "сапожник", "мельник", "кузнец", "знахарка"}  # craft at home
_MOBILE_ROLE = {"стражник", "головорез", "бродяга", "бард", "горожанин"}
_WORKCAP = {"таверн": 6, "трактир": 6, "гильд": 6, "игорн": 4, "лавк": 3, "оружейн": 2,
            "кузн": 3, "храм": 3, "молельн": 3, "часовн": 3, "лечебн": 3, "мастерск": 3,
            "башн": 2, "магич": 2}


def _plan_jobs(city, homes: dict, roles: dict) -> dict:
    """DETERMINISTIC: who works at which venue (gravity — nearest by home) + who to reclassify.
    Returns pid → (work_bid|None, role_override|None). Pure function of (city, homes, roles) —
    same result in both settlement paths (fresh/restore)."""
    xy = {n.id: (n.x, n.y) for n in city.nodes()}

    def dist(pid, node):
        h = homes.get(pid)
        if h not in xy or node not in xy:
            return 1e9
        (ax, ay), (bx, by) = xy[h], xy[node]
        return (ax - bx) ** 2 + (ay - by) ** 2

    out: dict = {}
    assigned: set = set()
    for bid, kb in sorted(city.key_buildings.items()):  # venue recruits NEAREST by role
        want = _role_for_building(bid)
        info = (_binfo(bid)["kind"] + " " + _binfo(bid)["name"]).lower()
        cap = next((c for w, c in _WORKCAP.items() if w in info), 3)
        cand = sorted((pid for pid, r in roles.items()
                       if r == want and pid not in assigned),
                      key=lambda pid: dist(pid, kb.node))
        for pid in cand[:cap]:
            out[pid] = (bid, None)
            assigned.add(pid)
    for pid, r in roles.items():                        # remainder: home-producer / day laborer
        if pid in assigned:
            continue
        if r in _VENUE_NEED:                            # service without venue won't work — day laborer
            out[pid] = (None, "подёнщик")
        # HOME_PRODUCER and MOBILE — no override (produce at home / mobile), work=None
    return out
