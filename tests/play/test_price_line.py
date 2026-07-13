"""_price_line grounds NPC price/lodging talk in code truth (same arithmetic as /wares) — only
for the NPC who actually works at the building the player is standing in."""

from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core
from aidnd.server.play.engine.session import persist
from aidnd.server.play.handlers import dialogue as dlg_mod
from aidnd.server.play.handlers import trade as trade_mod
from aidnd.server.play.mechanics.items import _npc_cap, _npc_sees
from aidnd.worldgen import WorldStore


def _npc(id_="npc:inn", name="Хёльга", role="трактирщик", work=None):
    st = NpcState.from_config(NpcConfig(id=id_, name=name, role=role))
    return SimpleNamespace(id=id_, name=name, role=role, state=st, persona={}, portraits={},
                           work=work, keys=[])


@pytest.fixture
def wired(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    saved = dict(core._S._d())
    d = core._S._d()
    try:
        d.clear()
        d["wid"] = 1
        d["gt"] = 600
        d["city_name"] = "Городок"
        yield st
    finally:
        d.clear()
        d.update(saved)


def test_lodging_clause_reads_rest_cost_from_pb_not_hardcoded(wired, monkeypatch):
    st = wired
    st.save_building(1, "b:tavern", True, 1, None, {"services": ["lodging"]})
    monkeypatch.setitem(core.PB, "rest_cost", 7)
    p = _npc(role="трактирщик", work="b:tavern")
    cr2b = {"loc:square": "b:tavern"}
    line = dlg_mod._price_line(p, cr2b, "loc:square")
    assert line is not None
    assert "7 зм" in line
    assert "2 зм" not in line  # not the old hardcoded/default value


def test_wares_clause_matches_wares_handler_prices(wired, monkeypatch):
    st = wired
    st.save_building(1, "b:shop", True, 1, None, {"services": []})
    p = _npc(id_="npc:merch", name="Тор", role="лавочник", work="b:shop")
    def _mk(iid, name, worth):
        return {
            "id": iid, "kind": "food", "name": name, "worth": worth, "apparent_worth": worth,
            "rarity": "common", "slot": None, "material": "plain", "quality": "modest",
            "weight": 1, "tags": [], "hidden": [], "mods": [],
        }

    st.save_item(_mk("it:bread", "хлеб", 2))
    st.save_item(_mk("it:ale", "эль", 4))
    st.inv_add(1, "it:bread", "npc:merch")
    st.inv_add(1, "it:ale", "npc:merch")
    cr2b = {"loc:market": "b:shop"}
    line = dlg_mod._price_line(p, cr2b, "loc:market")
    assert line is not None

    rel = p.state.relationships.get("pc", {"affinity": 0.0})
    greed = p.state.config.traits.get("greed", 0.5)
    for iid, name in (("it:bread", "хлеб"), ("it:ale", "эль")):
        it = st.get_item(iid)
        seen = _npc_sees(it, _npc_cap(p), "npc:merch")
        expected_price = trade_mod._wares_price(it, seen, rel, greed)
        assert f"{name}: {expected_price} зм" in line


def test_no_price_line_for_npc_not_working_here(wired, monkeypatch):
    st = wired
    st.save_building(1, "b:tavern", True, 1, None, {"services": ["lodging"]})
    p = _npc(role="трактирщик", work="b:other")  # works elsewhere
    cr2b = {"loc:square": "b:tavern"}
    assert dlg_mod._price_line(p, cr2b, "loc:square") is None


def test_no_price_line_when_player_not_in_a_building(wired):
    p = _npc(role="трактирщик", work="b:tavern")
    cr2b = {}  # loc not mapped to any building
    assert dlg_mod._price_line(p, cr2b, "loc:square") is None


def test_no_price_line_when_neither_lodging_nor_wares_apply(wired):
    st = wired
    st.save_building(1, "b:plain", True, 1, None, {"services": []})
    p = _npc(id_="npc:guard", name="Крон", role="стражник", work="b:plain")  # not a merchant role
    cr2b = {"loc:gate": "b:plain"}
    assert dlg_mod._price_line(p, cr2b, "loc:gate") is None
