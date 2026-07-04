"""Грамматика рисунка: нормализация, бюджет силы, якорь, противоречия по кольцам, канонический хэш."""

from __future__ import annotations

from aidnd.magic import (
    anchor,
    base_law,
    circle_hash,
    classify,
    glyph_cost,
    known_ids,
    load,
    normalize,
    power_budget,
)


def test_load_dictionary():
    g = load()
    assert len(g["elements"]) == 6 and len(g["glyphs"]) == 12
    assert "огонь" in known_ids() and "стрела" in known_ids()


def test_normalize_accepts_strings_and_dicts():
    pts = normalize(["огонь", {"id": "стрела", "size": 0.9, "angle": 10, "ring": 1}])
    assert len(pts) == 2
    assert pts[0]["ring"] == 0 and pts[1]["ring"] == 1
    assert normalize(["нет-такого"]) == []


def test_size_and_ring_scale_budget():
    small = power_budget([{"id": "огонь", "size": 0.2, "angle": 0, "ring": 0}])
    big = power_budget([{"id": "огонь", "size": 0.9, "angle": 0, "ring": 0}])
    inner = power_budget([{"id": "огонь", "size": 0.9, "angle": 0, "ring": 1}])
    assert small < big and inner < big                      # крупный сильнее, внутреннее кольцо — тоньше
    assert glyph_cost("огонь", 0.9, 0) > glyph_cost("огонь", 0.2, 0)


def test_anchor_direction():
    assert anchor([{"id": "огонь", "size": 0.5, "angle": 0, "ring": 0}]) == "вовне/на цель"
    assert anchor([{"id": "огонь", "size": 0.5, "angle": 180, "ring": 0}]) == "на себя"
    spread = [{"id": "огонь", "size": 0.5, "angle": a, "ring": 0} for a in (0, 120, 240)]
    assert anchor(spread) == "вокруг"


def test_classify_empty_and_clean():
    assert classify([{"id": "больше", "size": 0.5, "angle": 0, "ring": 0}])["kind"] == "empty"
    assert classify(["огонь", "стрела"])["kind"] == "clean"


def test_opposing_elements_same_ring_wild_but_rings_tame():
    same = [{"id": "огонь", "size": 0.5, "angle": 0, "ring": 0},
            {"id": "лёд", "size": 0.5, "angle": 90, "ring": 0}]
    split = [{"id": "огонь", "size": 0.5, "angle": 0, "ring": 0},
             {"id": "лёд", "size": 0.5, "angle": 90, "ring": 1}]
    assert classify(same)["kind"] == "wild"
    assert classify(split)["kind"] == "clean"               # контраст на разных кольцах — обуздан


def test_hash_quantized_stable():
    a = [{"id": "огонь", "size": 0.5, "angle": 10, "ring": 0}]
    b = [{"id": "огонь", "size": 0.55, "angle": 12, "ring": 0}]   # чуть сдвинут — тот же закон
    c = [{"id": "огонь", "size": 0.9, "angle": 10, "ring": 0}]    # крупнее — другой закон
    assert circle_hash(a) == circle_hash(b) != circle_hash(c)
    assert circle_hash(["огонь", "стрела"]) == circle_hash(["огонь", "стрела"])


def test_base_law_within_budget():
    comp = ["огонь", "стрела", "больше"]
    law = base_law(comp)
    assert law["power"] <= max(1, round(power_budget(comp)))
    assert law["mech"].get("damage")
    assert law["name"]
