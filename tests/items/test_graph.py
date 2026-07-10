import copy

import pytest

from aidnd.items import derive_effects
from aidnd.items.graph import combine, combine_item, item_graph, node_attrs, node_item, node_lookup


def test_raw_material_returns_base_profile():
    v = node_attrs("железная руда")
    assert v["вес"] == 60 and v.get("твёрдость", 0) == 20


def test_smelting_hardens_the_bar_over_the_ore():
    assert node_attrs("железный слиток")["твёрдость"] > node_attrs("железная руда")["твёрдость"]


def test_sword_derives_edge_and_hardness_down_the_chain():
    v = node_attrs("меч")
    assert v.get("острота", 0) > 0 and v.get("твёрдость", 0) > 0     # steel-blade lineage


def test_changing_iron_propagates_to_the_sword():
    g = copy.deepcopy(item_graph())
    before = node_attrs("меч", g)["твёрдость"]
    g["materials"]["железная руда"]["твёрдость"] = 90               # richer ore
    assert node_attrs("меч", g)["твёрдость"] > before               # cascades all the way up


def test_sword_yields_attack_via_derive_effects():
    assert [m for m in derive_effects(node_item("меч", "fine"))["mods"] if m["target"] == "attack"]


def test_quality_scales_a_materialized_node():
    crude = node_item("меч", "crude")["attrs"]["твёрдость"]["true"]
    exq = node_item("меч", "exquisite")["attrs"]["твёрдость"]["true"]
    assert exq > crude


def test_gunpowder_arrow_is_a_deterministic_exploding_projectile():
    # NOVEL combination — there is no authored «стрела с зарядом» node; the result is COMPUTED
    vec = combine(["стрела", "пороховой заряд"], "привязать")
    assert vec.get("острота", 0) > 0 and vec.get("взрывчатость", 0) > 0   # keeps the point, gains the bang
    item = combine_item(["стрела", "пороховой заряд"], "привязать", kind="weapon")
    assert item["form"] == "стрела"                                       # stays a projectile
    mods = derive_effects(item)["mods"]
    assert [m for m in mods if m["target"] == "attack"]                   # ranged attack
    assert [m for m in mods if m["target"] == "special:взрыв"]            # explodes on impact — no LLM


def test_node_lookup_resolves_aliases():
    assert node_lookup("меч") == "меч"
    assert node_lookup("Кривой нож") == "нож"
    assert node_lookup("несуществующая чепуха") is None


def test_unknown_node_and_cycle_raise():
    with pytest.raises(KeyError):
        node_attrs("нет-такого-узла")
    cyclic = {"materials": {}, "processes": {}, "nodes": {"a": {"from": ["b"]}, "b": {"from": ["a"]}}}
    with pytest.raises(ValueError):
        node_attrs("a", cyclic)
