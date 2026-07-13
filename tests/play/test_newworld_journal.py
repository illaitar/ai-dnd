"""newworld (permadeath/rebirth) must wipe the player's journal «Хроника» for the reset world_id —
a fresh town shouldn't carry over the previous life's chronicle rows (FIX 3)."""
from aidnd.worldgen import WorldStore


def test_destroy_world_clears_journal(tmp_path):
    st = WorldStore(str(tmp_path / "live.db"))
    st.journal_add(1, "event", "saw", [], "впервые вошёл в город", 100)
    assert st.journal_list(1) != []

    st.destroy_world(1)

    assert st.journal_list(1) == []


def test_destroy_world_leaves_other_worlds_journal_untouched(tmp_path):
    st = WorldStore(str(tmp_path / "live.db"))
    st.journal_add(1, "event", "saw", [], "world 1 row", 100)
    st.journal_add(2, "event", "saw", [], "world 2 row", 100)

    st.destroy_world(1)

    assert st.journal_list(1) == []
    assert len(st.journal_list(2)) == 1
