import os
import tempfile

import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.engine.session import persist


@pytest.fixture
def world(monkeypatch):
    from aidnd.server.play.engine.world import _play
    from aidnd.worldgen import WorldStore

    monkeypatch.setattr(persist, "_STORE", WorldStore(os.path.join(tempfile.mkdtemp(), "live.db")))
    core._S["city"] = None
    _play()
    core._S["gt"] = 8 * 60
    return None


def test_drink_heals_and_restores_mana(world):
    from aidnd.server.play.engine.core import _mana, _pc_hp
    from aidnd.server.play.mechanics.items import _apply_consumable

    _pc_hp(set_to=9)                                          # wounded
    mana0 = _mana()
    it = {"kind": "consumable", "name": "зелье",
          "attrs": {"святость": {"surface": 60, "true": 60}, "мана": {"surface": 80, "true": 80}}}
    frag = _apply_consumable(it)
    assert _pc_hp() == 14                                     # +5 (medium band), clamped ≤ 18
    assert _mana() > mana0                                    # mana pool rose (band 3 × mana_per_band)
    assert any("здоровья" in f for f in frag) and any("маны" in f for f in frag)


def test_overheal_clamps_to_cap(world):
    from aidnd.server.play.engine.core import _pc_hp
    from aidnd.server.play.mechanics.items import _apply_consumable

    _pc_hp(set_to=16)                                         # near cap 18
    frag = _apply_consumable({"kind": "consumable", "name": "зелье",
                              "attrs": {"святость": {"surface": 100, "true": 100}}})  # +8 → would overheal
    assert _pc_hp() == 18                                     # capped
    assert frag == ["+2 здоровья"]                            # only the 2 that fit are reported


def test_legacy_consumable_is_inert(world):
    from aidnd.server.play.mechanics.items import _apply_consumable

    assert _apply_consumable({"kind": "consumable", "name": "хлеб"}) == []   # no attrs → no effect


def test_use_endpoint_heals_a_real_crafted_draught(world):
    """Drive the ACTUAL /api/play/use handler with a real graph-crafted святость consumable —
    the same code path the browser 'применить' button hits (no LLM)."""
    import asyncio

    from aidnd.server.play.engine.core import _pc_hp
    from aidnd.server.play.handlers.inventory import use_item
    from aidnd.server.play.mechanics.items import _put_graph_item

    _pc_hp(set_to=8)
    iid = _put_graph_item("святое зелье", "plain")           # святость-bearing consumable from the graph

    class Req:
        async def json(self):
            return {"item": iid}

    res = asyncio.run(use_item(Req()))
    assert res.get("consumed") is True
    assert res["hp"] > 8                                      # HP actually rose
    assert any("здоровья" in f for f in res["effects"])       # and the endpoint reported the heal
