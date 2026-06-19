"""Манифест боевых карт сценария (main §14.4).

Боевая карта — ВИЗУАЛЬНАЯ подложка сцены боя (theatre-of-the-mind), а не
координатная механика: движок боя позиции не использует, токены раскладываются
по сторонам поверх изображения.

По умолчанию в server/web/maps/ лежат ОРИГИНАЛЬНЫЕ сгенерированные карты под
каноничными именами LMoP. Реальные карты модуля кладутся туда же с теми же
именами файлов — замена тривиальна (scripts/gen_battlemaps.py их перерисовывает).

Карты LMoP проприетарны Wizards of the Coast; для приватного некоммерческого
использования допустимо, для публичного релиза нужны открыто-лицензированные
ассеты (Forgotten Adventures / The MAD Cartographer free pack и т.п.).
"""

from __future__ import annotations

import json
import os

MAP_URL_PREFIX = "/static/maps/"
MAPS_DIR = os.path.join(os.path.dirname(__file__), "..", "server", "web", "maps")

# локация боя -> файл карты в server/web/maps/
BATTLEMAPS = {
    "place:cragmaw_klarg_cave": "cragmaw_hideout.png",
    "building:tresendar_manor": "redbrand_hideout.png",
    "place:phandalin_square": "phandalin.png",
}


def attach_battlemaps(world) -> None:
    """Привязывает файлы карт к узлам графа локаций (Place.battlemap)."""
    for pid, file in BATTLEMAPS.items():
        p = world.spatial.places.get(pid)
        if p:
            p.battlemap = file


def battlemap_url(world, place_id: str) -> str | None:
    p = world.spatial.places.get(place_id)
    return MAP_URL_PREFIX + p.battlemap if (p and p.battlemap) else None


def load_meta(place_id: str) -> dict | None:
    """Читает JSON-терраин боевой карты локации (для тактической сетки)."""
    file = BATTLEMAPS.get(place_id)
    if not file:
        return None
    path = os.path.join(MAPS_DIR, file.rsplit(".", 1)[0] + ".json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)
