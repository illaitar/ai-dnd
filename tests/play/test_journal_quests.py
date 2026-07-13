# tests/play/test_journal_quests.py
"""Quest beats land in the chronicle via j_beat: accept → prov='accept', complete → prov='done',
each refs=[cid]. The narrator is stubbed (code owns the FACTS, the stub owns the wording)."""
from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


class _Voice:
    """Echoes the beat name back as the line, so tests can key off it without a live LLM."""
    def call(self, role, messages, **kw):
        user = messages[-1]["content"]
        beat = user.split("(", 1)[1].split(")", 1)[0] if "(" in user else "?"
        return {"content": f"[{beat}] {user[:40]}"}


def _npc(pid, name, role):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    return SimpleNamespace(id=pid, name=name, role=role, persona={}, state=st, keys=[], work=None)


@pytest.fixture
def wired(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    monkeypatch.setattr(core, "_model", lambda: _Voice())
    people = {"p_odo": _npc("p_odo", "Одо", "трактирщик")}
    saved = dict(core._S._d()); d = core._S._d()
    try:
        d.clear(); d.update(wid=1, gt=600, people=people)
        yield st
    finally:
        d.clear(); d.update(saved)


def _quest_rows(st):
    return st.journal_list(1, kind="quest")


def test_accept_writes_accept_beat(wired):
    from aidnd.server.play.engine.world import _accept_contract
    cid = "ct:odo:1"
    ct = {"id": cid, "giver": "p_odo", "giver_name": "Одо", "kind": "bring",
          "want": "бочонок сидра", "where": "погреб", "reward": 6}
    _accept_contract(cid, ct)
    r = [x for x in _quest_rows(wired) if x["refs"] == [cid]]
    assert len(r) == 1 and r[0]["prov"] == "accept"


def test_complete_writes_done_beat(wired):
    from aidnd.server.play.mechanics.contracts import _contract_complete
    cid = "ct:odo:1"
    ct = {"id": cid, "giver": "p_odo", "giver_name": "Одо", "kind": "bring",
          "want": "бочонок сидра", "where": "погреб", "reward": 6}
    wired.purse_set(1, "p_odo", 20) if hasattr(wired, "purse_set") else None
    _contract_complete(ct)
    r = [x for x in _quest_rows(wired) if x["refs"] == [cid] and x["prov"] == "done"]
    assert len(r) == 1
