"""Мост к процедурному генератору (диаграмма Вороного и пр.) → чистый граф города.

Сам генератор (`citygraph/render.py`, порт citygen.js) наружу не виден: внешний код работает
только с City/CityParams. Здесь мы лишь вытаскиваем нейтральную геометрию (улицы, дома, мосты,
река, стена, ворота) и отдаём её графу.

Key functions
-------------
generate(params) -> City : run the Voronoi generator and wrap the raw geometry into a movement
    graph. The single public entry for "make me a city".
visual(params, ...) -> dict : the RICH SVG the /citydebug stand and the game map both render
    (full houses/river/walls); returns inner-SVG + canvas W×H so the interactive player layer
    overlays without coordinate shifts.
_citygen() : return the self-contained `render` module (build_city / render_svg). Kept as a thin
    accessor so call sites (routes_citydebug, this file) stay unchanged after the move out of
    server/web; it now backs a normal package import instead of the old importlib-by-path hack.
_extract / _gate_points : raw generator dict → neutral geometry contract, honouring river/walls.
"""

from __future__ import annotations

from . import render as _render_mod
from .graph import City
from .params import CityParams


def _citygen():
    """Self-contained генератор (build_city / render_svg) — теперь обычный модуль пакета."""
    return _render_mod


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


def visual(params: CityParams, chrome: bool = True, interactive: bool = False) -> dict:
    """Богатый визуал города — ТОТ ЖЕ рендер, что на /citydebug (полные дома с крышами, река,
    стены, мосты, площадь, районы). Тот же build_city(seed,W,H) → одна система координат 0 0 W H
    с графом, поэтому интерактивный слой (фигура игрока) кладётся поверх без сдвигов.

    interactive=True — каждый дом становится кликабельным полигоном `class="h" data-id="<house-id>"`
    (по этому id граф отдаёт перекрёсток дома). Встроенный скрипт/стиль рендера при этом вырезаем —
    клики навешивает фронт игры сам. Возвращает ВНУТРЕННЕЕ содержимое SVG + размеры холста W×H.
    """
    p = params.normalized()
    cg = _citygen()
    m = cg.build_city(p.seed, p.width, p.height, buildings=[], key_houses=[])
    full = cg.render_svg(m, chrome=chrome, marks=False, interactive=interactive)
    si = full.find("<style>.h{")                    # вырезать встроенный style+script интерактива
    if si != -1:
        se = full.find("</script>", si)
        full = full[:si] + (full[se + 9:] if se != -1 else full[si:])
    inner = full[full.index(">", full.index("<svg")) + 1: full.rindex("</svg>")]
    return {"inner": inner, "W": int(m["W"]), "H": int(m["H"])}
