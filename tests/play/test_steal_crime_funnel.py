"""Last raw victim writer after the «единый контур психики» unification: `/api/play/steal`'s
CAUGHT branch (`handlers/crime.py`) hand-wrote the theft-victim tier (affinity floor, anchored,
anger, a memory line) instead of riding `core._witness_crime` — the SAME funnel `handlers/freeform.py`
already uses for its own (dead) pickpocket path. The route's observable behavior must stay: a
caught victim ends up angry, grudging, anchored, remembers the theft, and wanted/karma still grow
in the same shape — but now through `_witness_crime` → `_crime_affect` → the Event bus's victim
branch, not a hand-rolled write."""

from __future__ import annotations

import asyncio

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core
from aidnd.server.play.engine.session.config import PLAYER
from aidnd.server.play.handlers import crime


class _P:
    def __init__(self, name, pid, wv=None):
        self.id = pid
        self.name, self.role, self.work, self.persona = name, "завсегдатай", None, {}
        cfg = NpcConfig(id=pid, name=name, role="завсегдатай", worldview=wv or {})
        self.state = NpcState.from_config(cfg)


class _Req:
    def __init__(self, d):
        self.d = d

    async def json(self):
        return self.d


class _FakeRandom:
    """Deterministic LOW roll — guarantees the CAUGHT branch regardless of seed."""

    def __init__(self, seed):
        pass

    def randint(self, a, b):
        return 1


@pytest.fixture
def world(tmp_path, monkeypatch):
    from aidnd.server.play.engine.session import persist
    from aidnd.worldgen import WorldStore

    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    for mod in (core, crime):
        monkeypatch.setattr(mod, "_store", lambda: st, raising=False)
        monkeypatch.setattr(mod, "_wid", lambda: 1, raising=False)
    monkeypatch.setattr(crime, "_npc_save", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(crime, "_pc_remember", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(crime, "_materialize_npc", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(crime, "_voice", lambda *a, **k: "(поймал)", raising=False)

    people = {"npc:dunn": _P("Горм", "npc:dunn", {"morals": {"honesty": 0.5}})}
    crof = {"npc:dunn": "loc:x"}
    monkeypatch.setattr(crime, "_play", lambda: (None, people, crof, {}, "loc:x"))
    monkeypatch.setattr(crime, "random", type("R", (), {"Random": staticmethod(_FakeRandom)})())

    d = core._S._d()
    saved = dict(d)
    try:
        d.clear()
        d["wid"] = 1
        d["gt"] = 514
        d["live"] = {}
        d["model"] = None
        yield st, people
    finally:
        d.clear()
        d.update(saved)


def test_steal_caught_routes_victim_through_unified_funnel(world):
    st, people = world
    before_wanted = core._wanted()

    res = asyncio.run(crime.steal(_Req({"npc": "npc:dunn"})))

    assert res["caught"] is True
    p = people["npc:dunn"]
    rel = p.state.rel(PLAYER)
    assert rel["affinity"] <= -0.39                     # grudge-tier floor (min(cur, -0.4))
    assert rel["anchored"] is True                      # slow carrier — a caught thief is remembered
    assert p.state.emotion["anger"] >= 0.6               # deserved-anger floor fires
    assert any("карман" in m.text for m in p.state.memory.items)   # a memory line about the theft
    # wanted/karma unchanged in shape: still grows by weight + witnesses (same formula as before)
    assert core._wanted() > before_wanted


def test_steal_caught_no_raw_affinity_write_left_in_route():
    """Code-level guard: the CAUGHT branch must no longer hand-write `rel["affinity"] = min(...)`
    — it should call the shared funnel instead."""
    import inspect

    src = inspect.getsource(crime.steal)
    assert "rel[\"affinity\"]" not in src
    assert "_witness_crime" in src
