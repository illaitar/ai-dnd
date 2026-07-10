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
    assert node_lookup("Кривой нож") == "нож"                 # whole word «нож» present
    assert node_lookup("несуществующая чепуха") is None


def test_node_lookup_avoids_substring_false_positives():
    assert node_lookup("Порог таверны") is None               # «рог» is not a whole word here
    assert node_lookup("Стоптанный каблук") is None           # not «лук»


def test_itemgraph_integrity():
    from aidnd.items.attrs import attr_graph
    from aidnd.items.model import ATTRS
    g = item_graph()
    A, mats, nodes = set(ATTRS), set(g["materials"]), set(g["nodes"])
    forms, procs = set(attr_graph()["forms"]), set(g["processes"])
    assert not (mats & nodes), f"id collision material/node: {mats & nodes}"
    for m, d in g["materials"].items():
        assert set(d) <= A, f"material {m}: unknown attrs {set(d) - A}"
    for p, d in g["processes"].items():
        assert set(d) <= A, f"process {p}: unknown attrs {set(d) - A}"
    for nid, n in g["nodes"].items():
        assert set(n.get("from", [])) <= (mats | nodes), f"{nid}: dangling from {set(n['from']) - (mats | nodes)}"
        assert not n.get("process") or n["process"] in procs, f"{nid}: unknown process {n.get('process')}"
        assert set(n.get("treatments") or []) <= procs, f"{nid}: unknown treatment"
        assert not n.get("form") or n["form"] in forms, f"{nid}: unknown form {n.get('form')}"
        node_attrs(nid)                                        # every node computes without error


def test_unknown_node_and_cycle_raise():
    with pytest.raises(KeyError):
        node_attrs("нет-такого-узла")
    cyclic = {"materials": {}, "processes": {}, "nodes": {"a": {"from": ["b"]}, "b": {"from": ["a"]}}}
    with pytest.raises(ValueError):
        node_attrs("a", cyclic)
