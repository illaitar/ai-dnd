from aidnd.items import normalize, view


def _mk(d):
    it = normalize(d)
    it["id"] = "vt"
    return it


def test_forgery_worth_flips_on_value_reveal():
    it = _mk({"kind": "trinket", "name": "перстень", "form": "оправа",
              "attrs": {"ценность": {"surface": 90, "true": 5}}})
    assert view(it, set())["worth"] > view(it, {"attr:value"})["worth"]
    assert view(it, {"attr:value"})["worth_known"] is True
    assert view(it, set())["worth_known"] is False


def test_shown_vector_and_unknown_count():
    it = _mk({"kind": "weapon", "name": "нож", "form": "клинок",
              "attrs": {"острота": {"surface": 30, "true": 80}}})
    v = view(it, set())
    assert v["attrs"]["острота"] == {"value": 30, "true_known": False}
    assert v["unknown"] == 3
    v2 = view(it, {"attr:phys"})
    assert v2["attrs"]["острота"] == {"value": 80, "true_known": True}
    assert v2["unknown"] == 2


def test_legacy_view_has_no_attrs_key_and_same_worth():
    it = _mk({"kind": "weapon", "name": "ржавый нож", "worth": 3, "apparent_worth": 3, "mods": []})
    v = view(it, set())
    assert "attrs" not in v and v["worth"] == 3
