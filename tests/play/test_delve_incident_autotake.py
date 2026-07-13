"""Playtest bug: POST /delve on an untaken city incident (lair id "inc|...") dropped straight
into incident_delve() with no board_take: no active contract, no map-mark, no accept journal
beat — and so no reward possible at the end. delve's inc| branch must auto-take the job first
(same bookkeeping board_take does for guild-board incidents) when the player hasn't already taken
it via the board, then proceed into the dungeon as before. Already-taken incidents must not be
double-booked."""
from __future__ import annotations

import asyncio

import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.engine.session import persist
from aidnd.server.play.handlers import board as board_mod
from aidnd.worldgen import WorldStore


class _Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


class _Voice:
    """Stub narrator so j_beat's single model call resolves without a live LLM."""
    def call(self, role, messages, **kw):
        return {"content": "взялся за дело"}


def _inc(iid="inc|1|gang"):
    return {"id": iid, "title": "Шайка у моста", "env": "slum", "cr": 1.2,
            "reward": 12, "goal": "clear", "bid": "b:bridge", "node": 7,
            "patron": None, "members": [], "captive": None}


@pytest.fixture
def wired(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    monkeypatch.setattr(board_mod, "_store", lambda: st, raising=False)
    monkeypatch.setattr(board_mod, "_wid", lambda: 1, raising=False)
    monkeypatch.setattr(board_mod, "_play", lambda: None, raising=False)
    monkeypatch.setattr(board_mod, "_pc_hp", lambda: 10, raising=False)
    monkeypatch.setattr(board_mod, "_guild_bid", lambda: None, raising=False)
    monkeypatch.setattr(core, "_model", lambda: _Voice(), raising=False)
    d = core._S._d(); saved = dict(d)
    try:
        d.clear()
        d["wid"] = 1
        d["gt"] = 100
        d["people"] = {}
        d["loc"] = None
        yield st
    finally:
        d.clear(); d.update(saved)


def _canned_dungeon(inc):
    return {"dungeon": {"name": inc["title"]}, "narr": [inc["title"]], "gt": 100}


def test_delve_untaken_incident_auto_takes_job(wired, monkeypatch):
    inc = _inc()
    monkeypatch.setattr(
        "aidnd.server.play.engine.incidents.incidents_active", lambda: [inc]
    )
    monkeypatch.setattr(
        "aidnd.server.play.handlers.dungeon.incident_delve", lambda i: _canned_dungeon(i)
    )
    from aidnd.server.play.engine.pc import hero as hero_mod
    seen_calls = []
    monkeypatch.setattr(hero_mod, "_mark_seen",
                        lambda bid, **kw: seen_calls.append(bid), raising=False)

    # RED (pre-fix) evidence lives in the commit history / can be reproduced by reverting the
    # delve inc| branch: no contract, no seen-mark, no journal row would exist here.
    res = asyncio.run(board_mod.delve(_Req({"lair": inc["id"]})))
    assert res["dungeon"]["name"] == inc["title"]

    ct = next((c for c in wired.contracts(1, "active") if c.get("target") == inc["id"]), None)
    assert ct is not None, "delve on an untaken incident must create an active contract"
    assert ct["kind"] == "clear"

    assert seen_calls == ["b:bridge"]                    # map-mark, like board_take gives it

    j = wired.journal_list(1, kind="quest")
    told = [e for e in j if e["prov"] == "accept"]
    assert len(told) == 1                                # one accept beat, not zero


def test_delve_already_taken_incident_does_not_double_book(wired, monkeypatch):
    inc = _inc()
    monkeypatch.setattr(
        "aidnd.server.play.engine.incidents.incidents_active", lambda: [inc]
    )
    monkeypatch.setattr(
        "aidnd.server.play.handlers.dungeon.incident_delve", lambda i: _canned_dungeon(i)
    )
    wired.save_contract(1, f"ct:inc:{inc['id']}", "active",
                        {"giver": "guild", "giver_name": "Гильдия", "kind": "clear",
                         "target": inc["id"], "target_name": inc["title"], "reward": 12,
                         "reward_item": None, "reward_name": None, "want": None,
                         "pitch": "", "why": "доска гильдии"})
    res = asyncio.run(board_mod.delve(_Req({"lair": inc["id"]})))
    assert res["dungeon"]["name"] == inc["title"]
    active = [c for c in wired.contracts(1, "active") if c.get("target") == inc["id"]]
    assert len(active) == 1                              # not duplicated
    j = wired.journal_list(1, kind="quest")
    assert [e for e in j if e["prov"] == "accept"] == []  # no fresh accept beat re-fired
