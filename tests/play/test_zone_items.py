"""Кейс: материализация обстановки — предметы зон НАСТОЯЩИЕ (live.db), взятое не возвращается."""

from aidnd.server.play.mechanics import items as mi
from aidnd.server.play.mechanics.items import _materialize_zones, _zone_holder, _zone_stock


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
