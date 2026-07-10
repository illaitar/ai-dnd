# tests/items/test_deception.py
from aidnd.items import inspect as item_inspect
from aidnd.items import normalize, view
from aidnd.items.model import Capability


def _forged_ring():
    """A gilded-brass ring passed off as gold: surface краса/ценность high, true low."""
    it = normalize({"kind": "trinket", "name": "перстень «под золото»", "form": "оправа",
                    "attrs": {"ценность": {"surface": 85, "true": 10},
                              "краса": {"surface": 80, "true": 40}}})
    it["id"] = "ring1"
    return it


def test_appraisal_deflates_a_forgery():
    it = _forged_ring()
    known = set()
    assert view(it, known)["worth_known"] is False
    surface_worth = view(it, known)["worth"]
    merchant = Capability(abilities={"int": 14}, competencies={"trade"})
    res = item_inspect(it, merchant, "appraise")
    known |= set(res["attr_groups"])                       # what the endpoint does
    v = view(it, known)
    assert v["worth_known"] is True and v["worth"] < surface_worth


def test_hidden_poison_surfaces_only_under_lore():
    it = normalize({"kind": "weapon", "name": "тонкий стилет", "form": "клинок",
                    "attrs": {"острота": {"surface": 70, "true": 70},
                              "скверна": {"surface": 0, "true": 65}}})
    it["id"] = "stiletto1"
    assert not [m for m in view(it, set())["mods"] if m["target"] == "special:poison"]
    sage = Capability(abilities={"int": 12}, competencies={"lore"})
    known = set(item_inspect(it, sage, "lore")["attr_groups"])
    assert [m for m in view(it, known)["mods"] if m["target"] == "special:poison"]
