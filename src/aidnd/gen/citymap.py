"""Настоящий граф города (перекрёстки + дома) поверх процедурного city-SVG.

Визуальный SVG генерит web/citygen.py; здесь из его выдачи берём НАСТОЯЩИЙ дататип:
- intersections — перекрёстки (узлы улиц) с координатами;
- edges — рёбра улиц;
- buildings — ключевые здания (game-id), привязанные к БЛИЖАЙШЕМУ перекрёстку (door = вход/выход).

На этом графе строится реальная система передвижения: путь по перекрёсткам (улица→улица),
вывески зданий вдоль маршрута, вход в здание с его двери. Здания остаются местами мира
(спатиаль/сейвы/квесты не трогаем) — CityGraph служит подложкой движения и открытия.
"""

from __future__ import annotations

import importlib.util
import os
from collections import deque

_CITYGEN = None


def _citygen():
    """Ленивая загрузка self-contained модуля web/citygen.py (чистый, без серверных зависимостей)."""
    global _CITYGEN
    if _CITYGEN is None:
        path = os.path.join(os.path.dirname(__file__), "..", "server", "web", "citygen.py")
        spec = importlib.util.spec_from_file_location("aidnd_citygen", path)
        _CITYGEN = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_CITYGEN)
    return _CITYGEN


def _blds(buildings: list) -> list:
    """Здания мира → формат citygen.build_city."""
    return [{"kind": "building", "dx": b["dx"], "dy": b["dy"], "name": b["name"],
             "affordances": b.get("affordances", []), "go": b.get("go"), "id": b["id"],
             "status": b.get("status", "open")} for b in buildings]


def build_graph(seed: int, buildings: list) -> CityGraph:
    """Собрать CityGraph для (seed, здания) — детерминированно (та же геометрия города, что в SVG)."""
    cg = _citygen()
    m = cg.build_city(int(seed), 980, 700, buildings=_blds(buildings), key_houses=[])
    g = CityGraph(cg.city_graph(m))
    g.profile = city_profile(m)
    return g


def city_profile(m: dict) -> dict:
    """ПОЛНЫЙ профиль города из процедурной генерации: строений, кварталов, река, стены, ворота, мосты."""
    hits = m.get("hits", [])
    return {
        "buildings": len(hits),                            # всего строений (дома + лендмарки)
        "houses": sum(1 for h in hits if h.get("house")),
        "landmarks": sum(1 for h in hits if h.get("landmark")),
        "wards": len(m.get("wards", [])),
        "has_river": bool(m.get("river_pts")),
        "has_walls": bool(m.get("wall_poly")),
        "gates": len(m.get("gate_edges", [])),
        "bridges": len(m.get("bridges", [])),
        "roads_out": len(m.get("roads_out", [])),
    }


def city_brief(profile: dict, settlement: str = "Фэндалин") -> str:
    """Краткая фактическая справка о городе для контекстов (NPC, нарратор и пр.)."""
    if not profile:
        return ""
    b = profile.get("buildings", 0)
    tier = "крупный город" if b > 600 else "город" if b > 200 else "городок"
    s = f"{settlement} — {tier}: ~{b} строений в {profile.get('wards', 0)} кварталах"
    feats = []
    if profile.get("has_river"):
        feats.append(f"его пересекает река, мостов — {profile.get('bridges', 0)}")
    if profile.get("has_walls"):
        feats.append(f"обнесён крепостной стеной, ворот — {profile.get('gates', 0)}")
    if profile.get("roads_out"):
        feats.append(f"дорог в округу — {profile['roads_out']}")
    if not feats:
        return s + "."
    tail = "; ".join(feats)
    return f"{s}. {tail[0].upper()}{tail[1:]}."


def _town_nodes(world) -> list:
    """Здания-узлы поселения из мира (для построения процедурного города/профиля), dx/dy по компасу."""
    from ..world.spatial import DIRECTIONS
    sp = world.spatial
    out = []
    for d, dest in sp.exits_of("place:phandalin_square").items():
        p = sp.places.get(dest)
        if not p:
            continue
        dx, dy = DIRECTIONS.get(d, (0.0, -0.55))
        out.append({"id": dest, "name": p.name, "kind": getattr(p, "kind", ""), "dx": dx, "dy": dy,
                    "affordances": list(getattr(p, "affordances", []) or []), "go": "идти в " + p.name,
                    "status": getattr(p, "status", "open")})
    return out


def profile_for(world, seed: int) -> dict:
    """Профиль города по миру+seed (детерминированно)."""
    cg = _citygen()
    m = cg.build_city(int(seed), 980, 700, buildings=_blds(_town_nodes(world)), key_houses=[])
    return city_profile(m)


class CityGraph:
    """Граф города: перекрёстки + рёбра + здания (door=ближайший перекрёсток). Пути — BFS."""

    def __init__(self, g: dict):
        self.intersections = g["intersections"]
        self.edges = g["edges"]
        self.buildings = g["buildings"]
        self.start = g.get("start", 0)
        self._adj: dict[int, list[int]] = {}
        for a, b in self.edges:
            self._adj.setdefault(a, []).append(b)
            self._adj.setdefault(b, []).append(a)
        self.door = {b["id"]: b["door"] for b in self.buildings if b.get("door") is not None}
        self.bld = {b["id"]: b for b in self.buildings}
        self.at_node: dict[int, list[str]] = {}            # перекрёсток → здания с дверью здесь
        for bid, nd in self.door.items():
            self.at_node.setdefault(nd, []).append(bid)
        self._build_proximity()                            # честная геометрическая близость (раз при сборке)

    def _build_proximity(self) -> None:
        """ЧЕСТНО (по геометрии, раз при сборке): для каждого перекрёстка — дома в физическом радиусе вокруг
        него (что видно, стоя на этом перекрёстке). Радиус ~2 длины уличного сегмента — соседние строения,
        а не весь город. Используется для вывесок: на перекрёстке/в пути видишь только прилегающие дома."""
        pos = {it["i"]: (it["x"], it["y"]) for it in self.intersections}
        segs = sorted((pos[a][0] - pos[b][0]) ** 2 + (pos[a][1] - pos[b][1]) ** 2
                      for a, b in self.edges if a in pos and b in pos)
        seg = (segs[len(segs) // 2] ** 0.5) if segs else 32.0   # медианный сегмент улицы
        r2 = (seg * 2.2) ** 2                                    # радиус «видно вокруг» (≈2 перекрёстка)
        bpos = {bid: pos[nd] for bid, nd in self.door.items() if nd in pos}
        self.around: dict[int, list[str]] = {}             # перекрёсток → дома в радиусе (соседние)
        for i, (x, y) in pos.items():
            blds = [bid for bid, (bx, by) in bpos.items() if (bx - x) ** 2 + (by - y) ** 2 <= r2]
            if blds:
                self.around[i] = blds

    def around_of(self, a_bld: str) -> list[str]:
        """Дома, прилегающие к перекрёстку здания a (видно, выйдя к нему), кроме самого a."""
        nd = self.door.get(a_bld)
        return [b for b in self.around.get(nd, []) if b != a_bld] if nd is not None else []

    def seen_along(self, a_bld: str, b_bld: str) -> list[str]:
        """Дома, мимо которых реально проходишь от a к b: на каждом перекрёстке пути — его прилегающие дома."""
        if a_bld not in self.door or b_bld not in self.door:
            return []
        out, seen = [], set()
        for nd in self._bfs_nodes(self.door[a_bld], self.door[b_bld]):
            for bid in self.around.get(nd, []):
                if bid != a_bld and bid not in seen:
                    seen.add(bid)
                    out.append(bid)
        return out

    def _bfs_nodes(self, src: int, dst: int) -> list[int]:
        """Кратчайший путь по перекрёсткам (список узлов), [] если недостижимо."""
        if src == dst:
            return [src]
        prev = {src: -1}
        q = deque([src])
        while q:
            n = q.popleft()
            if n == dst:
                break
            for m in self._adj.get(n, []):
                if m not in prev:
                    prev[m] = n
                    q.append(m)
        if dst not in prev:
            return []
        out, n = [], dst
        while n != -1:
            out.append(n)
            n = prev[n]
        return out[::-1]

    def path_steps(self, a_bld: str, b_bld: str) -> int:
        """Сколько перекрёстков пройти от здания a до здания b (0 если неизвестно/то же)."""
        if a_bld not in self.door or b_bld not in self.door:
            return 0
        p = self._bfs_nodes(self.door[a_bld], self.door[b_bld])
        return max(0, len(p) - 1)

    def buildings_along(self, a_bld: str, b_bld: str) -> list[str]:
        """Здания, чьи двери стоят на маршруте a→b (вывески, что видишь по пути). Без a и b."""
        if a_bld not in self.door or b_bld not in self.door:
            return []
        order = []
        for nd in self._bfs_nodes(self.door[a_bld], self.door[b_bld]):
            for bid in self.at_node.get(nd, []):
                if bid not in (a_bld, b_bld) and bid not in order:
                    order.append(bid)
        return order

    def near(self, a_bld: str, k: int = 4, max_dist: int | None = None) -> list[str]:
        """До k ближайших по улицам зданий от двери a (что видно «вокруг»), по возрастанию пути.
        max_dist (если задан) — не дальше стольких уличных шагов: «вокруг» = реально смежное, не весь район."""
        if a_bld not in self.door:
            return []
        src = self.door[a_bld]
        dist = {src: 0}
        q = deque([src])
        found: list[tuple[int, str]] = []
        while q:
            n = q.popleft()
            d = dist[n]
            if max_dist is not None and d > max_dist:
                continue
            for bid in self.at_node.get(n, []):
                if bid != a_bld:
                    found.append((d, bid))
            if max_dist is not None and d >= max_dist:
                continue                                  # дальше границы не расширяемся
            for m in self._adj.get(n, []):
                if m not in dist:
                    dist[m] = d + 1
                    q.append(m)
        found.sort(key=lambda t: t[0])
        out: list[str] = []
        for _, bid in found:
            if bid not in out:
                out.append(bid)
            if len(out) >= k:
                break
        return out
