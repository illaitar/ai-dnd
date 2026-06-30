"""Тесты слоя насыщения (через StubEnricher — без LLM): фактшит-характеристики, scope keys/all,
прогресс-батчи, БД миров (store), детерминизм, хук картинок."""

from __future__ import annotations

import math

import pytest

from aidnd.citygraph import CityParams, generate
from aidnd.worldgen import (
    Progress,
    StubEnricher,
    WorldStore,
    build_prompt,
    enrich_city,
    get_imagegen,
    store_world,
)


@pytest.fixture(scope="module")
def city():
    return generate(CityParams(seed=7, key_buildings=8, river=True, walls=True))


def test_progress_batches():
    p = Progress(total=50, max_concurrent=8)
    assert p.batches_total == math.ceil(50 / 8) == 7
    for _ in range(50):
        p.tick(1)
    assert p.snapshot()["done"] == 50 and p.snapshot()["pct"] == 100.0


def test_building_factsheet_fields(city):
    enr = enrich_city(city, "keys", StubEnricher(), max_concurrent=4)
    assert set(enr.buildings) == set(city.key_buildings)
    for b in enr.buildings.values():
        d = b.data
        assert d["type"] and d["tier"] in ("poor", "modest", "comfortable", "wealthy")
        assert d["condition"] in ("pristine", "sound", "worn", "dilapidated")
        assert isinstance(d["features"], list) and isinstance(d["services"], list)
        assert "description" not in d                       # прозы НЕТ — только характеристики
        assert b.is_key and b.sign                          # ключевые с вывеской
    assert any(b.data["services"] and b.data["secret"] for b in enr.buildings.values())


def test_subrooms_inline(city):
    enr = enrich_city(city, "keys", StubEnricher(), max_concurrent=4)
    subs = [s for b in enr.buildings.values() for s in b.data["sub_rooms"]]
    assert subs
    for s in subs:
        assert s["kind"] and s["access"]
        assert isinstance(s["features"], list) and isinstance(s["contents"], list)


def test_enrich_all(city):
    enr = enrich_city(city, "all", StubEnricher(), max_concurrent=16)
    expected = len(city.key_buildings) + sum(1 for h in city.houses.values() if not h.building)
    assert len(enr.buildings) == expected
    # дома — это дома: не ключевые, без вывески
    homes = [b for b in enr.buildings.values() if not b.is_key]
    assert homes and all(b.sign is None for b in homes)


def test_store_roundtrip(city, tmp_path):
    store = WorldStore(str(tmp_path / "w.db"))
    enr = enrich_city(city, "keys", StubEnricher(), max_concurrent=8)
    store_world(store, 1, city, enr)
    assert store.count(1) == len(enr.buildings)
    assert store.find_world(city.params.seed, city.params.key_buildings,
                            city.params.river, city.params.walls, city.params.segment) == 1
    bid = next(iter(enr.buildings))
    row = store.get_building(1, bid)
    assert row and row["data"]["type"] and ("sub_rooms" in row["data"])


def test_deterministic_stub(city):
    a = enrich_city(city, "keys", StubEnricher(), max_concurrent=8).to_dict()["buildings"]
    b = enrich_city(city, "keys", StubEnricher(), max_concurrent=8).to_dict()["buildings"]
    assert a == b


def test_imagegen_hook():
    g = get_imagegen()
    assert g.available() is False                           # хук есть, провайдер не настроен
    assert g.generate("test") is None
    assert "fantasy" in build_prompt({"type": "таверна", "tier": "modest"}, sign="Клык")
