"""Предметы: ось редкости, весовой пул (уникальные не повторяются), граф материалов."""

from aidnd.items import craft_path, loot_pool, rarity_price


def test_rarity_price_multiplier():
    assert rarity_price(20, "common") == 20
    assert rarity_price(20, "rare") == 44
    assert rarity_price(90, "unique") == 810


def test_pool_draw_tier_and_unique():
    tpl = loot_pool.seed_templates()
    assert len(tpl) >= 20
    rares = {loot_pool.draw(tpl, set(), f"s{i}", tier="rare")["data"]["rarity"] for i in range(30)}
    assert "common" not in rares                            # tier=rare отсекает обычное
    u = next(t for t in tpl if t["data"]["rarity"] == "unique")
    d = loot_pool.draw(tpl, {u["key"]}, "x", tier="unique")
    assert d is None or d["key"] != u["key"]                # выпавший уникальный больше не выпадет


def test_craft_path_through_material_graph():
    assert [e["to"] for e in craft_path({"железная руда"}, "стальной клинок")] \
        == ["железный слиток", "стальной клинок"]
    assert [e["to"] for e in craft_path({"древесина", "тетива"}, "деревянный лук")] \
        == ["доска", "древко", "деревянный лук"]
    assert craft_path({"древесина"}, "деревянный лук") is None   # без тетивы никак
    assert craft_path({"стальной клинок"}, "стальной клинок") == []   # уже есть


def test_craft_edges_carry_gates():
    for e in craft_path({"железная руда"}, "стальной клинок"):
        assert e.get("time", 0) > 0 and "place" in e         # у ребра — гейты (время/станок)
