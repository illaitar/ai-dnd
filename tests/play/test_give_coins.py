"""FIX B: the player can GIVE COINS to an NPC — {"verb":"give","npc","coins":N} moves purses,
awards affinity like a gift, and runs the sift close on the spot so a wealth quest completes and
its writeback advances the giver's real agenda. Regression: give used to move ITEMS only, so
«накопить N монет» could never be satisfied by handing over coins."""

from __future__ import annotations

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.mind.agenda import wealth_agenda
from aidnd.server.play.engine import core
from aidnd.server.play.engine import deeds as dd
from aidnd.server.play.engine.session import persist
from aidnd.server.play.handlers import freeform
from aidnd.server.play.mechanics import contracts
from aidnd.worldgen import WorldStore


class _P:
    def __init__(self):
        self.name, self.role, self.work, self.persona = "Горм", "лавочник", None, {}
        cfg = NpcConfig(id="npc:dunn", name="Горм", role="лавочник")
        self.state = NpcState.from_config(cfg)
        self.state.agendas = [wealth_agenda("своё дело", goal=50.0)]   # milestone done = wealth|50
        self.charisma = 0.3
        self.appearance = 0.3


@pytest.fixture
def world(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)             # root-patch (journal's lazy store too)
    for mod in (core, contracts, freeform, dd):
        monkeypatch.setattr(mod, "_store", lambda: st, raising=False)
        monkeypatch.setattr(mod, "_wid", lambda: 1, raising=False)
    # keep _contract_complete's heavy side-effects out of the bridge's way
    monkeypatch.setattr(contracts, "_materialize_npc", lambda *a, **k: None)
    monkeypatch.setattr(contracts, "_pc_remember", lambda *a, **k: None)
    monkeypatch.setattr(contracts, "_npc_save", lambda *a, **k: None)
    monkeypatch.setattr(contracts, "_model", lambda: None)  # no LLM → writeback advances, skips replan
    monkeypatch.setattr(freeform, "_npc_save", lambda *a, **k: None)
    monkeypatch.setattr(freeform, "_pc_remember", lambda *a, **k: None)
    monkeypatch.setattr(dd, "record", lambda *a, **k: None)
    people = {"npc:dunn": _P()}
    monkeypatch.setattr(freeform, "_play",
                        lambda: (None, people, {}, {}, "loc:x"))
    core._S["people"] = people
    core._S["gt"] = 8 * 60
    st.purse_add(1, "pc", 100)
    st.purse_add(1, "npc:dunn", 5)
    return st, people


def test_give_coins_moves_purse_and_closes_wealth_quest(world):
    st, people = world
    st.save_contract(1, "ct:sift:npc:dunn:1", "active", {
        "giver": "npc:dunn", "giver_name": "Горм", "kind": "bring", "want": None,
        "where": "", "step": 0, "steps": [{"kind": "bring", "want": None}],
        "reward": 3, "reward_item": None, "src": "sift", "arc": {"beat": "active"},
        "roles": {"giver": "npc:dunn"}, "done_any": [{"type": "wealth", "value": 50}]})

    res = freeform._attempt({"verb": "give", "npc": "npc:dunn", "coins": 50}, {})

    assert res.get("refresh") and not res.get("fail"), res["narr"]
    joined = " ".join(res["narr"])
    assert "отсчитываешь 50" in joined and "Уговор исполнен" in joined
    # purses moved: pc 100 -50 = 50, then reward 3 back → 53; giver 5 +50 = 55, then -3 → 52
    assert st.purse_get(1, "pc") == 53
    assert st.purse_get(1, "npc:dunn") == 52
    # quest closed + real agenda advanced (writeback fired)
    assert st.contracts(1, "active") == []
    assert people["npc:dunn"].state.agendas[0].cursor == 1
    # gift affinity applied
    assert people["npc:dunn"].state.rel("pc")["affinity"] > 0


def test_give_more_coins_than_you_have_fails(world):
    st, people = world
    res = freeform._attempt({"verb": "give", "npc": "npc:dunn", "coins": 500}, {})
    assert res.get("fail")
    assert st.purse_get(1, "pc") == 100                    # untouched
    assert st.purse_get(1, "npc:dunn") == 5
