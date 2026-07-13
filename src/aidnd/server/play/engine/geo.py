"""NPC geographic knowledge (pure). Code owns every geo fact — this module derives, per query,
which places an NPC could plausibly know, the true route to a place, and who he could refer you
to. The LLM only DECIDES and SPEAKS (Inc 2 router); everything here is deterministic.

No stored state. Reads _S (city/people/keynode/cr2b/loc) + _store() building factsheets +
relationships. See docs/superpowers/specs/2026-07-13-npc-geo-knowledge-design.md."""

from __future__ import annotations

from aidnd import society

from .session.config import PB
from .session.state import _S

# goods hint by building kind keyword (rule 4 landmarks + rule 2 work) — spec §4.1
_GOODS = (
    ("кузн", "оружие, доспехи"),
    ("оружейн", "оружие, доспехи"),
    ("рынок", "всякий товар"),
    ("рыноч", "всякий товар"),
    ("лавк", "ткани, снедь"),
    ("таверн", "выпивка, слухи"),
    ("трактир", "выпивка, слухи"),
    ("постоял", "выпивка, слухи"),
    ("храм", "свечи, благословение"),
    ("часовн", "свечи, благословение"),
    ("колодец", "вода"),
    ("колод", "вода"),
)
# landmark building kinds "everyone knows" beyond society tavern/temple/market (rule 4)
_LANDMARK_WORDS = ("колод", "гильди", "ворот", "мельниц")
_LANDMARK_SOC = {"tavern", "temple", "market"}
_ROUTINE_KINDS = ("tavern", "temple", "market")   # rule 3 routine-venue approximation


def _goods_for(info: dict) -> str:
    blob = (info.get("kind", "") + " " + info.get("name", "")).lower()
    return next((g for w, g in _GOODS if w in blob), "")


def _bdata(bid: str) -> dict:
    from .session.persist import _store
    from .session.state import _wid
    return (_store().get_building(_wid(), bid) or {}).get("data") or {}


def _is_landmark(bid: str) -> bool:
    data = _bdata(bid)
    if set(society.kinds_of(data)) & _LANDMARK_SOC:
        return True
    blob = (str(data.get("type", "")) + " " + str(data.get("name", ""))).lower()
    return any(w in blob for w in _LANDMARK_WORDS)


def _node2bid(node) -> str | None:
    return (_S.get("cr2b") or {}).get(node)


def _home_bid(pid: str) -> str | None:
    p = (_S.get("people") or {}).get(pid)
    return _node2bid(p.home) if p is not None and p.home is not None else None


def _landmark_bids() -> list[str]:
    return [bid for bid in (_S.get("keynode") or {}) if _is_landmark(bid)]


def _routine_venues(p) -> list[str]:
    """Approximation (spec §4.3): the nearest tavern/temple/market to the NPC's home, by route
    length. No clean frequents() accessor exists; this matches what worldsim._candidates seeds."""
    city, keynode = _S.get("city"), _S.get("keynode") or {}
    if city is None or p.home is None:
        return []
    by_kind: dict[str, list[str]] = {}
    for bid in keynode:
        for k in society.kinds_of(_bdata(bid)):
            if k in _ROUTINE_KINDS:
                by_kind.setdefault(k, []).append(bid)
    out = []
    for kind in _ROUTINE_KINDS:
        cands = by_kind.get(kind) or []
        if not cands:
            continue
        best, bd = None, 1e30
        for bid in cands:
            r = city.route(p.home, bid)
            if r.found and r.length < bd:
                bd, best = r.length, bid
        if best is not None:
            out.append(best)
    return out


def _kin_and_friends(pid: str) -> list[str]:
    from .quests.seeds import _aff, _fam
    people = _S.get("people") or {}
    p = people.get(pid)
    if p is None:
        return []
    surname = _fam(p.name)
    out = []
    for other, op in people.items():
        if other == pid:
            continue
        is_kin = surname and _fam(op.name) == surname
        is_friend = _aff(p, other) > PB["geo_friend_aff"]
        is_coworker = bool(p.work) and getattr(op, "work", None) == p.work
        if is_kin or is_friend or is_coworker:
            out.append(other)
    return out


def _neighbor_home_bids(p) -> list[str]:
    """Homes whose node is within PB[geo_neighbor_hops] graph hops of the NPC's home node."""
    city = _S.get("city")
    if city is None or p.home is None:
        return []
    adj = getattr(city, "_adj", {})
    seen, frontier = {p.home}, {p.home}
    for _ in range(int(PB["geo_neighbor_hops"])):
        nxt = set()
        for n in frontier:
            nxt |= set(adj.get(n, ()))
        frontier = nxt - seen
        seen |= nxt
    out = []
    for n in seen:
        if n == p.home:
            continue
        bid = _node2bid(n)
        if bid:
            out.append(bid)
    return out


def known_places(pid: str) -> list[dict]:
    """The NPC's plausibly-known places — 6 source rules (spec §4.1). First rule to claim a bid
    wins; a bid appears once. Each entry: {bid, node, name, kind, goods, why_known}."""
    from .core import _binfo
    people = _S.get("people") or {}
    p = people.get(pid)
    if p is None:
        return []
    keynode = _S.get("keynode") or {}
    out: dict[str, dict] = {}

    def add(bid, why):
        if not bid or bid in out:
            return
        info = _binfo(bid)
        out[bid] = {"bid": bid, "node": keynode.get(bid), "name": info["name"],
                    "kind": info["kind"], "goods": _goods_for(info), "why_known": why}

    if p.home is not None:                              # rule 1 — home
        add(_node2bid(p.home), "живу")
    if p.work:                                          # rule 2 — work
        add(p.work, "работаю")
    for bid in _routine_venues(p):                      # rule 3 — routine venues (approx §4.3)
        add(bid, "хожу")
    for bid in _landmark_bids():                        # rule 4 — town landmarks
        add(bid, "все знают")
    for other in _kin_and_friends(pid):                 # rule 5 — kin & friend homes
        add(_home_bid(other), "свои")
    for bid in _neighbor_home_bids(p):                  # rule 6 — neighbors
        add(bid, "соседи")
    return list(out.values())
