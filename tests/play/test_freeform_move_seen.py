"""F4: verb=move place=… resolves against REVEALED buildings, not just geom landmarks.
A seen house («дом Медовара») → goto=<its door node>; an unrevealed / unknown place → honest
refusal. The arbiter fact sheet must also NAME seen buildings so intent[place] can be produced."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.engine.action import arbiter
from aidnd.server.play.handlers import freeform


class _FakeCity:
    """Minimal City: door nodes for a key building and a residential house."""
    def __init__(self):
        self.key_buildings = {"key:1": SimpleNamespace(node=48)}
        self.houses = {"house:9:310_372": SimpleNamespace(node=372)}


@pytest.fixture
def world(tmp_path, monkeypatch):
    from aidnd.server.play.engine.session import persist
    from aidnd.worldgen import WorldStore

    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    st.save_building(1, "house:9:310_372", False, 372, "дом Медовара",
                     {"name": "дом Медовара", "type": "жилой дом"})
    city = _FakeCity()
    people, crof, cr2b = {}, {}, {372: "house:9:310_372", 48: "key:1"}
    monkeypatch.setattr(freeform, "_play", lambda: (city, people, crof, cr2b, 50))
    d = core._S._d(); saved = dict(d)
    try:
        d.clear()
        d.update(wid=1, gt=514, loc=50, city=city, cr2b=cr2b, keynode={"key:1": 48},
                 geom={"keys": [{"node": 48, "label": "кузня", "bid": "key:1"}]},
                 seen={"house:9:310_372"})
        yield st
    finally:
        d.clear(); d.update(saved)


def test_move_to_seen_house_sets_goto(world):
    res = freeform._attempt({"verb": "move", "place": "дом Медовара"}, {})
    assert res.get("goto") == 372                       # the house's door node
    assert not res.get("fail")


def test_move_to_landmark_still_works(world):
    res = freeform._attempt({"verb": "move", "place": "кузня"}, {})
    assert res.get("goto") == 48


def test_move_to_unknown_place_refuses(world):
    res = freeform._attempt({"verb": "move", "place": "дворец короля"}, {})
    assert res.get("fail") is True
    assert "Спроси у людей" in " ".join(res["narr"])


def test_arbiter_context_names_seen_buildings(tmp_path):
    # assemble_context must list the revealed house under МЕСТА ГОРОДА so the parser can emit it
    from aidnd.server.play.engine.session import state as _state
    d = _state._S._d(); saved = dict(d)
    from aidnd.server.play.engine.session import persist
    from aidnd.worldgen import WorldStore
    st = WorldStore(str(tmp_path / "live2.db"))
    try:
        d.clear()
        d.update(wid=1, loc=50, seen={"house:9:310_372"},
                 geom={"keys": [{"node": 48, "label": "кузня", "bid": "key:1"}]},
                 live={}, zone=None)
        persist._STORE = st
        st.save_building(1, "house:9:310_372", False, 372, "дом Медовара",
                         {"name": "дом Медовара", "type": "жилой дом"})
        sc = {"here": [], "location": {"name": "улица", "containers": []}, "ambient": {}}
        ctx = arbiter.assemble_context(sc)
        assert "дом Медовара" in ctx                     # revealed house is offered to the parser
    finally:
        d.clear(); d.update(saved)


def test_arbiter_seen_names_capped_at_12(tmp_path):
    # F4 review Minor: unbounded seen-list bloats every prompt in a long-lived world — cap it.
    from aidnd.server.play.engine.session import persist
    from aidnd.server.play.engine.session import state as _state
    from aidnd.worldgen import WorldStore

    st = WorldStore(str(tmp_path / "live3.db"))
    d = _state._S._d(); saved = dict(d)
    try:
        d.clear()
        seen_bids = {f"house:{i}" for i in range(15)}
        d.update(wid=1, loc=50, seen=seen_bids,
                 geom={"keys": [{"node": 48, "label": "кузня", "bid": "key:1"}]},
                 live={}, zone=None)
        persist._STORE = st
        for i in range(15):
            st.save_building(1, f"house:{i}", False, 372 + i, f"дом {i}", {"name": f"дом {i}"})
        sc = {"here": [], "location": {"name": "улица", "containers": []}, "ambient": {}}
        ctx = arbiter.assemble_context(sc)
        mesta = ctx.split("МЕСТА ГОРОДА: ")[1].split(". ЗОНЫ:")[0]
        seen_present = [f"дом {i}" for i in range(15) if f"дом {i}" in mesta]
        assert len(seen_present) <= 12
    finally:
        d.clear(); d.update(saved)
