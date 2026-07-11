import os
import tempfile

import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.engine.session import persist
from aidnd.server.play.engine.session.config import PB
from aidnd.server.play.mechanics.items import _craft_band, _flaw_attrs, _mw_attrs


@pytest.fixture
def world(monkeypatch):
    from aidnd.server.play.engine.world import _play
    from aidnd.worldgen import WorldStore

    monkeypatch.setattr(persist, "_STORE", WorldStore(os.path.join(tempfile.mkdtemp(), "live.db")))
    core._S["city"] = None
    _play()
    core._S["gt"] = 8 * 60
    return None


def test_craft_band_thresholds():
    assert _craft_band(PB["craft_waste"] - 1) == "waste"
    assert _craft_band(PB["craft_waste"]) == "crude"      # low but not wasted → a flawed item
    assert _craft_band(PB["craft_flaw"]) == "plain"
    assert _craft_band(PB["craft_clean"]) == "fine"       # modified
    assert _craft_band(PB["craft_fine"]) == "exquisite"   # masterwork
    assert _craft_band(999) == "exquisite"


def test_flaw_hides_a_crack():
    a = {"прочность": {"surface": 60, "true": 60}}
    _flaw_attrs(a)
    assert a["прочность"]["surface"] == 60                # looks sound
    assert a["прочность"]["true"] < 60                    # but is cracked (revealed by craft_eye)
    b = {}                                                # even an item with no прочность gains the crack
    _flaw_attrs(b)
    assert b["прочность"]["true"] < b["прочность"]["surface"]


def test_masterwork_bumps_only_the_strongest():
    a = {"острота": {"surface": 70, "true": 70}, "вес": {"surface": 40, "true": 40}}
    _mw_attrs(a)
    assert a["острота"]["true"] == min(100, 70 + PB["craft_masterwork_bonus"])
    assert a["вес"]["true"] == 40                          # only the primary attribute is bumped


def test_put_graph_item_forges_a_real_attribute_item(world):
    from aidnd.items import derive_effects
    from aidnd.server.play.engine.session.persist import _store
    from aidnd.server.play.mechanics.items import _put_graph_item

    it = _store().get_item(_put_graph_item("меч", "fine"))
    assert it["kind"] == "weapon" and it["attrs"]         # a graph node → a real attr-bearing item
    assert [m for m in derive_effects(it)["mods"] if m["target"] == "attack"]   # it has combat stats
    assert it["worth"] > 0                                 # and a derived worth (combat/trade read it)


def test_craft_loop_consumes_input_and_narrates(world):
    from aidnd.server.play.engine.session.persist import _store
    from aidnd.server.play.engine.session.state import _S, _wid
    from aidnd.server.play.mechanics.items import _do_craft, _put_item

    _put_item("t|масло", "масло", "material", holder="pc")     # a raw input in the bag
    _S["inside"] = "b0"                                        # in some building; «наполнить» needs no station
    out = {"narr": []}
    _do_craft("склянка масла", out)                           # from ["масло"] via наполнить
    names = [_store().get_item(r["item_id"])["name"] for r in _store().inventory(_wid(), "pc")
             if _store().get_item(r["item_id"])]
    assert "масло" not in names                               # the input was consumed
    assert out["narr"]                                        # an outcome was narrated
