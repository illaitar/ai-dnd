"""Тесты слоя насыщения (через StubEnricher — без LLM): scope keys/all, прогресс-батчи,
структура слоя, детерминизм."""

from __future__ import annotations

import math

import pytest

from aidnd.citygraph import CityParams, generate
from aidnd.worldgen import Progress, StubEnricher, enrich_city


@pytest.fixture(scope="module")
def city():
    return generate(CityParams(seed=7, key_buildings=8, river=True, walls=True))


# ----------------------------------------------------------------- прогресс - #
def test_progress_batches():
    p = Progress(total=50, max_concurrent=8)
    assert p.batches_total == math.ceil(50 / 8) == 7    # здания / макс одновременных
    for _ in range(50):
        p.tick(1)
    s = p.snapshot()
    assert s["done"] == 50 and s["pct"] == 100.0 and s["batch"] == p.batches_total


def test_progress_callback_fires():
    seen = []
    p = Progress(total=4, max_concurrent=2, on_update=lambda s: seen.append(s["done"]))
    p.tick(); p.tick(); p.tick(); p.tick()
    assert seen == [1, 2, 3, 4]


# -------------------------------------------------------------- насыщение --- #
def test_enrich_keys_only(city):
    enr = enrich_city(city, "keys", StubEnricher(), max_concurrent=4)
    assert set(enr.buildings) == set(city.key_buildings)         # ровно ключевые
    for b in enr.buildings.values():
        assert b.description and b.node >= 0
    assert enr.progress["done"] == len(city.key_buildings)
    assert enr.progress["batches_total"] == math.ceil(len(city.key_buildings) / 4)


def test_enrich_all_buildings(city):
    enr = enrich_city(city, "all", StubEnricher(), max_concurrent=16)
    expected = len(city.key_buildings) + sum(1 for h in city.houses.values() if not h.building)
    assert len(enr.buildings) == expected                       # ключевые + все дома
    assert enr.progress["total"] == expected
    # значимые здания получают доп-помещение (подвал), дома — нет
    assert any(b.sub_rooms for b in enr.buildings.values())


def test_enrichment_serializable(city):
    enr = enrich_city(city, "keys", StubEnricher(), max_concurrent=8)
    import json
    d = enr.to_dict()
    json.dumps(d, ensure_ascii=False)                           # сериализуемо
    assert d["scope"] == "keys" and d["buildings"]


def test_enrich_deterministic_with_stub(city):
    a = enrich_city(city, "keys", StubEnricher(), max_concurrent=8).to_dict()["buildings"]
    b = enrich_city(city, "keys", StubEnricher(), max_concurrent=8).to_dict()["buildings"]
    assert a == b
