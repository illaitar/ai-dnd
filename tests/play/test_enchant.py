import asyncio
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
    core._S["glyphs"] = None            # reset → starter glyph set
    _play()
    core._S["gt"] = 8 * 60
    return None


class Req:
    def __init__(self, d):
        self.d = d

    async def json(self):
        return self.d


def test_enchant_cap_from_chara():
    from aidnd.server.play.handlers.magic import _enchant_cap

    assert _enchant_cap({"attrs": {"чара": {"surface": 60, "true": 60}}}) == 6.0   # 60 / 10
    assert _enchant_cap({"attrs": {}}) == 0                                         # no чара → not enchantable


def test_bind_stores_a_grimoire_law_on_the_item(world):
    """Bind a KNOWN circle (grimoire-cached → no LLM) into an item; the law is stored with charges."""
    from aidnd.magic import circle_hash
    from aidnd.server.play.engine.core import _grimoire_put
    from aidnd.server.play.engine.session.persist import _store
    from aidnd.server.play.engine.session.state import _wid
    from aidnd.server.play.handlers.magic import enchant_item

    it = {"id": "it:wand", "kind": "trinket", "name": "жезл",
          "attrs": {"чара": {"surface": 60, "true": 60}}}
    _store().save_item(it)
    _store().inv_add(_wid(), "it:wand", "pc")
    comp = [{"id": "свет", "size": 0.5, "angle": 0, "ring": 0}]          # свет = starter glyph
    h = circle_hash(comp)
    _grimoire_put(h, {"hash": h, "name": "Ровный свет", "kind": "light", "power": 1,
                      "mech": {"light": True}, "law": "", "flavor": "", "sensory": "",
                      "target": "self", "range": 1, "duration": 1, "taboo": False})  # cache hit → DET
    res = asyncio.run(enchant_item(Req({"item": "it:wand", "drawing": comp})))
    assert res.get("enchanted") is True and res["law"] == "Ровный свет"
    stored = _store().get_item("it:wand")
    assert stored["enchant"]["name"] == "Ровный свет" and stored["enchant"]["charges"] == 3


def test_bind_rejects_item_without_chara(world):
    from aidnd.server.play.engine.session.persist import _store
    from aidnd.server.play.engine.session.state import _wid
    from aidnd.server.play.handlers.magic import enchant_item

    it = {"id": "it:stick", "kind": "misc", "name": "палка", "attrs": {}}
    _store().save_item(it)
    _store().inv_add(_wid(), "it:stick", "pc")
    res = asyncio.run(enchant_item(Req({"item": "it:stick",
                                        "drawing": [{"id": "свет", "size": 0.5, "angle": 0, "ring": 0}]})))
    assert "error" in res and "чар" in res["error"]                     # no чара → can't be enchanted


def test_activate_enchant_heals_then_spends(world):
    """The deterministic payoff: an enchanted item fires its law via _apply_law, per-use charges."""
    from aidnd.server.play.engine.core import _pc_hp
    from aidnd.server.play.engine.session.persist import _store
    from aidnd.server.play.handlers.magic import _activate_enchant

    it = {"id": "it:charm", "kind": "trinket", "name": "оберег",
          "attrs": {"чара": {"surface": 60, "true": 60}},
          "enchant": {"name": "Тихий свет", "kind": "heal", "mech": {"heal": 5}, "charges": 2}}
    _store().save_item(it)
    _pc_hp(set_to=8)
    r1 = _activate_enchant(it)
    assert r1["activated"] and _pc_hp() == 13 and r1["charges"] == 1     # +5 heal, one charge left
    _pc_hp(set_to=8)
    r2 = _activate_enchant(it)
    assert _pc_hp() == 13 and r2["charges"] == 0                          # fired again, now spent
    assert "enchant" not in _store().get_item("it:charm")                # enchant gone, item remains
    assert _store().get_item("it:charm")["name"] == "оберег"
