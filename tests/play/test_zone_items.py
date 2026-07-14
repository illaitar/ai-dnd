"""Кейс: материализация обстановки — предметы зон НАСТОЯЩИЕ (live.db), взятое не возвращается."""

from types import SimpleNamespace

from aidnd.server.play.engine import core
from aidnd.server.play.mechanics import items as mi
from aidnd.server.play.mechanics.items import (
    _materialize_npc,
    _materialize_zones,
    _zone_holder,
    _zone_stock,
)


def _fake_zones(monkeypatch, zones):
    monkeypatch.setattr(
        "aidnd.server.play.engine.zones.building_zones", lambda bid: ({}, zones)
    )


def test_materialize_idempotent_and_theft_sticks(tmp_path, monkeypatch):
    from aidnd.worldgen.store import WorldStore

    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(mi, "_store", lambda: st)
    monkeypatch.setattr(mi, "_wid", lambda: 1)
    _fake_zones(
        monkeypatch,
        [{"id": "z0", "kind": "tables", "name": "стол", "objects": [
            {"name": "щербатая кружка", "kind": "misc", "worth": 2,
             "afford": {"hunger": 0.1}},
            {"name": "дубовый стол", "kind": "misc", "fixed": True, "worth": 30},
        ]}],
    )
    _materialize_zones("b:1")
    stock = _zone_stock("b:1", "z0")
    assert {it["name"] for _iid, it in stock} == {"щербатая кружка", "дубовый стол"}
    fixed = {it["name"]: it.get("fixed") for _iid, it in stock}
    assert fixed["дубовый стол"] and not fixed["щербатая кружка"]

    # кружку унесли — повторная материализация НЕ возвращает её на стол
    mug = next(iid for iid, it in stock if it["name"] == "щербатая кружка")
    st.inv_move(1, mug, "pc")
    _materialize_zones("b:1")
    assert {it["name"] for _iid, it in _zone_stock("b:1", "z0")} == {"дубовый стол"}
    assert any(r["item_id"] == mug for r in st.inventory(1, "pc"))
    assert st.inventory(1, _zone_holder("b:1", "z0"))  # стол остался на месте


def test_materialize_npc_sanitizes_dict_shaped_pool_valuables(tmp_path, monkeypatch):
    """30 pool personas store `valuables` entries as dicts (e.g. {'item': ..., 'cost': ...})
    instead of plain strings — see data/debug/playtests/2026-07-14-grand2.md. Materializing
    such an NPC must not leak the dict's Python repr into the item's name (it ends up in
    haggle speech otherwise)."""
    from aidnd.worldgen.store import WorldStore

    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(mi, "_store", lambda: st)
    monkeypatch.setattr(mi, "_wid", lambda: 1)

    npc = SimpleNamespace(
        persona={
            "carry": {"goods": [], "personal": [], "coins": 0},
            "valuables": [{"item": "Медная пуговица", "cost": "1 медный"}],
        },
        work=None,
    )
    saved = dict(core._S._d())
    d = core._S._d()
    try:
        d.clear()
        d["wid"] = 1
        d["people"] = {"npc:but": npc}
        _materialize_npc("npc:but", layer="pockets")
        inv = st.inventory(1, "npc:but")
        assert len(inv) == 1
        item = st.get_item(inv[0]["item_id"])
        assert item["name"] == "Медная пуговица"
    finally:
        d.clear()
        d.update(saved)
