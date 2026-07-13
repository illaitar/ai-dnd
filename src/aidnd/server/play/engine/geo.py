"""NPC geographic knowledge (pure). Code owns every geo fact — this module derives, per query,
which places an NPC could plausibly know, the true route to a place, and who he could refer you
to. The LLM only DECIDES and SPEAKS (Inc 2 router); everything here is deterministic.

No stored state. Reads _S (city/people/keynode/cr2b/loc) + _store() building factsheets +
relationships. See docs/superpowers/specs/2026-07-13-npc-geo-knowledge-design.md."""

from __future__ import annotations

import re

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


# minutes → RU numeral word for small counts (spec §10 resolved: numeral words 1–10, else «минут N»)
_MIN_WORD = {
    1: "минуту", 2: "в паре минут", 3: "минуты три", 4: "минуты четыре", 5: "минут пять",
    6: "минут шесть", 7: "минут семь", 8: "минут восемь", 9: "минут девять", 10: "минут десять",
}
# City._heading 8-wind code → RU "к <side>" (graph.py:399 dirs order)
_SIDE = {
    "С": "к северу", "СВ": "к северо-востоку", "В": "к востоку", "ЮВ": "к юго-востоку",
    "Ю": "к югу", "ЮЗ": "к юго-западу", "З": "к западу", "СЗ": "к северо-западу",
}
# landmark tag (Route.landmarks) → RU clause appended after the near_target
_LM_WORD = {"river": "у реки", "wall": "у городской стены", "gate": "у ворот", "bridge": "у моста"}


def _minutes_phrase(steps: int) -> str:
    m = max(1, steps) * int(PB["step_min"])
    if m in _MIN_WORD:
        return _MIN_WORD[m]
    # beyond the word table: the RU approximation idiom is an inverted ROUND numeral
    # («минут двадцать»), so bucket to the nearest natural round value — grammatical for any m
    if m <= 17:
        return "минут пятнадцать"
    if m <= 25:
        return "минут двадцать"
    if m <= 40:
        return "с полчаса"
    return "добрый час, не меньше"


def direction_line(from_node, bid: str) -> str:
    """One always-true RU sentence for the route from_node → bid. Thin formatter over City.route:
    minutes (steps × step_min) + compass side + nearest landmark. Voice may wrap, never alter."""
    city = _S.get("city")
    r = city.route(from_node, bid) if city is not None else None
    if r is None or not r.found:
        return "это на другом конце города"
    steps = max(1, len(r.nodes) - 1)
    parts = [f"{_minutes_phrase(steps)} ходу"]
    if r.bearing and r.bearing in _SIDE:
        parts.append(_SIDE[r.bearing])
    # "за рыночной площадью" reads better for an open square; "у <name>" for a point landmark.
    # Spec §5 uses «за рыночной площадью» for the market and «у колодца» for the well.
    tail = ""
    if r.near_target is not None:
        name = r.near_target.name
        prep = "за" if ("площад" in name or "рынок" in name or "рыноч" in name) else "у"
        tail = f", {prep} {_loc_form(name, prep)}"
    lm = next((_LM_WORD[t] for t in (r.landmarks or []) if t in _LM_WORD), "")
    sentence = " ".join(parts) + tail
    if lm:
        sentence += f", {lm}"
    return sentence


def _loc_form(name: str, prep: str) -> str:
    """Instrumental/prepositional case for the landmark noun phrase. The citygraph names are fixed
    strings; map the few real forms, fall back to the raw name (voice smooths any rough edge)."""
    forms = {
        ("за", "рыночная площадь"): "рыночной площадью",
        ("у", "колодец"): "колодца",
        ("у", "рыночная площадь"): "рыночной площади",
    }
    return forms.get((prep, name), name)


def acquaintances(pid: str, from_node) -> list[dict]:
    """Referrable people — kin/friend/coworker whose HOME the NPC knows — with a where_line the NPC
    can speak. Bounds the router's refer_pid choice (spec §4.2 validation)."""
    people = _S.get("people") or {}
    out = []
    for other in _kin_and_friends(pid):
        op = people.get(other)
        if op is None or getattr(op, "home", None) is None:
            continue
        hb = _home_bid(other)
        where = direction_line(from_node, hb) if hb else "где-то в городе"
        out.append({"pid": other, "name": op.name, "role": op.role,
                    "home": op.home, "where_line": where})
    return out


# where-question intent — spec §3.2 (где|куда|как найти|как пройти|где купить|у кого)
_GEO_RE = re.compile(
    r"\b(где|куда|как\s+найти|как\s+пройти|как\s+добраться|где\s+купить|у\s+кого)\b",
    re.IGNORECASE,
)


def geo_question(text: str) -> bool:
    return bool(_GEO_RE.search(text or ""))


def _stem_tokens(s: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[а-яё]+", (s or "").lower()) if len(w) >= 4}


def match_known_place(pid: str, text: str) -> dict | None:
    """Inc 1 exact-name matcher: the known_places entry whose name/kind shares a 4+ char token
    with the question. Longest-name match wins (most specific). Superseded by the router in Inc 2."""
    q = _stem_tokens(text)
    best, score = None, 0
    for e in known_places(pid):
        hit = len(_stem_tokens(e["name"] + " " + e["kind"]) & q)
        if hit > score:
            best, score = e, hit
    return best if score else None


def geo_answer(pid: str, text: str, from_node) -> dict | None:
    """Stable say() seam. None → not a geo question (say() runs unchanged). Otherwise a dict with
    a geo_line for _voice and an optional reveal {bid,text} to _mark_seen. Inc 1 body = exact-name
    matcher → share or deflect; Inc 2 rewrites this body to the persona-driven router."""
    if not geo_question(text):
        return None
    place = match_known_place(pid, text)
    if place is None:
        return {"geo_line": "ты уклончив и не выдаёшь точных мест — отговорись общими словами",
                "reveal": None}
    dline = direction_line(from_node, place["bid"])
    if dline == "это на другом конце города":
        return {"geo_line": f"ты знаешь про {place['kind']} «{place['name']}», но это далеко: "
                            f"{dline} — так и скажи",
                "reveal": None}
    teller = (_S.get("people") or {}).get(pid)
    tname = teller.name if teller is not None else "NPC"
    return {
        "geo_line": f"ты знаешь место {place['kind']} «{place['name']}»: {dline} — посоветуй "
                    "дорогу игроку по-своему",
        "reveal": {"bid": place["bid"],
                   "text": f"{tname} рассказал(а) дорогу к {place['name']}"},
    }
