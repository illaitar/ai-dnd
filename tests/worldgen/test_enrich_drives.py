"""Tests for Pass B NPC entity enrichment — the LLM-batch `mech.drives` slice
(docs/superpowers/specs/2026-07-15-npc-entity-enrichment-design.md §3.6, §4.1).

No live LLM call here (project rule / CI hygiene) — a fake ModelManager stands in for
`manager.call`, mirroring the house pattern (tests/play/test_journal_quests.py). Covers: the
parse/validate path (good JSON → structured drives; bad JSON → LLMBadOutput, no partial write),
adults-only eligibility, --resume skip, and idempotent persistence via write_drives.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from aidnd.inference import LLMBadOutput
from aidnd.worldgen import WorldStore
from aidnd.worldgen.enrich_drives import (
    DRIVE_KINDS,
    LLMDrives,
    StubDrives,
    build_ctx,
    eligible_rows,
    normalize_drives,
    write_drives,
)


def _fresh_store() -> WorldStore:
    return WorldStore(os.path.join(tempfile.mkdtemp(), "worlds.db"))


def _mk(store, pid, role, *, name="Бран Полынь", dependent=False, head=None,
        wants=None, fears=None, secret=None):
    mech = {"role": role}
    if dependent:
        mech["dependent"] = True
        mech["head"] = head
    persona = {"race": "человек", "wants": wants or [], "fears": fears or [], "secret": secret}
    store.save_person(pid, role, name, 0.3, 0.3, mech, persona, {}, seed=1)


class _FakeManager:
    """Stand-in for ModelManager — returns whatever `content` was queued for the next .call()."""

    def __init__(self, content: str | None):
        self.content = content
        self.calls = 0

    def call(self, role, messages, **kw):
        self.calls += 1
        assert role == "character_writer"
        return {"content": self.content}


# ── normalize_drives (parse/validate path) ──────────────────────────────────
def test_normalize_good_json_yields_structured_drives():
    data = {"drives": [
        {"kind": "revenge", "target": "обидчик из прошлого", "intensity": 0.8},
        {"kind": "wealth", "target": "нож получше", "amount": 15, "intensity": 0.5},
    ]}
    out = normalize_drives(data)
    assert out == [
        {"kind": "revenge", "target": "обидчик из прошлого", "intensity": 0.8},
        {"kind": "wealth", "target": "нож получше", "amount": 15, "intensity": 0.5},
    ]


def test_normalize_drops_unknown_kind_and_empty_target():
    data = {"drives": [
        {"kind": "wealth", "target": "", "intensity": 0.5},          # empty target → dropped
        {"kind": "greed", "target": "золото", "intensity": 0.5},      # not in DRIVE_KINDS → dropped
        {"kind": "faith", "target": "храм", "intensity": 0.9},        # valid
    ]}
    out = normalize_drives(data)
    assert out == [{"kind": "faith", "target": "храм", "intensity": 0.9}]


def test_normalize_clamps_intensity_and_caps_at_three():
    data = {"drives": [
        {"kind": "status", "target": f"цель{i}", "intensity": 5.0} for i in range(5)
    ]}
    out = normalize_drives(data)
    assert len(out) == 3
    assert all(d["intensity"] == 1.0 for d in out)


def test_normalize_drops_amount_for_non_wealth_kind():
    data = {"drives": [{"kind": "status", "target": "власть", "amount": 99, "intensity": 0.6}]}
    out = normalize_drives(data)
    assert "amount" not in out[0]


def test_normalize_bad_shape_returns_none():
    assert normalize_drives(None) is None
    assert normalize_drives({}) is None
    assert normalize_drives({"drives": "not a list"}) is None
    assert normalize_drives({"drives": []}) is None
    assert normalize_drives({"drives": [{"kind": "bogus", "target": "x"}]}) is None


def test_normalize_accepts_bare_top_level_array():
    """deepseek sometimes drops the {"drives": [...]} wrapper — a bare array is still valid."""
    data = [{"kind": "wealth", "target": "нож получше", "amount": 0, "intensity": 0.6}]
    out = normalize_drives(data)
    assert out == [{"kind": "wealth", "target": "нож получше", "amount": 0, "intensity": 0.6}]


def test_all_drive_kinds_accepted():
    for k in DRIVE_KINDS:
        out = normalize_drives({"drives": [{"kind": k, "target": "цель", "intensity": 0.5}]})
        assert out and out[0]["kind"] == k


# ── LLMDrives (good JSON → written; bad JSON → row skipped, no crash) ──────
def test_llm_drives_good_json_parsed():
    mgr = _FakeManager('{"drives": [{"kind": "wealth", "target": "монеты", "amount": 10, "intensity": 0.4}]}')
    ctx = build_ctx({"id": "pool:0001", "name": "Гвен", "role": "подёнщица",
                     "mech": {"role": "подёнщица"},
                     "persona": {"wants": ["накопить на нож"], "fears": [], "secret": None}})
    drives = LLMDrives(mgr).derive(ctx)
    assert drives == [{"kind": "wealth", "target": "монеты", "amount": 10, "intensity": 0.4}]
    assert mgr.calls == 1


def test_llm_drives_bare_array_content_parsed():
    mgr = _FakeManager('[{"kind": "revenge", "target": "обидчик", "intensity": 0.8}]')
    ctx = build_ctx({"id": "pool:0004", "name": "Гвен", "role": "подёнщица",
                     "mech": {"role": "подёнщица"}, "persona": {}})
    drives = LLMDrives(mgr).derive(ctx)
    assert drives == [{"kind": "revenge", "target": "обидчик", "intensity": 0.8}]


def test_llm_drives_bad_json_raises_no_partial_write():
    mgr = _FakeManager("not json at all, sorry")
    ctx = build_ctx({"id": "pool:0002", "name": "Освин", "role": "жрец",
                     "mech": {"role": "жрец"}, "persona": {"wants": [], "fears": [], "secret": None}})
    with pytest.raises(LLMBadOutput):
        LLMDrives(mgr).derive(ctx)


def test_llm_drives_empty_drives_list_raises():
    mgr = _FakeManager('{"drives": []}')
    ctx = build_ctx({"id": "pool:0003", "name": "Тень", "role": "бродяга",
                     "mech": {"role": "бродяга"}, "persona": {}})
    with pytest.raises(LLMBadOutput):
        LLMDrives(mgr).derive(ctx)


# ── eligible_rows: adults only, --resume skip ───────────────────────────────
def test_eligible_rows_skips_dependents():
    store = _fresh_store()
    _mk(store, "pool:0000", "горожанин")
    _mk(store, "pool:0001", "дитя", dependent=True, head="pool:0000")
    rows = eligible_rows(store)
    ids = {r["id"] for r in rows}
    assert ids == {"pool:0000"}


def test_eligible_rows_resume_skips_already_drived():
    store = _fresh_store()
    _mk(store, "pool:0000", "горожанин")
    _mk(store, "pool:0001", "кузнец")
    row = store.get_person("pool:0000")
    write_drives(store, row, [{"kind": "wealth", "target": "х", "intensity": 0.5}])

    all_rows = eligible_rows(store, resume=False)
    assert {r["id"] for r in all_rows} == {"pool:0000", "pool:0001"}

    resumed = eligible_rows(store, resume=True)
    assert {r["id"] for r in resumed} == {"pool:0001"}


# ── write_drives persists additive mech key, idempotent ─────────────────────
def test_write_drives_persists_and_is_idempotent():
    store = _fresh_store()
    _mk(store, "pool:0000", "горожанин", wants=["мир и покой"])
    row = store.get_person("pool:0000")
    drives = StubDrives().derive(build_ctx(row))
    write_drives(store, row, drives)

    saved = store.get_person("pool:0000")
    assert saved["mech"]["drives"] == drives
    assert saved["persona"] == row["persona"]     # persona untouched

    write_drives(store, saved, drives)             # re-run — no duplication
    saved2 = store.get_person("pool:0000")
    assert saved2["mech"]["drives"] == drives
