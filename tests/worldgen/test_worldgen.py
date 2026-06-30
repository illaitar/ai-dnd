"""Тесты слоя насыщения (через StubEnricher — без LLM): двухфазность (здания → очередь суб-помещений),
богатые поля, отсутствие вложенности суб-помещений, прогресс-батчи по фазам, детерминизм."""

from __future__ import annotations

import math

import pytest

from aidnd.citygraph import CityParams, generate
from aidnd.worldgen import Progress, StubEnricher, enrich_city


@pytest.fixture(scope="module")
def city():
    return generate(CityParams(seed=7, key_buildings=8, river=True, walls=True))


# ----------------------------------------------------------------- прогресс - #
def test_progress_batches_and_label():
    p = Progress(total=50, max_concurrent=8, label="здания")
    assert p.batches_total == math.ceil(50 / 8) == 7
    assert p.snapshot()["phase"] == "здания"
    for _ in range(50):
        p.tick(1)
    s = p.snapshot()
    assert s["done"] == 50 and s["pct"] == 100.0 and s["batch"] == p.batches_total


def test_progress_callback_fires():
    seen = []
    p = Progress(total=4, max_concurrent=2, on_update=lambda s: seen.append(s["done"]))
    for _ in range(4):
        p.tick()
    assert seen == [1, 2, 3, 4]


# -------------------------------------------------------- богатые поля ------ #
def test_building_rich_fields(city):
    enr = enrich_city(city, "keys", StubEnricher(), max_concurrent=4)
    assert set(enr.buildings) == set(city.key_buildings)
    for b in enr.buildings.values():
        assert b.description and b.node >= 0
        assert b.type                                  # тип закреплён
        assert isinstance(b.services, list)            # услуги — список
    # значимые здания: есть услуги, хозяин, тайна
    assert any(b.services and b.keeper and b.secret for b in enr.buildings.values())


# ------------------------------------------ двухфазность: суб-помещения ----- #
def test_subrooms_generated_in_phase_two(city):
    enr = enrich_city(city, "keys", StubEnricher(), max_concurrent=4)
    subs = [s for b in enr.buildings.values() for s in b.sub_rooms]
    assert subs                                        # суб-помещения есть
    for s in subs:
        assert s.kind and s.access                     # из стаба (фаза 1)
        assert s.description and s.contents             # заполнено в фазе 2
        assert s.parent in enr.buildings               # привязка к родителю


def test_subrooms_have_no_nested_subrooms(city):
    enr = enrich_city(city, "keys", StubEnricher(), max_concurrent=4)
    for b in enr.buildings.values():
        for s in b.sub_rooms:
            assert not hasattr(s, "sub_rooms")          # у суб-помещения нет своих суб-помещений


def test_progress_two_phases(city):
    enr = enrich_city(city, "keys", StubEnricher(), max_concurrent=4)
    assert enr.progress["buildings"]["phase"] == "здания"
    assert enr.progress["buildings"]["done"] == len(city.key_buildings)
    assert enr.progress["subrooms"]["phase"] == "суб-помещения"
    n_subs = sum(len(b.sub_rooms) for b in enr.buildings.values())
    assert enr.progress["subrooms"]["done"] == n_subs


# -------------------------------------------------------------- scope all --- #
def test_enrich_all_buildings(city):
    enr = enrich_city(city, "all", StubEnricher(), max_concurrent=16)
    expected = len(city.key_buildings) + sum(1 for h in city.houses.values() if not h.building)
    assert len(enr.buildings) == expected
    assert enr.progress["buildings"]["total"] == expected


def test_enrichment_serializable_and_deterministic(city):
    import json
    a = enrich_city(city, "keys", StubEnricher(), max_concurrent=8).to_dict()
    b = enrich_city(city, "keys", StubEnricher(), max_concurrent=8).to_dict()
    json.dumps(a, ensure_ascii=False)
    assert a["buildings"] == b["buildings"]
    assert a["scope"] == "keys"
