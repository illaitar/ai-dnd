from aidnd.items import compose, derive_effects, normalize
from aidnd.items.attrs import attr_graph  # noqa: F401  (ensures export path is wired)


def test_normalize_passes_attrs_parts_form():
    it = normalize({
        "kind": "weapon", "name": "стальной нож", "form": "клинок",
        "parts": [{"role": "клинок", "material": "сталь", "treatments": ["заточка"]}],
        "attrs": {"острота": {"surface": 80, "true": 80}, "нет-такого": {"true": 5}},
    })
    assert it["form"] == "клинок"
    assert it["parts"][0]["material"] == "сталь"
    assert "острота" in it["attrs"] and "нет-такого" not in it["attrs"]   # unknown attr dropped
    assert it["attrs"]["острота"] == {"surface": 80, "true": 80}


def test_normalize_clamps_and_defaults_surface_to_true():
    it = normalize({"attrs": {"твёрдость": {"true": 150}, "краса": 40}})
    assert it["attrs"]["твёрдость"]["true"] == 100                        # clamped
    assert it["attrs"]["краса"] == {"surface": 40, "true": 40}            # scalar → surface==true


def test_legacy_item_unchanged():
    it = normalize({"kind": "weapon", "name": "ржавый нож", "worth": 3, "mods": []})
    assert it["attrs"] == {} and it["parts"] == [] and it["form"] == ""
    assert it["name"] == "ржавый нож" and it["kind"] == "weapon" and it["worth"] == 3


def test_compose_feeds_derive_via_normalize():
    parts = [{"role": "клинок", "material": "сталь", "treatments": ["заточка", "закалка"]}]
    vec = compose(parts, "fine")
    it = normalize({"kind": "weapon", "form": "клинок", "parts": parts,
                    "attrs": {a: {"surface": v, "true": v} for a, v in vec.items()}})
    eff = derive_effects(it)
    assert [m for m in eff["mods"] if m["target"] == "attack"]
