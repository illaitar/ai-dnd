"""Inc 1 play wiring: a src:"sift" contract closes predicate-driven and its completion advances the
giver's real Agenda cursor via the writeback hook; improvised contracts are provably untouched
(no writeback, step engine unchanged)."""

from __future__ import annotations

import pytest

from aidnd.mind import Body, Item, NpcConfig, NpcState, World
from aidnd.mind.agenda import Agenda, Milestone
from aidnd.server.play.engine import core
from aidnd.server.play.engine import deeds as dd
from aidnd.server.play.engine.session import persist
from aidnd.server.play.mechanics import contracts
from aidnd.worldgen import WorldStore


class _P:
    def __init__(self, name, role, done, cursor=0):
        self.name, self.role, self.work, self.persona = name, role, None, {}
        cfg = NpcConfig(id="npc:dunn", name=name, role=role)
        self.state = NpcState.from_config(cfg)
        self.state.agendas = [Agenda("вернуть гроссбух", "ambition", 0.7,
                                     [Milestone("вернуть гроссбух", "acquire", "цель", {}, done)])]
        self.state.agendas[0].cursor = cursor
        self.charisma = 0.3
        self.appearance = 0.3


@pytest.fixture
def world(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    # root-patch persist._STORE (the base every lazy _store() resolver hits, including journal's
    # own lazy import inside _contract_complete) so no journal_add call can leak into real live.db
    monkeypatch.setattr(persist, "_STORE", st)
    for mod in (core, contracts, dd):
        monkeypatch.setattr(mod, "_store", lambda: st, raising=False)
        monkeypatch.setattr(mod, "_wid", lambda: 1, raising=False)
    # keep _contract_complete's heavy store side-effects out of the way — Inc 1 tests the bridge
    monkeypatch.setattr(contracts, "_materialize_npc", lambda *a, **k: None)
    monkeypatch.setattr(contracts, "_pc_remember", lambda *a, **k: None)
    monkeypatch.setattr(contracts, "_npc_save", lambda *a, **k: None)
    monkeypatch.setattr(dd, "record", lambda *a, **k: None)
    people = {"npc:dunn": _P("Дунн", "горожанин", {"type": "have", "item": "гроссбух"})}
    core._S["people"] = people
    core._S["model"] = None                             # no LLM → writeback advances but skips replan
    st.purse_add(1, "npc:dunn", 40)
    st.purse_add(1, "pc", 0)
    return st, people


def _giver_holds(st, name):
    # a mind (state, world) where the giver carries `name` → _met(have) true
    def _fake(ct):
        p = core._S["people"][ct["giver"]]
        w = World()
        w.add(Body(id=ct["giver"], place="дом", loot=[Item(name, 0.5)]))
        return p.state, w
    return _fake


def test_sift_completion_writes_back_cursor(world, monkeypatch):
    st, people = world
    monkeypatch.setattr(contracts, "_giver_world", _giver_holds(st, "гроссбух Марты"))
    st.save_contract(1, "ct:dunn:1", "active", {
        "giver": "npc:dunn", "giver_name": "Дунн", "kind": "bring", "want": "гроссбух",
        "where": "", "step": 0, "steps": [{"kind": "bring", "want": "гроссбух"}],
        "reward": 30, "reward_item": None,
        "src": "sift", "arc": {"beat": "active"}, "roles": {"giver": "npc:dunn"},
        "done_any": [{"type": "have", "item": "гроссбух"}]})
    ct = next(c for c in st.contracts(1, "active") if c["id"] == "ct:dunn:1")
    contracts._contract_complete(ct)
    assert people["npc:dunn"].state.agendas[0].cursor == 1     # real agenda advanced
    assert st.contracts(1, "active") == []                     # contract closed


def test_improvised_completion_never_writes_back(world, monkeypatch):
    st, people = world
    monkeypatch.setattr(contracts, "_giver_world", _giver_holds(st, "гроссбух Марты"))
    st.save_contract(1, "ct:dunn:2", "active", {
        "giver": "npc:dunn", "giver_name": "Дунн", "kind": "bring", "want": "гроссбух",
        "where": "", "step": 0, "steps": [{"kind": "bring", "want": "гроссбух"}],
        "reward": 30, "reward_item": None})               # NO src → improvised
    ct = next(c for c in st.contracts(1, "active") if c["id"] == "ct:dunn:2")
    contracts._contract_complete(ct)
    assert people["npc:dunn"].state.agendas[0].cursor == 0     # untouched
    assert [c["id"] for c in st.contracts(1, "done")] == ["ct:dunn:2"]   # but still paid/closed


def test_sift_maybe_close_completes_only_predicate_met_sift(world, monkeypatch):
    st, people = world
    monkeypatch.setattr(contracts, "_giver_world", _giver_holds(st, "гроссбух Марты"))
    st.save_contract(1, "ct:sift", "active", {
        "giver": "npc:dunn", "giver_name": "Дунн", "kind": "dead", "target": "npc:ralf",
        "where": "", "step": 0, "steps": [{"kind": "dead", "target": "npc:ralf"}],
        "reward": 10, "reward_item": None, "src": "sift",
        "done_any": [{"type": "have", "item": "гроссбух"}]})   # already true via giver loot
    st.save_contract(1, "ct:imp", "active", {
        "giver": "npc:dunn", "giver_name": "Дунн", "kind": "bring", "want": "меч",
        "where": "", "step": 0, "steps": [{"kind": "bring", "want": "меч"}],
        "reward": 5, "reward_item": None})                # improvised — ignored by the sweep
    narr = contracts._sift_maybe_close()
    assert narr and "Уговор исполнен" in narr
    active = {c["id"] for c in st.contracts(1, "active")}
    assert active == {"ct:imp"}                            # only the sift one closed
    assert people["npc:dunn"].state.agendas[0].cursor == 1
