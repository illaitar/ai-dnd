"""Бумажный рендер планов: смоук + детерминизм (сама красота проверяется галереей глазами)."""

from __future__ import annotations

from aidnd.worldgen.floorart import paper_svg
from aidnd.worldgen.floorplan import plan_location
from aidnd.worldgen.furnish import zones_for


def _data(btype: str) -> dict:
    d = {"name": "Тест «Проверочная»", "size": "medium"}
    d["zones"] = zones_for(btype, d, "key")
    for z in d["zones"]:
        z["objects"] = [{"name": "вещь", "fixed": True}]
    return d


def test_paper_smoke_all_types():
    for btype in ("Таверна", "Трактир с комнатами", "Целебница", "Конюшня", "Храм",
                  "Кузница", "Игорный дом", "Склад", "Баня", "Гильдия"):
        d = _data(btype)
        svg = paper_svg(plan_location(d, seed_key=btype), d, seed_key=btype)
        assert svg.startswith("<svg") and svg.endswith("</svg>"), btype
        assert "feTurbulence" in svg and "Georgia" in svg, btype        # бумага + подписи
        assert svg.count("<path") >= len(d["zones"]), btype             # штрихи глифов есть


def test_paper_deterministic():
    d = _data("Таверна")
    p = plan_location(d, seed_key="x")
    assert paper_svg(p, d, seed_key="x") == paper_svg(p, d, seed_key="x")
    assert paper_svg(p, d, seed_key="x") != paper_svg(p, d, seed_key="y")   # дрожь сидирована
