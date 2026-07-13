"""known_places(pid): the 6 source rules compose an NPC's known-set; a far arbitrary
house is NOT in it; the smithy landmark carries its goods hint. Fixture = Ода Вент (spec §5)."""
from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core, geo
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


class _FakeCity:
    """Minimal City surface geo.py depends on: adjacency for neighbor BFS + route() stub.
    The fixture graph only wires up the home/neighbor nodes (42/41/43) needed for the
    "соседи" BFS — landmark/work nodes (54/55/60/48/51) live outside it, exactly like a
    real City graph would still route to them across streets this fixture never draws.
    route() is a naive stub: BFS distance when reachable, a large-but-finite fallback
    length (still `found`) otherwise, so "nearest routine venue" always resolves."""
    def __init__(self, adj):
        self._adj = adj

    def route(self, a, b):
        from collections import deque
        if a == b:
            return SimpleNamespace(found=True, length=0)
        seen, q = {a}, deque([(a, 0)])
        while q:
            n, d = q.popleft()
            for nb in self._adj.get(n, ()):
                if nb == b:
                    return SimpleNamespace(found=True, length=d + 1)
                if nb not in seen:
                    seen.add(nb)
                    q.append((nb, d + 1))
        return SimpleNamespace(found=True, length=999)


def _person(pid, name, role, home, work):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    return SimpleNamespace(id=pid, name=name, role=role, home=home, work=work,
                           persona={}, state=st)


@pytest.fixture
def town(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    keynode = {"b_house_oda": 42, "b_market_stall": 55, "b_tavern_goose": 60, "b_smithy": 48,
               "b_market": 54, "b_well": 51, "b_house_gorm": 40, "b_house_pekka": 43,
               "b_house_vetl": 90}
    cr2b = {n: b for b, n in keynode.items()}
    # buildings (factsheets drive _binfo name/kind + society.kinds_of detect)
    def _b(bid, name, btype):
        st.save_building(1, bid, True, keynode[bid], name, {"name": name, "type": btype})
    _b("b_house_oda", "дом Оды", "жилой дом")
    _b("b_market_stall", "лавка Оды", "лавка тканей")
    _b("b_tavern_goose", "«Пьяный гусь»", "таверна")
    _b("b_smithy", "кузница «Молот и мех»", "кузница оружейная")
    _b("b_market", "рыночная площадь", "рынок")
    _b("b_well", "колодец", "колодец")
    _b("b_house_gorm", "дом Горма", "жилой дом")
    _b("b_house_pekka", "дом Пёкка", "жилой дом")
    _b("b_house_vetl", "дом Ветла", "жилой дом")   # arbitrary far house — MUST be excluded
    # a HOUSE whose type text contains a landmark keyword ("колодец") — NOT in keynode, so it
    # must never enter rule 4 (real keynode holds only key buildings, never houses; reviewer note)
    st.save_building(1, "b_house_lake", True, 99, "дом у колодца",
                      {"name": "дом у колодца", "type": "жилой дом у колодца"})
    # adjacency: Ода's home 42 neighbours 43 (Пёкка, 1 hop) and 41; 90 is far (unreachable in 2 hops)
    adj = {42: {41, 43}, 43: {42}, 41: {42}, 90: {91}, 91: {90}}
    people = {
        "p_oda": _person("p_oda", "Ода Вент", "лавочница", 42, "b_market_stall"),
        "p_gorm": _person("p_gorm", "Горм Вент", "кузнец", 40, "b_smithy"),
        "p_pekka": _person("p_pekka", "Пёкка Луд", "рыбак", 43, None),
        "p_vetl": _person("p_vetl", "Ветл Кор", "бродяга", 90, None),
    }
    saved = dict(core._S._d()); d = core._S._d()
    try:
        d.clear()
        d.update(wid=1, city=_FakeCity(adj), people=people, keynode=keynode, cr2b=cr2b, loc=50)
        yield people
    finally:
        d.clear(); d.update(saved)


def _by_why(entries):
    out = {}
    for e in entries:
        out.setdefault(e["why_known"], []).append(e)
    return out


def test_all_six_rules_fire(town):
    entries = geo.known_places("p_oda")
    buckets = _by_why(entries)
    assert set(buckets) == {"живу", "работаю", "хожу", "все знают", "свои", "соседи"}


def test_home_and_work_entries(town):
    entries = {e["bid"]: e for e in geo.known_places("p_oda")}
    assert entries["b_house_oda"]["why_known"] == "живу"
    assert entries["b_market_stall"]["why_known"] == "работаю"


def test_smithy_landmark_carries_goods(town):
    entries = {e["bid"]: e for e in geo.known_places("p_oda")}
    assert entries["b_smithy"]["why_known"] == "все знают"
    assert entries["b_smithy"]["goods"] == "оружие, доспехи"


def test_kin_home_included_neighbor_home_included(town):
    entries = {e["bid"]: e for e in geo.known_places("p_oda")}
    assert entries["b_house_gorm"]["why_known"] == "свои"      # kin (same surname Вент)
    assert entries["b_house_pekka"]["why_known"] == "соседи"   # 1 hop from home node 42


def test_far_arbitrary_house_excluded(town):
    bids = {e["bid"] for e in geo.known_places("p_oda")}
    assert "b_house_vetl" not in bids                          # not home/work/kin/neighbor/landmark


def test_house_with_landmark_keyword_not_in_keynode_excluded(town):
    """Carried from T1 review: a house whose type text matches a landmark keyword ("колодец")
    must NOT be pulled in by rule 4 — real keynode holds only key buildings, never houses, so
    keynode membership (not the keyword match alone) gates the landmark rule."""
    bids = {e["bid"] for e in geo.known_places("p_oda")}
    assert "b_house_lake" not in bids
