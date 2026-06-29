"""Мост к процедурному генератору (диаграмма Вороного и пр.) → чистый граф города.

Сам генератор (server/web/citygen.py) загружается приватно и НАРУЖУ не виден: внешний код
работает только с City/CityParams. Здесь мы лишь вытаскиваем нейтральную геометрию
(улицы, дома, мосты, река, стена, ворота) и отдаём её графу.
"""

from __future__ import annotations

import importlib.util
import os

from .graph import City
from .params import CityParams

_CITYGEN = None


def _citygen():
    """Ленивая приватная загрузка self-contained генератора (без серверных зависимостей)."""
    global _CITYGEN
    if _CITYGEN is None:
        path = os.path.join(os.path.dirname(__file__), "..", "server", "web", "citygen.py")
        spec = importlib.util.spec_from_file_location("aidnd_citygen_core", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)          # сперва полностью загрузить…
        _CITYGEN = mod                        # …потом опубликовать (иначе гонка пустого модуля)
    return _CITYGEN


def _gate_points(gate_edges, wall_poly) -> list:
    """Ворота → точки. gate_edges генератора — ИНДЕКСЫ рёбер контура стены (берём середину ребра)."""
    out, n = [], len(wall_poly)
    for ge in gate_edges or []:
        try:
            if isinstance(ge, int):
                if 0 <= ge < n:
                    a, b = wall_poly[ge], wall_poly[(ge + 1) % n]
                    out.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
            elif isinstance(ge, dict) and ge.get("a") and ge.get("b"):
                a, b = ge["a"], ge["b"]
                out.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
            elif isinstance(ge, (list, tuple)) and len(ge) >= 2:
                a, b = ge[0], ge[1]
                out.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
        except (TypeError, IndexError, ValueError):
            pass
    return out


def _extract(m: dict, p: CityParams) -> dict:
    """Сырая геометрия генератора → нейтральный контракт для City. Учитывает флаги river/walls."""
    streets = m.get("streets") or {"nodes": [], "adj": []}
    nodes = [(float(x), float(y)) for x, y in streets["nodes"]]
    adj = [list(a) for a in streets["adj"]]
    houses = [{"id": h["id"], "x": h["x"], "y": h["y"]} for h in m.get("hits", []) if h.get("house")]
    keys = [{"id": h.get("id"), "name": h.get("name", ""), "kind": h.get("kind", ""),
             "x": h["x"], "y": h["y"]} for h in m.get("hits", []) if h.get("landmark")]
    if p.river:
        river = {"pts": [(float(x), float(y)) for x, y in (m.get("river_pts") or [])],
                 "w": float(m.get("river_w", 0) or 0)}
        bridges = [(float(b["cross"][0]), float(b["cross"][1]))
                   for b in (m.get("bridges") or []) if b.get("cross")]
    else:
        river, bridges = {"pts": [], "w": 0}, []
    wall_poly = m.get("wall_poly") or []
    walls = [(float(x), float(y)) for x, y in wall_poly] if p.walls else []
    gates = _gate_points(m.get("gate_edges"), wall_poly) if p.walls else []
    return {"nodes": nodes, "adj": adj, "houses": houses, "keys": keys,
            "river": river, "bridges": bridges, "walls": walls, "gates": gates}


def generate(params: CityParams) -> City:
    """Сгенерировать город по параметрам и вернуть готовый граф с системой передвижения."""
    p = params.normalized()
    m = _citygen().build_city(p.seed, p.width, p.height, buildings=[], key_houses=[])
    return City(p, _extract(m, p))
