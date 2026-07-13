"""GET /api/play/journal groups quest rows into per-quest threads: gt-ascending within a дело,
дела newest-beat-first, enriched title/giver/status from the live contract. Legacy un-typed rows
and orphan cids still render."""
import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.engine.session import persist
from aidnd.server.play.handlers import misc as misc_mod
from aidnd.worldgen import WorldStore


@pytest.fixture
def wired(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    monkeypatch.setattr(misc_mod, "_play", lambda: None)
    # дело A (roza): offer→accept→done, out of gt order on insert
    st.journal_add(1, "quest", "done", ["cA"], "Так и завершилось это дело.", 22080)
    st.journal_add(1, "quest", "offer", ["cA"], "Ко мне обратилась Роза.", 20940)
    st.journal_add(1, "quest", "accept", ["cA"], "Я согласился.", 21360)
    # дело B (gwen): a single later offer → should float ABOVE A (latest beat gt bigger)
    st.journal_add(1, "quest", "offer", ["cB"], "Ко мне обратилась Гвен.", 30000)
    st.save_contract(1, "cA", "done",
                     {"giver": "p_roza", "giver_name": "Роза Медовар", "kind": "bring"})
    st.save_contract(1, "cB", "active",
                     {"giver": "p_gwen", "giver_name": "Гвен Тихвуд", "kind": "befriend"})
    saved = dict(core._S._d()); d = core._S._d()
    try:
        d.clear(); d.update(wid=1)
        yield st
    finally:
        d.clear(); d.update(saved)


def test_groups_into_dela_newest_first(wired):
    out = misc_mod.journal_endpoint()
    dela = out["dela"]
    assert [g["cid"] for g in dela] == ["cB", "cA"]           # B's latest beat (30000) > A's (22080)


def test_thread_is_gt_ascending(wired):
    dela = {g["cid"]: g for g in misc_mod.journal_endpoint()["dela"]}
    gts = [t["gt"] for t in dela["cA"]["thread"]]
    assert gts == [20940, 21360, 22080]                      # story order regardless of insert order
    beats = [t["beat"] for t in dela["cA"]["thread"]]
    assert beats == ["offer", "accept", "done"]


def test_enrichment_title_giver_status(wired):
    dela = {g["cid"]: g for g in misc_mod.journal_endpoint()["dela"]}
    assert dela["cA"]["giver"] == "Роза Медовар"
    assert dela["cA"]["status"] == "done"
    assert "Роза Медовар" in dela["cA"]["title"] and "добыть" in dela["cA"]["title"]


def test_orphan_cid_renders_unknown(wired):
    wired.journal_add(1, "quest", "offer", ["cGhost"], "Некое забытое дело.", 40000)
    g = next(x for x in misc_mod.journal_endpoint()["dela"] if x["cid"] == "cGhost")
    assert g["status"] == "unknown" and g["thread"][0]["text"] == "Некое забытое дело."


def test_empty_journal(wired):
    fresh = misc_mod.journal_endpoint
    # wipe rows: a brand-new world id has none
    core._S._d()["wid"] = 999
    assert fresh()["dela"] == []
