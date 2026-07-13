"""j_place gains a prov param (default 'saw' — regression-safe); _mark_seen can journal a
'told' reveal in one row. hero.py's default first-visit call stays 'saw'."""
import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.engine.journal import j_place
from aidnd.server.play.engine.pc.hero import _mark_seen, _seen
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    st.save_building(1, "b_smithy", True, 1, "кузница «Молот и мех»",
                     {"name": "кузница «Молот и мех»", "type": "кузница"})
    saved = dict(core._S._d()); d = core._S._d()
    try:
        d.clear(); d.update(wid=1, gt=600, seen=None)
        yield st
    finally:
        d.clear(); d.update(saved)


def _place_rows(st):
    return [r for r in st.journal_list(1, limit=100) if r["kind"] == "place"]


def test_j_place_default_prov_is_saw(store):
    j_place("впервые вошёл в кузницу", "b_smithy")
    rows = _place_rows(store)
    assert rows and rows[-1]["prov"] == "saw"


def test_j_place_told_prov(store):
    j_place("Ода рассказала дорогу к кузнице", "b_smithy", prov="told")
    rows = _place_rows(store)
    assert rows[-1]["prov"] == "told"
    assert "рассказала" in rows[-1]["text"]


def test_mark_seen_told_reveals_and_journals_once(store):
    _mark_seen("b_smithy", prov="told", text="Ода рассказала дорогу к кузнице «Молот и мех»")
    assert "b_smithy" in _seen()
    rows = _place_rows(store)
    assert len(rows) == 1 and rows[0]["prov"] == "told"       # ONE row, right provenance


def test_mark_seen_default_still_saw(store):
    _mark_seen("b_smithy")
    rows = _place_rows(store)
    assert len(rows) == 1 and rows[0]["prov"] == "saw"
    assert "впервые вошёл" in rows[0]["text"]
