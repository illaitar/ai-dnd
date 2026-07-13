"""Директор: окно quest_active_max, перебивка ≥k×, протухание — паузит ТОЛЬКО показ, не разум."""
import os
import tempfile

from aidnd.server.play.engine import core
from aidnd.server.play.engine.quests import director as D
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


def _store(monkeypatch):
    tmp = tempfile.mkdtemp()
    st = WorldStore(os.path.join(tmp, "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    return st


def _queued(st, cid, beat="offered", score=1.0):
    st.save_contract(core._wid(), cid, "offered" if beat == "offered" else "queued",
                     {"src": "sift", "arc": {"beat": beat},
                      "seed": {"score": score, "pattern": "kin_debt"}, "giver": cid})


def test_window_full_blocks_weaker_new(monkeypatch):
    _store(monkeypatch)
    monkeypatch.setitem(core.PB, "quest_active_max", 1)
    monkeypatch.setitem(core.PB, "quest_interrupt_k", 2.0)
    _queued(core._store(), "ct:sift:a", beat="offered", score=1.0)   # window occupied
    assert D.active_count() == 1
    assert D.admit([{"score": 1.5, "pattern": "kin_debt", "giver": "npc:b",
                     "cast": {"villain": None}}]) is None            # 1.5 < 2.0×1.0 → blocked


def test_strong_new_interrupts(monkeypatch):
    _store(monkeypatch)
    monkeypatch.setitem(core.PB, "quest_active_max", 1)
    monkeypatch.setitem(core.PB, "quest_interrupt_k", 2.0)
    _queued(core._store(), "ct:sift:a", beat="offered", score=1.0)
    strong = {"score": 2.5, "pattern": "kin_debt", "giver": "npc:b", "cast": {"villain": None}}
    assert D.admit([strong]) is strong                              # 2.5 ≥ 2.0×1.0 → jumps window


def test_empty_window_admits_top(monkeypatch):
    _store(monkeypatch)
    monkeypatch.setitem(core.PB, "quest_active_max", 1)
    a = {"score": 3.14, "pattern": "kin_debt", "giver": "npc:a", "cast": {"villain": None}}
    b = {"score": 2.60, "pattern": "broken_promise", "giver": "npc:b", "cast": {"villain": None}}
    assert D.admit([a, b]) is a                                     # window free → highest
