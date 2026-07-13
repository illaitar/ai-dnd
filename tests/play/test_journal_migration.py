"""Legacy purge: non-quest rows (person/place/event) are deleted ONCE per world behind the
journal_purged flag; quest rows (incl. old un-typed prov) survive. Idempotent on re-run.
Also asserts the ambient helpers are GONE from journal.py."""
import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.engine import journal as J
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    saved = dict(core._S._d()); d = core._S._d()
    try:
        d.clear(); d.update(wid=1, gt=600)
        yield st
    finally:
        d.clear(); d.update(saved)


def _seed_mixed(st):
    st.journal_add(1, "event", "heard1", [], "кто-то сболтнул", 100)
    st.journal_add(1, "person", "saw", ["p1"], "встретил кого-то", 101)
    st.journal_add(1, "place", "saw", ["b1"], "впервые вошёл", 102)
    st.journal_add(1, "quest", "told", ["c_old"], "старая нетипизированная строка", 103)  # legacy
    st.journal_add(1, "quest", "accept", ["c_new"], "Я взялся за дело.", 104)


def test_purge_deletes_nonquest_keeps_quest(store):
    _seed_mixed(store)
    J.purge_legacy_once(1)
    kinds = {r["kind"] for r in store.journal_list(1)}
    assert kinds == {"quest"}
    provs = {r["prov"] for r in store.journal_list(1, kind="quest")}
    assert provs == {"told", "accept"}                       # legacy un-typed quest row survives


def test_purge_is_idempotent(store):
    _seed_mixed(store)
    J.purge_legacy_once(1)
    st_rows = store.journal_list(1)
    J.purge_legacy_once(1)                                   # second call: flag set → no-op
    assert store.journal_list(1) == st_rows
    assert store.flag_get(1, "journal_purged")


def test_ambient_helpers_are_gone():
    for name in ("journal_feed", "j_event", "j_person", "j_person_once", "j_place"):
        assert not hasattr(J, name), f"{name} must be deleted from journal.py"
