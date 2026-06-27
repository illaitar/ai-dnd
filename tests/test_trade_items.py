"""Торговля, вытягивание предметов из БД 5e и модификация свойств экземпляра.
Всё детерминированно (use_model=False)."""

from aidnd.bootstrap import new_session
from aidnd.inventory import container as inv
from aidnd.inventory.items import wallet_value_cp

BARTHEN = "building:barthens_provisions"


def _sess():
    from aidnd import config
    s = new_session(seed=1337, roster_size=4, use_model=False)
    s.world.clock.tick = 12 * 60 // config.SIM_MINUTES_PER_TICK   # полдень — лавки открыты (часы работы)
    s.world.wallet("pc:hero").update({"gp": 200})
    return s


def _at(s, place):
    s.world.commit("set_position", "pc:hero", target="pc:hero",
                   payload={"region": "region:phandalin", "place": place})


# --- вытягивание существующих предметов из БД D&D 5e ----------------------- #
def test_find_template_by_ru_and_en_name():
    s = _sess()
    assert inv.find_template(s.world, "длинный меч") == "tmpl:longsword"
    assert inv.find_template(s.world, "longsword") == "tmpl:longsword"
    assert inv.find_template(s.world, "кольчуж") == "tmpl:chain_shirt"
    assert inv.find_template(s.world, "несуществующее") is None


def test_pull_item_materializes_from_db():
    s = _sess()
    iid = inv.pull_item(s.world, "скимитар", "carry:hero", owner="pc:hero")
    assert s.world.items[iid].template_id == "tmpl:scimitar"
    assert iid in s.world.containers["carry:hero"].items


# --- модификация свойств: притупить клинок --------------------------------- #
def test_blunt_weapon_reduces_damage_and_renames():
    s = _sess()
    expr0, _, mag0 = inv.weapon_damage_expr(s.world, "pc:hero")
    assert expr0 == "1d8"
    inv.blunt_weapon(s.world, "it:hero_sword")
    expr1, _, mag1 = inv.weapon_damage_expr(s.world, "pc:hero")
    assert expr1 == "1d6" and mag1 == mag0 - 1          # кость ниже + штраф к урону
    inst = s.world.items["it:hero_sword"]
    assert inst.mods.get("dulled") and inst.custom_name.startswith("затупл")


def test_blunt_is_deterministic_event_sourced():
    a, b = _sess(), _sess()
    inv.blunt_weapon(a.world, "it:hero_sword")
    inv.blunt_weapon(b.world, "it:hero_sword")
    assert a.world.state_hash() == b.world.state_hash()  # модификация воспроизводима


# --- торговля у NPC-торговца ----------------------------------------------- #
def test_merchant_buy_charges_and_sell_pays():
    s = _sess()
    _at(s, BARTHEN)
    before = wallet_value_cp(s.world.wallet("pc:hero"))
    s.handle("купить кинжал")                          # покупка снимает золото
    mid = wallet_value_cp(s.world.wallet("pc:hero"))
    assert mid < before
    s.handle("продать зелье лечения")                  # продажа расходника возвращает часть
    after = wallet_value_cp(s.world.wallet("pc:hero"))
    assert after > mid


def test_merchant_only_buys_what_it_deals_in():
    s = _sess()
    _at(s, BARTHEN)                                    # Бартен торгует gear/consumable, не оружием
    # дадим герою лишний меч и попробуем продать — должно отказать
    sword = inv.pull_item(s.world, "длинный меч", "carry:hero", owner="pc:hero")
    r = s.handle("продать длинный меч")
    assert "не удалась" in r["text"] or "не торгует" in r["text"]
    assert sword in s.world.containers["carry:hero"].items   # меч остался у игрока


def test_shop_view_read_model():
    s = _sess()
    assert s.shop_view() is None                       # не у лавки
    _at(s, BARTHEN)
    sv = s.shop_view()
    assert sv and sv["merchant"] and sv["goods"]
    assert all("price_gp" in g for g in sv["goods"])
    assert any(x["name"].startswith("зелье") for x in sv["sellable"])  # расходник продаётся




def test_merchant_can_stock_pulled_item():
    """Бот-торговец «создаёт»/выставляет товар, вытянув его из БД 5e."""
    s = _sess()
    iid = inv.pull_item(s.world, "длинный меч", "shop:barthen")
    assert iid in s.world.containers["shop:barthen"].items
    assert s.world.items[iid].template_id == "tmpl:longsword"
