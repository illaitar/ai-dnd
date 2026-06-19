"""Инвентарь (атомарность, торговля) и plausibility (док 04, док 06)."""

import random

from aidnd.inventory import container as inv
from aidnd.inventory.items import wallet_value_cp
from aidnd.plausibility import (
    Candidate,
    SpawnContext,
    check,
    discover,
    plausibility,
)


def test_item_move_atomic(world):
    # положим предмет в землю и перенесём игроку
    from aidnd.gen.item_gen import spawn_item
    inv_ground = inv.Container("ground:test", kind="ground", items=[])
    world.containers["ground:test"] = inv_ground
    iid = spawn_item(world, "tmpl:dagger", "ground:test")
    inv.move(world, "ground:test", "carry:hero", iid, actor="pc:hero")
    assert iid in world.containers["carry:hero"].items
    assert iid not in world.containers["ground:test"].items
    assert world.items[iid].location_ref == "carry:hero"


def test_buy_transfers_item_and_currency(world):
    before = wallet_value_cp(world.wallet("pc:hero"))
    shop = world.containers["shop:barthen"]
    iid = shop.items[0]
    price = inv.price_of(world, world.items[iid], shop, "pc:hero")
    inv.buy(world, "pc:hero", "shop:barthen", iid)
    assert iid in world.containers["carry:hero"].items
    after = wallet_value_cp(world.wallet("pc:hero"))
    assert after == before - price


def test_equip_changes_ac(world):
    # снимем щит → AC падает на 2
    ac_before = inv.armor_class(world, "pc:hero")
    inv.unequip(world, "pc:hero", "it:hero_shield")
    assert inv.armor_class(world, "pc:hero") == ac_before - 2


def test_plausibility_noble_vs_merchant():
    # док 06 §9.2: дворянин неправдоподобен в шахтёрском фронтире, торговец — да
    ctx = SpawnContext(location_type="frontier_town", party_tier=1,
                       world_flags=["post_redbrand_purge"])
    noble = Candidate("noble", "npc", 0.5, "noble", ecology=("manor",))
    merchant = Candidate("merchant", "npc", 0.6, "merchant_caravan", ecology=("frontier_town",))
    assert plausibility(noble, ctx) < plausibility(merchant, ctx)


def test_plausibility_forbids_zero():
    ctx = SpawnContext(location_type="frontier_town")
    banshee = Candidate("banshee", "monster", 1.0, "undead", forbidden_in=("frontier_town",))
    assert plausibility(banshee, ctx) == 0.0
    assert check(banshee, ctx, random.Random(1)) is False


def test_discover_passive_vs_active():
    ctx = SpawnContext(location_type="dungeon", search_dc=15)
    stash = Candidate("stash", "loot", 0.6, ecology=("dungeon",))
    # пассивно ниже DC, активный бросок выше DC → найдено
    assert discover(stash, ctx, passive_perception=13) is False
    assert discover(stash, ctx, passive_perception=13, player_roll_total=17) is True
    assert discover(stash, ctx, passive_perception=16) is True
