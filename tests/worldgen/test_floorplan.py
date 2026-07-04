"""Планировщик локаций: детерминированная раскладка зон в клетках + SVG (без LLM)."""

from __future__ import annotations

from aidnd.worldgen.floorplan import clamp_layout, plan_location, plan_svg, reachable
from aidnd.worldgen.furnish import zones_for


def _data(btype: str, size: str = "medium", kind: str = "key") -> dict:
    d = {"name": "Тест", "size": size}
    d["zones"] = zones_for(btype, d, kind)
    for z in d["zones"]:
        z["objects"] = [{"name": "стол", "fixed": True}, {"name": "кружка", "fixed": False}]
    return d


def test_all_zones_placed_no_overlap():
    for btype in ("Таверна", "Трактир с комнатами", "Целебница", "Конюшня", "Гильдия", "Храм"):
        d = _data(btype)
        plan = plan_location(d)
        placed = [r for fl in plan["floors"] for r in fl["zones"]] + \
                 [r for fl in plan["floors"] for r in fl.get("back", {}).get("rooms", [])]
        assert len(placed) == len(d["zones"]), btype                 # все зоны на плане
        hall = plan["floors"][0]
        for r in hall["zones"]:                                      # в границах зала
            assert 0 < r["x"] and r["x"] + r["w"] < hall["w"], (btype, r)
            assert 0 < r["y"] and r["y"] + r["h"] < hall["h"], (btype, r)
        seen = set()                                                 # без пересечений в зале
        for r in hall["zones"]:
            cells = {(r["x"] + i, r["y"] + j) for i in range(r["w"]) for j in range(r["h"])}
            assert not (cells & seen), (btype, r["name"])
            seen |= cells


def test_lockable_rooms_go_upstairs():
    plan = plan_location(_data("Трактир с комнатами"))
    assert len(plan["floors"]) == 2 and plan["floors"][1]["label"]
    assert all(r["lock"] for r in plan["floors"][1]["zones"])


def test_doors_reachable_and_rows_aligned():
    """Гарантии v2: все двери достижимы от входа; столы стоят РЯДАМИ (общие колонки), не россыпью."""
    for btype in ("Таверна", "Трактир с комнатами", "Целебница", "Конюшня", "Игорный дом"):
        for layout in ({}, {"windows": "right", "bar_wall": "right", "tables": "perimeter"},
                       {"density": "packed"}):
            d = _data(btype)
            d["layout"] = layout
            plan = plan_location(d)
            assert reachable(plan), (btype, layout)              # двери/лестница не заставлены
    d = _data("Таверна", size="large")
    plan = plan_location(d)
    hall = plan["floors"][0]
    tables = [r for r in hall["zones"] if r["kind"] == "tables"]
    xs = {r["x"] for r in tables}
    assert len(xs) <= max(2, len(tables) - 2), xs                # выровненные колонки-ряды
    aisle_x = hall["door"]["x"]
    for r in tables:                                             # главный проход свят
        assert not (r["x"] <= aisle_x < r["x"] + r["w"]), r


def test_clamp_layout():
    assert clamp_layout(None) == clamp_layout({}) == clamp_layout({"windows": "чушь"})
    assert clamp_layout({"windows": "right", "tables": "perimeter"})["windows"] == "right"


def test_deterministic_and_svg():
    d = _data("Таверна")
    p1, p2 = plan_location(d), plan_location(d)
    assert p1 == p2
    svg = plan_svg(p1)
    assert svg.startswith("<svg") and svg.endswith("</svg>") and "вход" in svg
    assert svg.count("<rect") >= len(d["zones"])
