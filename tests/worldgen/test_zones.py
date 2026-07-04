"""Шаблоны зон локаций (content/zones.json + worldgen.furnish.zones_for) — без LLM."""

from __future__ import annotations

from aidnd.worldgen.furnish import NEEDS, _zone_for_container, zone_catalog, zones_for

KEY_TYPES = [  # палитра значимых зданий из scripts/buildinggen.py
    "Таверна", "Трактир с комнатами", "Кузница", "Лавка всякой всячины", "Лавка зелий и трав",
    "Храм", "Часовня", "Пекарня", "Мясная лавка", "Целебница", "Конюшня", "Склад",
    "Мастерская плотника", "Мастерская кожевника", "Швейная мастерская", "Дом старосты",
    "Гильдия", "Купеческий дом", "Ломбард-меняльня", "Рыбная лавка", "Оружейная лавка",
    "Свечная мастерская", "Гончарная мастерская", "Пивоварня", "Мельница у окраины",
    "Баня", "Игорный дом", "Книжная лавка писца",
]


def test_catalog_kinds_valid():
    cat = zone_catalog()
    for k, d in cat["kinds"].items():
        assert 0 <= d["noise"] <= 1 and 0 <= d["privacy"] <= 1 and d["cap"] >= 1, k
    used = {z["kind"] for t in cat["templates"] for z in t["zones"]}
    used |= {z["kind"] for z in cat["generic_key"]} | {z["kind"] for z in cat["residential"]}
    used |= {z["kind"] for t in cat["street"] for z in t["zones"]}
    assert used <= set(cat["kinds"]), used - set(cat["kinds"])


def test_every_key_type_gets_zones():
    for bt in KEY_TYPES:
        zs = zones_for(bt, {}, "key")
        assert 2 <= len(zs) <= 20, bt
        assert all(z["id"] and z["kind"] and z["name"] and "noise" in z for z in zs), bt
    # у таверны — стойка с постом, не generic
    tav = zones_for("Таверна", {}, "key")
    assert tav[0]["kind"] == "bar" and tav[0]["post"]


def test_group_instances():
    """Групповые якоря: каждый стол — СВОЯ зона (атом разговора), положение двигает приватность."""
    tav = zones_for("Таверна", {"size": "medium", "name": "Зубр"}, "key")
    tables = [z for z in tav if z.get("group") == "стол"]
    assert 5 <= len(tables) <= 9
    assert len({z["name"] for z in tables}) == len(tables)          # имена-положения уникальны
    assert len({z["privacy"] for z in tables}) > 1                  # угол приватнее прохода
    small = zones_for("Таверна", {"size": "small", "name": "Зубр"}, "key")
    large = zones_for("Таверна", {"size": "large", "name": "Зубр"}, "key")
    assert (len([z for z in small if z.get("group")])
            <= len([z for z in large if z.get("group")]))           # размер здания → больше столов
    inn = zones_for("Трактир с комнатами", {"size": "medium"}, "key")
    rooms = [z for z in inn if z["kind"] == "beds"]
    assert rooms and all(r.get("lockable") and r.get("group") for r in rooms)
    # детерминизм: тот же вход → тот же состав
    assert zones_for("Таверна", {"size": "medium", "name": "Зубр"}, "key") == tav


def test_res_and_street():
    res = zones_for("Дом рыбака", {}, "res")
    assert {z["kind"] for z in res} == {"hearth", "beds", "storage"}
    sq = zones_for("площадь", {}, "street")
    assert any(z["kind"] == "post" for z in sq)          # столб объявлений
    st = zones_for("улица", {}, "street")
    assert len(st) >= 1


def test_container_zone_address():
    zones = zones_for("Таверна", {}, "key")
    c = {"name": "сундук за стойкой", "where": "за стойкой"}
    assert _zone_for_container(c, zones) == zones[0]["id"]      # матч по слову «стойка» → bar
    c2 = {"name": "ларь", "where": "в углу"}
    zid = _zone_for_container(c2, zones)                        # нет совпадения → приватная/кладовая
    kinds = {z["id"]: z["kind"] for z in zones}
    assert kinds[zid] in ("storage", "private")


def test_needs_frozen():
    assert set(NEEDS) == {"fatigue", "hunger", "social", "purpose", "wealth", "comfort", "novelty"}
