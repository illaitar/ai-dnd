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
    core._S._d().clear()
    core._S["wid"] = 1
    core._S["gt"] = 514
    return st


def test_accept_writes_quest_told(wired, monkeypatch):
    monkeypatch.setattr(world_mod, "_play", lambda: None, raising=False)
    wired.save_contract(1, "ct:odo:1", "offered",
                        {"giver": "odo", "giver_name": "Одо", "kind": "bring",
                         "want": "бочонок сидра", "where": "погреб"})
    asyncio.run(world_mod.contract_accept(_Req({"id": "ct:odo:1"})))
    r = wired.journal_list(1, kind="quest")
    assert len(r) == 1 and r[0]["prov"] == "told" and r[0]["refs"] == ["ct:odo:1"]
    assert r[0]["text"] == "взялся за дело для Одо: bring — бочонок сидра (погреб)"


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
