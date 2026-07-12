"""GET /api/play/journal: newest-first entries, kind filter, limit cap (misc.py pattern)."""

import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.handlers import misc as misc_mod
from aidnd.worldgen import WorldStore


@pytest.fixture
def wired(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(core, "_store", lambda: st, raising=False)
    monkeypatch.setattr(core, "_wid", lambda: 1, raising=False)
    monkeypatch.setattr(misc_mod, "_play", lambda: None, raising=False)
    st.journal_add(1, "event", "heard2", [], "… Марты …", 512)
    st.journal_add(1, "person", "saw", ["odo"], "встретил Одо", 513)
    st.journal_add(1, "quest", "told", ["ct:odo:1"], "взялся за дело", 514)
    return st


def test_entries_newest_first(wired):
    out = misc_mod.journal_endpoint()
    assert list(out.keys()) == ["entries"]
    assert [e["gt"] for e in out["entries"]] == [514, 513, 512]
    assert out["entries"][0]["kind"] == "quest" and out["entries"][0]["refs"] == ["ct:odo:1"]


def test_kind_filter(wired):
    out = misc_mod.journal_endpoint(kind="person")
    assert len(out["entries"]) == 1 and out["entries"][0]["refs"] == ["odo"]


def test_limit_caps_length(wired):
    assert len(misc_mod.journal_endpoint(limit=1)["entries"]) == 1
