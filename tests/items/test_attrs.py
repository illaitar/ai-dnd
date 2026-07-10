# tests/items/test_attrs.py
from aidnd.items.attrs import attr_graph

from aidnd.items.model import ATTRS


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
