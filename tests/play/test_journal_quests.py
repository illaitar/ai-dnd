"""Hook 2: a contract's beats land in the chronicle — pitch (told), accept (told),
complete (saw) — all sharing refs=[contract id], in id order."""

import asyncio
from types import SimpleNamespace

import pytest

from aidnd.server.play.engine import core, journal
from aidnd.server.play.engine import world as world_mod
from aidnd.server.play.engine.pc import hero as hero_mod
from aidnd.server.play.mechanics import contracts as ct_mod
from aidnd.worldgen import WorldStore


class _Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


@pytest.fixture
def wired(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    for mod in (core, journal, world_mod, hero_mod, ct_mod):  # hero: _pc_remember resolves store here
        monkeypatch.setattr(mod, "_store", lambda: st, raising=False)
        monkeypatch.setattr(mod, "_wid", lambda: 1, raising=False)
    monkeypatch.setattr(journal, "_gt", lambda: 514)
    d = core._S._d()
    saved = dict(d)                    # snapshot the shared world-1 session blob...
    try:
        d.clear()
        d["wid"] = 1
        d["gt"] = 514
        yield st
    finally:
        d.clear()
        d.update(saved)                # ...and restore it so later tests keep their 'seed' etc.


def test_accept_writes_quest_told(wired, monkeypatch):
    monkeypatch.setattr(world_mod, "_play", lambda: None, raising=False)
    wired.save_contract(1, "ct:odo:1", "offered",
                        {"giver": "odo", "giver_name": "Одо", "kind": "bring",
                         "want": "бочонок сидра", "where": "погреб"})
    asyncio.run(world_mod.contract_accept(_Req({"id": "ct:odo:1"})))
    r = wired.journal_list(1, kind="quest")
    assert len(r) == 1 and r[0]["prov"] == "told" and r[0]["refs"] == ["ct:odo:1"]
    assert r[0]["text"] == "взялся за дело для Одо: принести — бочонок сидра (погреб)"


def test_accept_writes_quest_told_emergent_pitch(wired, monkeypatch):
    # emergent (src=sift) contract: summary speaks through its own pitch, no bare English
    # kind, no "None" (live-playtest bug: "bring — None" leaked when want/target_name absent)
    monkeypatch.setattr(world_mod, "_play", lambda: None, raising=False)
    wired.save_contract(
        1, "ct:yuna:1", "offered",
        {"giver": "yuna", "giver_name": "Юна Вересковый", "kind": "bring", "src": "sift",
         "pitch": "накопить на долг кузнецу за починку кадила"},
    )
    asyncio.run(world_mod.contract_accept(_Req({"id": "ct:yuna:1"})))
    r = wired.journal_list(1, kind="quest")
    assert len(r) == 1
    assert r[0]["text"] == (
        "взялся за дело для Юна Вересковый: накопить на долг кузнецу за починку кадила"
    )
    assert "None" not in r[0]["text"] and "bring" not in r[0]["text"]


def test_accept_writes_quest_told_no_want_no_none(wired, monkeypatch):
    # improvised contract with no want/target_name (e.g. "dead" kind) must never render "None"
    monkeypatch.setattr(world_mod, "_play", lambda: None, raising=False)
    wired.save_contract(1, "ct:odo:3", "offered",
                        {"giver": "odo", "giver_name": "Одо", "kind": "dead"})
    asyncio.run(world_mod.contract_accept(_Req({"id": "ct:odo:3"})))
    r = wired.journal_list(1, kind="quest")
    row = next(x for x in r if x["refs"] == ["ct:odo:3"])
    assert row["text"] == "взялся за дело для Одо: устранить"
    assert "None" not in row["text"]


def test_complete_writes_quest_saw(wired, monkeypatch):
    # _contract_complete pays out & closes; stub the heavy neighbours it calls.
    people = {"odo": SimpleNamespace(name="Одо", state=SimpleNamespace(
        rel=lambda who: {"trust": 0.0, "affinity": 0.0},
        memory=SimpleNamespace(add=lambda *a, **k: None)))}
    core._S["people"] = people
    monkeypatch.setattr(ct_mod, "_materialize_npc", lambda *a, **k: None)
    monkeypatch.setattr(ct_mod, "_npc_save", lambda *a, **k: None)
    monkeypatch.setattr(ct_mod, "_pc_remember", lambda *a, **k: None)
    monkeypatch.setattr(ct_mod, "_mt", lambda: 516, raising=False)
    import aidnd.server.play.engine.deeds as dd
    monkeypatch.setattr(dd, "record", lambda *a, **k: None, raising=False)
    wired.purse_add(1, "odo", 50)
    ct = {"id": "ct:odo:1", "giver": "odo", "kind": "bring",
          "want": "бочонок сидра", "reward": 5}
    ct_mod._contract_complete(ct)
    r = wired.journal_list(1, kind="quest")
    assert len(r) == 1 and r[0]["prov"] == "saw" and r[0]["refs"] == ["ct:odo:1"]
    assert r[0]["text"] == "выполнено для Одо: бочонок сидра доставлен"


def test_complete_writes_quest_saw_no_none_for_wantless_contract(wired, monkeypatch):
    # kind "dead" contract with no `want`/`target_name` — summary must never render "None"
    people = {"odo": SimpleNamespace(name="Одо", state=SimpleNamespace(
        rel=lambda who: {"trust": 0.0, "affinity": 0.0},
        memory=SimpleNamespace(add=lambda *a, **k: None)))}
    core._S["people"] = people
    monkeypatch.setattr(ct_mod, "_materialize_npc", lambda *a, **k: None)
    monkeypatch.setattr(ct_mod, "_npc_save", lambda *a, **k: None)
    monkeypatch.setattr(ct_mod, "_pc_remember", lambda *a, **k: None)
    monkeypatch.setattr(ct_mod, "_mt", lambda: 516, raising=False)
    import aidnd.server.play.engine.deeds as dd
    monkeypatch.setattr(dd, "record", lambda *a, **k: None, raising=False)
    wired.purse_add(1, "odo", 50)
    ct = {"id": "ct:odo:2", "giver": "odo", "kind": "dead", "reward": 5}
    ct_mod._contract_complete(ct)
    r = wired.journal_list(1, kind="quest")
    row = next(x for x in r if x["refs"] == ["ct:odo:2"])
    assert "None" not in row["text"]
    assert row["text"] == "выполнено для Одо: цель устранена"
