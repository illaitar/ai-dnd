from aidnd.items import inspect as item_inspect
from aidnd.items.model import Capability

FORGERY = {"id": "f1", "kind": "trinket", "form": "оправа",
           "attrs": {"ценность": {"surface": 90, "true": 5}}, "hidden": []}
BLADE = {"id": "b1", "kind": "weapon", "form": "клинок",
         "attrs": {"острота": {"surface": 30, "true": 80}}, "hidden": []}


def test_appraiser_competency_reveals_value():
    merchant = Capability(abilities={"int": 12}, competencies={"trade"})
    assert "attr:value" in item_inspect(FORGERY, merchant, "appraise")["attr_groups"]


def test_craft_eye_needs_a_trained_hand():
    smith = Capability(abilities={"int": 10}, competencies={"metalwork"})
    layman = Capability(abilities={"int": 10})
    assert "attr:phys" in item_inspect(BLADE, smith, "craft_eye")["attr_groups"]
    assert "attr:phys" not in item_inspect(BLADE, layman, "craft_eye")["attr_groups"]


def test_glance_reveals_no_groups():
    anyone = Capability(abilities={"int": 20}, competencies={"trade", "metalwork", "lore"})
    assert item_inspect(FORGERY, anyone, "glance")["attr_groups"] == []


def test_expert_reveals_all_groups():
    res = item_inspect(FORGERY, Capability(abilities={"int": 10}), "expert")
    assert set(res["attr_groups"]) == {"attr:phys", "attr:value", "attr:arcane"}


def test_no_attrs_no_groups():
    legacy = {"id": "l1", "kind": "weapon", "attrs": {}, "hidden": []}
    assert item_inspect(legacy, Capability(abilities={"int": 20}), "expert")["attr_groups"] == []
