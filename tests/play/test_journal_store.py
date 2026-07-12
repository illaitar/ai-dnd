"""journal table: append-only, newest-first, kind filter, cap-prune keeps the newest."""

from aidnd.server.play.engine import core
from aidnd.worldgen import WorldStore


def _store(tmp_path):
    return WorldStore(str(tmp_path / "live.db"))


def test_add_and_list_newest_first(tmp_path):
    st = _store(tmp_path)
    st.journal_add(1, "event", "heard2", [], "… так и не … Марты, …", 512)
    st.journal_add(1, "event", "saw", ["garm"], "Гарм ныряет рукой в чужой кошель", 512)
    st.journal_add(1, "person", "saw", ["odo"], "встретил Одо — трактирщик", 513)
    rows = st.journal_list(1)
    assert [r["gt"] for r in rows] == [513, 512, 512]          # newest id first
    assert rows[0]["kind"] == "person" and rows[0]["refs"] == ["odo"]
    assert rows[2]["prov"] == "heard2" and rows[2]["refs"] == []


def test_kind_filter_and_limit(tmp_path):
    st = _store(tmp_path)
    st.journal_add(1, "quest", "told", ["ct:odo:1"], "взялся за дело", 514)
    st.journal_add(1, "quest", "saw", ["ct:odo:1"], "выполнено для Одо", 516)
    st.journal_add(1, "person", "saw", ["odo"], "встретил Одо", 513)
    q = st.journal_list(1, kind="quest")
    assert len(q) == 2 and all(r["kind"] == "quest" for r in q)
    assert q[0]["prov"] == "saw" and q[1]["prov"] == "told"    # newest-first
    assert len(st.journal_list(1, limit=1)) == 1


def test_per_world_isolation(tmp_path):
    st = _store(tmp_path)
    st.journal_add(1, "event", "saw", [], "мир 1", 1)
    st.journal_add(2, "event", "saw", [], "мир 2", 1)
    assert [r["text"] for r in st.journal_list(1)] == ["мир 1"]
    assert [r["text"] for r in st.journal_list(2)] == ["мир 2"]


def test_cap_prune_keeps_newest(tmp_path, monkeypatch):
    st = _store(tmp_path)
    monkeypatch.setitem(core.PB, "journal_cap", 5)             # small cap for a fast test
    for i in range(6):                                          # one over the cap
        st.journal_add(1, "event", "saw", [], f"строка {i}", i)
    rows = st.journal_list(1, limit=100)
    assert len(rows) == 5                                       # count == cap
    assert rows[0]["text"] == "строка 5"                        # newest survives
    assert "строка 0" not in [r["text"] for r in rows]          # oldest pruned
