from aidnd.server.play.mechanics.items import _sane_name


def test_sane_name_dict_with_item_key():
    assert _sane_name({"item": "Медная пуговица", "cost": "1 медный"}) == "Медная пуговица"


def test_sane_name_dict_with_str_value_fallback():
    assert _sane_name({"cost": "5 медных"}) == "5 медных"


def test_sane_name_plain_string_passthrough():
    assert _sane_name("Ржавый нож") == "Ржавый нож"


def test_sane_name_degenerate_dict_no_repr_leak():
    """Review finding: a dict with no 'item' key and no str values fell through to str(s),
    leaking a Python repr like "{'cost': 5}" into item names/trade speech. Must return a
    generic placeholder instead."""
    assert _sane_name({"cost": 5}) == "вещица"
    assert _sane_name({}) == "вещица"
