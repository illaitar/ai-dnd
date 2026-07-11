"""Предметы: ось редкости, весовой пул (уникальные не повторяются)."""

from aidnd.items import loot_pool, rarity_price


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
