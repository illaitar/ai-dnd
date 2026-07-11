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


def test_duplicate_inputs_are_counted(world):
    from aidnd.server.play.mechanics.items import _do_craft, _put_item

    _put_item("t|k1", "камень", "material", holder="pc")      # «zhernov» needs 2× камень; one is not enough
    out = {"narr": []}
    _do_craft("zhernov", out)
    assert "не хватает" in " ".join(out["narr"]).lower()      # (was a dup-input collapse bug)


def test_crafted_weapon_feeds_combat_and_prices(world):
    from aidnd.combat.model import from_pc
    from aidnd.items import derive_effects, view
    from aidnd.server.play.engine.pc.hero import _PC_CAP, _pc_hp
    from aidnd.server.play.engine.session.config import PB
    from aidnd.server.play.engine.session.persist import _store
    from aidnd.server.play.mechanics.combat import _derived_amount, _pc_combatant
    from aidnd.server.play.mechanics.items import _put_graph_item

    made = _store().get_item(_put_graph_item("меч", "exquisite", masterwork=True))
    atk = _derived_amount(made, "attack")
    assert atk > 0                                            # the masterwork blade has real bite
    cmb = _pc_combatant()                                     # highest-worth weapon → the меч
    base = from_pc(_PC_CAP.abilities, _pc_hp(), PB["pc_max_hp"], weapon={**made, "bonus": 0}).dmg_bonus
    assert cmb.dmg_bonus == base + atk                        # its derived attack reached combat damage
    assert view(made)["worth"] == derive_effects(made)["worth"]   # trade prices off derived worth


def test_crafted_armor_raises_ac_by_best_piece(world):
    from aidnd.server.play.engine.session.persist import _store
    from aidnd.server.play.mechanics.combat import _derived_amount, _pc_combatant
    from aidnd.server.play.mechanics.items import _put_graph_item

    bare = _pc_combatant().ac                                 # no crafted armor yet (legacy = 0 derived)
    vest = _store().get_item(_put_graph_item("кожаный жилет", "fine"))
    boots = _store().get_item(_put_graph_item("сапоги", "fine"))
    best = max(_derived_amount(vest, "defense"), _derived_amount(boots, "defense"))
    assert _pc_combatant().ac == bare + best                  # best single piece — NOT the sum (no stacking)
