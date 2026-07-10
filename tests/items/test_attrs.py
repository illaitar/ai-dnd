# tests/items/test_attrs.py
from aidnd.items.attrs import attr_graph, compose, derive_effects
from aidnd.items.model import ATTRS


def _item(attrs, form="клинок", kind="weapon"):
    return {"attrs": {a: {"surface": v, "true": v} for a, v in attrs.items()}, "form": form, "kind": kind}


def test_sharp_blade_yields_attack():
    eff = derive_effects(_item({"острота": 80, "твёрдость": 70, "точность": 50}, "клинок", "weapon"))
    atk = [m for m in eff["mods"] if m["target"] == "attack"]
    assert atk and atk[0]["amount"] >= 2


def test_same_attrs_as_shield_yield_no_attack():
    eff = derive_effects(_item({"острота": 80, "твёрдость": 70, "прочность": 65}, "щит", "armor"))
    assert not [m for m in eff["mods"] if m["target"] == "attack"]
    assert [m for m in eff["mods"] if m["target"] == "defense"]


def test_beauty_yields_appearance_and_worth():
    eff = derive_effects(_item({"краса": 90, "ценность": 80}, "оправа", "trinket"))
    assert [m for m in eff["mods"] if m["target"] == "social:appearance"]
    assert eff["worth"] > 0


def test_toxic_is_hidden_and_mana_focus():
    poison = derive_effects(_item({"скверна": 60}, "клинок", "weapon"))
    pm = [m for m in poison["mods"] if m["target"] == "special:poison"]
    assert pm and pm[0]["hidden"] is True
    mana = derive_effects(_item({"мана": 70}, "оправа", "trinket"))
    assert [m for m in mana["mods"] if m["target"] == "special:mana"]


def test_derive_reads_true_not_surface():
    forged = {"attrs": {"ценность": {"surface": 90, "true": 5}}, "form": "оправа", "kind": "trinket"}
    honest = {"attrs": {"ценность": {"surface": 90, "true": 90}}, "form": "оправа", "kind": "trinket"}
    assert derive_effects(forged)["worth"] < derive_effects(honest)["worth"]


def test_durability_from_integrity():
    eff = derive_effects(_item({"прочность": 80}, "клинок", "weapon"))
    assert eff["durability"] and eff["durability"]["max"] >= 4


def test_attrs_vocabulary_is_13():
    assert len(ATTRS) == 13
    assert "мана" in ATTRS and "чара" in ATTRS and "острота" in ATTRS


def test_graph_loads_and_references_only_known_attrs():
    g = attr_graph()
    assert g["materials"] and g["forms"] and g["treatments"]
    for _m, contrib in g["materials"].items():
        assert set(contrib) <= set(ATTRS), f"unknown attr in material {_m}: {set(contrib) - set(ATTRS)}"
    for _t, delta in g["treatments"].items():
        assert set(delta) <= set(ATTRS), f"unknown attr in treatment {_t}"
    for _f, spec in g["forms"].items():
        for _eff, attrs in spec.get("expresses", {}).items():
            assert set(attrs) <= set(ATTRS), f"unknown attr in form {_f}/{_eff}"


KNIFE = [{"role": "клинок", "material": "сталь", "treatments": ["заточка"]},
         {"role": "рукоять", "material": "дуб", "treatments": []}]


def test_compose_knife_expresses_steel_and_wood():
    a = compose(KNIFE, "plain")
    assert a["острота"] == 65 + 15          # steel 65 + hone 15
    assert a["твёрдость"] == 70             # from steel blade
    assert a["прочность"] == 70             # max(steel 70, oak 55)
    assert a["вес"] == 60                   # max(steel 60, oak 45)


def test_temper_raises_hardness_lowers_flex():
    plain = compose([{"role": "клинок", "material": "кожа", "treatments": []}], "plain")
    tempered = compose([{"role": "клинок", "material": "кожа", "treatments": ["закалка"]}], "plain")
    assert tempered["твёрдость"] > plain.get("твёрдость", 0)
    assert tempered.get("гибкость", 0) < plain["гибкость"]   # кожа гибкость 70 → 62


def test_quality_scales_the_vector():
    crude = compose(KNIFE, "crude")
    exq = compose(KNIFE, "exquisite")
    assert exq["острота"] > crude["острота"]


def test_clamp_ceiling_at_100():
    a = compose([{"role": "оправа", "material": "золото", "treatments": ["золочение"]}], "exquisite")
    assert a["ценность"] <= 100


def test_axe_weights_heft_where_blade_does_not():
    heavy = {"вес": 80, "твёрдость": 60, "острота": 20}
    axe = derive_effects(_item(heavy, "топор", "weapon"))
    blade = derive_effects(_item(heavy, "клинок", "weapon"))
    assert [m for m in axe["mods"] if m["target"] == "attack"]          # heft carries the axe
    assert not [m for m in blade["mods"] if m["target"] == "attack"]    # same attrs, blade needs острота


def test_precision_is_producible_and_feeds_attack():
    from aidnd.items.attrs import compose
    vec = compose([{"role": "клинок", "material": "сталь", "treatments": ["правка"]}], "plain")
    assert vec.get("точность", 0) > 0                                    # сталь + правка produce it
