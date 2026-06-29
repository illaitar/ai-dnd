"""Отдельная группа тестов графа города (модуль aidnd.citygraph).

Покрывает: генерацию, равномерность отрезков, раздел домов «один перекрёсток на дом»,
A*-маршрут как цепочку валидных реберных переходов между ключевыми точками, вывески,
детерминизм и параметры (река/стены).
"""

from __future__ import annotations

import statistics

import pytest

from aidnd.citygraph import CityParams, NodeKind, generate


@pytest.fixture(scope="module")
def city():
    return generate(CityParams(seed=7, key_buildings=16, river=True, walls=True))


# --------------------------------------------------------- генерация/граф --- #
def test_generate_builds_nonempty_graph(city):
    s = city.stats()
    assert s["nodes"] > 50
    assert s["edges"] > 50
    assert s["houses"] > 100
    assert s["key_buildings"] == 16
    assert s["by_kind"]["crossroad"] > 0
    assert s["by_kind"]["point"] > 0          # дороги реально разбиты на под-точки


def test_graph_connected_enough(city):
    # большинство узлов достижимы из произвольного — граф связен (один город)
    nodes = [n.id for n in city.nodes()]
    start = nodes[0]
    seen = {start}
    stack = [start]
    while stack:
        n = stack.pop()
        for m in city._adj[n]:           # noqa: SLF001 — белый ящик внутри тестов модуля
            if m not in seen:
                seen.add(m)
                stack.append(m)
    assert len(seen) >= 0.9 * len(nodes)


# --------------------------------------------------------- равные отрезки --- #
def test_segments_roughly_equal(city):
    lengths = [e.length for e in city.edges()]
    interval = city.stats()["interval"]
    med = statistics.median(lengths)
    assert 0.7 * interval <= med <= 1.3 * interval          # медиана у целевого интервала
    assert statistics.pstdev(lengths) < 0.45 * interval     # разброс мал → отрезки ~равные
    assert max(lengths) < 2.0 * interval                    # нет «длинных» необработанных рёбер


# --------------------------------------------------------- раздел домов ----- #
def test_house_partition_unique(city):
    # каждый дом приписан ровно к одному перекрёстку; суммарно покрыты все дома без дублей
    kps = city.key_points()
    total = sum(len(city.houses_at_crossroad(kp)) for kp in kps)
    assert total == len(city.houses)
    # обратная проверка: каждый дом в бакете СВОЕГО перекрёстка, и только там
    for h in city.houses.values():
        assert h.crossroad in set(kps)
        assert h.id in city.houses_at_crossroad(h.crossroad)
        others = sum(1 for kp in kps if kp != h.crossroad and h.id in city.houses_at_crossroad(kp))
        assert others == 0


def test_house_bound_to_nearest_crossroad(city):
    # «дом между ключевыми точками попадает только в одну» = в ближайшую
    import random
    rng = random.Random(1)
    xy = {n.id: (n.x, n.y) for n in city.nodes() if n.kind in
          (NodeKind.CROSSROAD, NodeKind.BRIDGE, NodeKind.GATE)}
    for h in rng.sample(list(city.houses.values()), 40):
        nearest = min(xy, key=lambda i: (xy[i][0] - h.x) ** 2 + (xy[i][1] - h.y) ** 2)
        assert h.crossroad == nearest


# --------------------------------------------------------- A* передвижение -- #
def test_route_is_chain_of_valid_edges(city):
    kbs = list(city.key_buildings)
    edge_set = {(min(e.a, e.b), max(e.a, e.b)) for e in city.edges()}
    r = city.route(kbs[0], kbs[8])
    assert r.found
    assert len(r.nodes) >= 2
    assert len(r.edges) == len(r.nodes) - 1
    for u, v in r.edges:                       # каждый переход — реальное ОДНО ребро графа
        assert (min(u, v), max(u, v)) in edge_set


def test_route_is_groups_of_transitions_through_crossroads(city):
    # «переход А→Б — это группа переходов по одной ключевой точке»: между соседними
    # перекрёстками маршрута лежат ТОЛЬКО под-точки (не другие перекрёстки)
    kbs = list(city.key_buildings)
    r = city.route(kbs[0], kbs[10])
    assert r.found
    cross_positions = [i for i, n in enumerate(r.nodes)
                       if city.node_kind(n) == NodeKind.CROSSROAD]
    assert len(cross_positions) >= 2
    for p, q in zip(cross_positions, cross_positions[1:]):
        between = r.nodes[p + 1:q]
        assert all(city.node_kind(n) != NodeKind.CROSSROAD for n in between)


def test_route_accepts_node_house_and_building(city):
    kb = next(iter(city.key_buildings.values()))
    some_house = next(h for h in city.houses.values() if h.building is None)
    assert city.route(kb.id, some_house.id).found            # здание → дом
    assert city.route(kb.node, some_house.node).found        # узел → узел
    assert city.route(some_house.id, kb.id).found            # дом → здание


def test_route_unknown_endpoint_not_found(city):
    kb = next(iter(city.key_buildings))
    assert city.route(kb, "house:does-not-exist").found is False
    assert city.route(999999, kb).found is False


def test_route_symmetric_length(city):
    kbs = list(city.key_buildings)
    a = city.route(kbs[0], kbs[5]).length
    b = city.route(kbs[5], kbs[0]).length
    assert abs(a - b) < 1e-6


# --------------------------------------------------------- вывески ---------- #
def test_signs_reference_real_key_buildings(city):
    kbs = list(city.key_buildings)
    found_any = False
    for i in (0, 4, 8):
        for j in (15, 11, 7):
            if i == j:
                continue
            r = city.route(kbs[i], kbs[j])
            for s in r.signs:
                found_any = True
                assert s.building in city.key_buildings
                assert s.building not in (kbs[i], kbs[j])     # не endpoints
    assert found_any                                          # хоть один маршрут даёт вывески


# --------------------------------------------------------- детерминизм ------ #
def test_deterministic_by_seed():
    a = generate(CityParams(seed=123, key_buildings=10, river=True, walls=True))
    b = generate(CityParams(seed=123, key_buildings=10, river=True, walls=True))
    assert a.debug_data() == b.debug_data()


def test_different_seed_differs():
    a = generate(CityParams(seed=1, key_buildings=8))
    b = generate(CityParams(seed=2, key_buildings=8))
    assert a.debug_data() != b.debug_data()


# --------------------------------------------------------- параметры -------- #
def test_river_toggle():
    on = generate(CityParams(seed=7, river=True, walls=False))
    off = generate(CityParams(seed=7, river=False, walls=False))
    assert on.river.get("pts")
    assert not off.river.get("pts")
    assert all(n.kind != NodeKind.BRIDGE for n in off.nodes())


def test_walls_toggle():
    on = generate(CityParams(seed=7, river=False, walls=True))
    off = generate(CityParams(seed=7, river=False, walls=False))
    assert on.walls
    assert not off.walls


def test_key_buildings_count_and_distinct_houses():
    c = generate(CityParams(seed=7, key_buildings=12))
    assert len(c.key_buildings) == 12
    houses = [kb.house for kb in c.key_buildings.values()]
    assert len(set(houses)) == 12                            # каждое — в своём доме
    for kb in c.key_buildings.values():
        assert c.houses[kb.house].building == kb.id          # дом помечен зданием


def test_segment_param_overrides_interval():
    c = generate(CityParams(seed=7, segment=20.0, key_buildings=4))
    assert abs(c.stats()["interval"] - 20.0) < 1e-6
