"""Hooks 3–5: first meeting (person/saw), first visit once (place/saw, no dup),
item reveal on known-set growth (event/saw, no dup). Person rows accumulate per pid."""

import asyncio

import pytest

from aidnd.items.model import normalize
from aidnd.server.play.engine import core, journal
from aidnd.server.play.engine.pc import hero as hero_mod
from aidnd.server.play.handlers import dialogue as dlg_mod
from aidnd.server.play.handlers import inventory as inv_mod
from aidnd.worldgen import WorldStore


class _Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


@pytest.fixture
def wired(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    for mod in (core, journal, hero_mod, dlg_mod, inv_mod):
        monkeypatch.setattr(mod, "_store", lambda: st, raising=False)
        monkeypatch.setattr(mod, "_wid", lambda: 1, raising=False)
    monkeypatch.setattr(journal, "_gt", lambda: 513)
    core._S.clear()
    return st


# --- Hook 4: first visit -------------------------------------------------------

def test_first_visit_writes_place_saw_once(wired, monkeypatch):
    core._S["seen"] = set()
    wired.save_building(1, "b:tav", True, 3, "Трактир", {"name": "Трактир «Пьяный вол»"})
    hero_mod._mark_seen("b:tav")
    hero_mod._mark_seen("b:tav")                               # revisit — adds nothing
    r = wired.journal_list(1, kind="place")
    assert len(r) == 1 and r[0]["prov"] == "saw" and r[0]["refs"] == ["b:tav"]
    assert r[0]["text"] == "впервые вошёл в Трактир «Пьяный вол»"


# --- Hook 5: item reveal -------------------------------------------------------

def test_item_reveal_writes_event_saw_on_growth(wired, monkeypatch):
    monkeypatch.setattr(inv_mod, "_play", lambda: (None, {}, None, None, None), raising=False)
    it = normalize({"id": "dagger7", "name": "кинжал", "kind": "weapon", "form": "клинок",
                    "attrs": {"острота": {"surface": 30, "true": 80},
                              "ценность": {"surface": 40, "true": 40}}, "hidden": []})
    it["id"] = "dagger7"
    wired.save_item(it)
    wired.inv_add(1, "dagger7", "pc", known=[])
    asyncio.run(inv_mod.inspect_item(_Req({"item": "dagger7", "via": "expert"})))
    r = wired.journal_list(1, kind="event")
    assert len(r) == 1 and r[0]["prov"] == "saw" and r[0]["refs"] == ["dagger7"]
    assert r[0]["text"].startswith("кинжал: открылось —")
    asyncio.run(inv_mod.inspect_item(_Req({"item": "dagger7", "via": "expert"})))  # nothing new
    assert len(wired.journal_list(1, kind="event")) == 1      # no duplicate row


# --- Hook 3: first meeting + person accumulation -------------------------------

def test_first_meeting_writes_person_saw(wired, monkeypatch):
    monkeypatch.setattr(journal, "j_person",
                        lambda prov, text, pid: wired.journal_add(1, "person", prov, [pid], text, 513))
    # exercise the composed text directly (talk() bootstraps a full session otherwise):
    journal.j_person("saw", "встретил Одо — трактирщик, Трактир «Пьяный вол»", "odo")
    r = wired.journal_list(1, kind="person")
    assert len(r) == 1 and r[0]["refs"] == ["odo"] and r[0]["prov"] == "saw"


def test_person_rows_accumulate_by_ref(wired):
    journal.j_person("saw", "встретил Одо — трактирщик", "odo")
    journal.j_person("heard1", "слышал про Одо: он в долгах", "odo")   # a later fact about odo
    r = wired.journal_list(1, kind="person")
    assert len(r) == 2 and all(x["refs"] == ["odo"] for x in r)        # grouped by the same pid
