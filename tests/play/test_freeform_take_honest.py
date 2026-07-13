"""F7: a take that resolves to a REAL zone item transfers it (inventory + narr); a take of an
item not present in the zone (hallucinated / null) returns an honest refusal and NEVER reaches
the free-narration arbiter (_say_aloud / _model). No sensory prose for a phantom pickup."""
from __future__ import annotations

import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.engine.session import persist
from aidnd.server.play.handlers import freeform
from aidnd.worldgen import WorldStore


class _Stub:
    """Narrator manager — must NOT be called for a phantom take (routing, not narration)."""
    def __init__(self):
        self.called = False

    def call(self, role, messages, **kw):
        self.called = True
        return {"content": "…ты хватаешь холодную рукоять…"}


@pytest.fixture
def world(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    for mod in (core, freeform):
        monkeypatch.setattr(mod, "_store", lambda: st, raising=False)
        monkeypatch.setattr(mod, "_wid", lambda: 1, raising=False)
    monkeypatch.setattr(freeform, "_pc_remember", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(freeform, "_play", lambda: (None, {}, {}, {}, "loc:x"))
    # one REAL zone item: a mug on the player's zone (must exist as an inventory row —
    # inv_move is an UPDATE, so the item needs a starting holder to be "picked up" from)
    st.save_item({"id": "it:mug", "name": "кружка", "kind": "vessel", "worth": 1})
    st.inv_add(1, "it:mug", holder="zone:z1")
    # a second REAL zone item with a short 3-letter noun name, for the short-noun tests
    st.save_item({"id": "it:knife", "name": "Зазубренный нож мясника", "kind": "weapon", "worth": 3})
    st.inv_add(1, "it:knife", holder="zone:z1")
    d = core._S._d(); saved = dict(d)
    try:
        d.clear()
        d.update(wid=1, gt=514, zone="z1",
                 live={"zone_names": {"z1": "у стойки"},
                       "zone_items": {"у стойки": {"кружка": "it:mug",
                                                    "Зазубренный нож мясника": "it:knife"}},
                       "zone_fixed": {}, "workers": {}})
        yield st
    finally:
        d.clear(); d.update(saved)


def test_real_zone_item_is_taken(world, monkeypatch):
    stub = _Stub()
    monkeypatch.setattr(freeform, "_model", lambda: stub, raising=False)
    res = freeform._attempt({"verb": "take", "item": "it:mug"}, {})
    assert any(r["item_id"] == "it:mug" for r in world.inventory(1, "pc"))   # really transferred
    assert not res.get("fail")
    assert not stub.called                                                  # no arbiter narration


def test_phantom_item_refused_without_narration(world, monkeypatch):
    stub = _Stub()
    monkeypatch.setattr(freeform, "_model", lambda: stub, raising=False)
    res = freeform._attempt({"verb": "take", "item": "it:ghost_knife",
                             "_text": "беру ржавый нож со стола"}, {})
    assert res.get("fail") is True
    assert not stub.called                                                  # NEVER free-narrated
    assert "холодную рукоять" not in " ".join(res["narr"])                  # no sensory prose
    assert world.inventory(1, "pc") == []                                   # inventory unchanged


def test_take_null_item_refused(world, monkeypatch):
    stub = _Stub()
    monkeypatch.setattr(freeform, "_model", lambda: stub, raising=False)
    res = freeform._attempt({"verb": "take", "item": None, "_text": "беру что-нибудь"}, {})
    assert res.get("fail") is True
    assert not stub.called


def test_named_mismatch_refused_without_transfer(world, monkeypatch):
    """F7b: parser resolved item=it:mug (a REAL zone item), but the player's raw text names a
    completely different object («золотой перстень») — code must NOT substitute the mug; this
    currently transfers (red before the F7b fix)."""
    stub = _Stub()
    monkeypatch.setattr(freeform, "_model", lambda: stub, raising=False)
    res = freeform._attempt(
        {"verb": "take", "item": "it:mug", "_text": "поднимаю с пола золотой перстень"}, {}
    )
    assert res.get("fail") is True
    assert not stub.called
    assert "холодную рукоять" not in " ".join(res["narr"])
    assert world.inventory(1, "pc") == []


def test_generic_take_phrase_still_transfers(world, monkeypatch):
    """A generic phrase naming no specific object must keep delivering whatever's there."""
    stub = _Stub()
    monkeypatch.setattr(freeform, "_model", lambda: stub, raising=False)
    res = freeform._attempt(
        {"verb": "take", "item": "it:mug", "_text": "беру предмет со стола"}, {}
    )
    assert any(r["item_id"] == "it:mug" for r in world.inventory(1, "pc"))
    assert not res.get("fail")
    assert not stub.called


def test_declension_form_still_transfers(world, monkeypatch):
    """«кружку» (accusative) must still stem-match «кружка» — declensions aren't a mismatch."""
    stub = _Stub()
    monkeypatch.setattr(freeform, "_model", lambda: stub, raising=False)
    res = freeform._attempt(
        {"verb": "take", "item": "it:mug", "_text": "беру кружку со стойки"}, {}
    )
    assert any(r["item_id"] == "it:mug" for r in world.inventory(1, "pc"))
    assert not res.get("fail")
    assert not stub.called


def test_short_noun_mismatch_refused_without_transfer(world, monkeypatch):
    """F7b finding 1: «нож» is a 3-char Russian noun — before the fix, _content_tokens dropped
    it (floor was 4 chars) so the mismatch guard no-op'd and the mug transferred anyway. The
    parser resolved item=it:mug (a REAL zone item, the mug) but the player named «нож» — a
    completely different object. Must refuse, not substitute the mug."""
    stub = _Stub()
    monkeypatch.setattr(freeform, "_model", lambda: stub, raising=False)
    res = freeform._attempt(
        {"verb": "take", "item": "it:mug", "_text": "беру нож со стола"}, {}
    )
    assert res.get("fail") is True
    assert not stub.called
    assert world.inventory(1, "pc") == []


def test_short_noun_legit_take_transfers(world, monkeypatch):
    """The same short noun «нож», when it stem-matches the resolved item's actual name
    («Зазубренный нож мясника»), must transfer normally — short nouns aren't just refused
    outright, they're compared like any other named token."""
    stub = _Stub()
    monkeypatch.setattr(freeform, "_model", lambda: stub, raising=False)
    res = freeform._attempt(
        {"verb": "take", "item": "it:knife", "_text": "беру нож со стола"}, {}
    )
    assert any(r["item_id"] == "it:knife" for r in world.inventory(1, "pc"))
    assert not res.get("fail")
    assert not stub.called


def test_mismatch_refusal_does_not_reroute_into_pickpocket(world, monkeypatch):
    """F7b finding 2 (latent, defensive): the mismatch-refusal recursion must null npc too —
    if a parser step carried both item and npc for a take, it must not fall through into the
    take+npc pickpocket branch, which would roll a real theft against a person that (here)
    doesn't even exist in `people`."""
    stub = _Stub()
    monkeypatch.setattr(freeform, "_model", lambda: stub, raising=False)
    res = freeform._attempt(
        {"verb": "take", "item": "it:mug", "npc": "p_x", "_text": "беру перстень"}, {}
    )
    assert res.get("fail") is True
    assert not stub.called
    assert world.inventory(1, "pc") == []
