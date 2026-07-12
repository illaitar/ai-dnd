"""Thin journal wrappers: resolve wid/store/gt internally; safe no-op with no session."""

import pytest

from aidnd.server.play.engine import journal
from aidnd.worldgen import WorldStore


@pytest.fixture
def wired(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(journal, "_store", lambda: st)
    monkeypatch.setattr(journal, "_wid", lambda: 1)
    monkeypatch.setattr(journal, "_gt", lambda: 512)
    return st


def test_j_event_default_empty_refs(wired):
    journal.j_event("heard2", "… так и не … Марты, …")
    r = wired.journal_list(1)
    assert r == [{"gt": 512, "kind": "event", "prov": "heard2",
                  "refs": [], "text": "… так и не … Марты, …"}]


def test_j_event_with_refs(wired):
    journal.j_event("saw", "Гарм ныряет рукой в чужой кошель", refs=["garm"])
    assert wired.journal_list(1)[0]["refs"] == ["garm"]


def test_j_quest_wraps_cid(wired):
    journal.j_quest("told", "взялся за дело для Одо", "ct:odo:1")
    r = wired.journal_list(1)[0]
    assert r["kind"] == "quest" and r["prov"] == "told" and r["refs"] == ["ct:odo:1"]


def test_j_person_wraps_pid(wired):
    journal.j_person("saw", "встретил Одо — трактирщик", "odo")
    r = wired.journal_list(1)[0]
    assert r["kind"] == "person" and r["refs"] == ["odo"]


def test_j_place_is_always_saw(wired):
    journal.j_place("впервые вошёл в Трактир «Пьяный вол»", "b:tav")
    r = wired.journal_list(1)[0]
    assert r["kind"] == "place" and r["prov"] == "saw" and r["refs"] == ["b:tav"]


def test_no_session_is_noop(monkeypatch):
    def boom():
        raise RuntimeError("no live session")
    monkeypatch.setattr(journal, "_store", boom)
    monkeypatch.setattr(journal, "_wid", lambda: None)
    assert journal.j_event("saw", "x") is None                 # never raises
    assert journal.j_person("saw", "x", "p") is None
