"""Приватное эмерджентное предложение перебивает импровизированное; accept двигает arc в active."""
import os
import tempfile
from types import SimpleNamespace

from aidnd.server.play.engine import core
from aidnd.server.play.engine.quests import offer as O
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


def _store(monkeypatch):
    tmp = tempfile.mkdtemp()
    st = WorldStore(os.path.join(tmp, "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    return st


def _emergent(st):
    data = {"giver": "npc:dunn", "giver_name": "Дунн", "step": 0,
            "steps": [{"kind": "bring", "want": "гроссбух"}], "kind": "bring", "want": "гроссбух",
            "reward": 30, "pitch": "Верни гроссбух — тридцать монет.", "src": "sift",
            "seed": {"pattern": "kin_debt"}, "arc": {"beat": "offered"},
            "roles": {"giver": "npc:dunn", "villain": "npc:ralf"},
            "done_any": [{"type": "have", "item": "гроссбух"}]}
    st.save_contract(core._wid(), "ct:sift:npc:dunn:4320", "offered", data)


def test_emergent_offer_found_for_giver(monkeypatch):
    st = _store(monkeypatch)
    _emergent(st)
    off = O.emergent_offer("npc:dunn")
    assert off and off["src"] == "sift" and off["pitch"].startswith("Верни")
    assert O.emergent_offer("npc:ralf") is None


def test_accept_flips_to_active_and_bumps_arc(monkeypatch):
    import asyncio

    from aidnd.server.play.engine import world as W
    st = _store(monkeypatch)
    _emergent(st)

    class _Req:
        async def json(self):
            return {"id": "ct:sift:npc:dunn:4320"}

    core._S["people"] = {"npc:dunn": SimpleNamespace(
        name="Дунн", state=SimpleNamespace(memory=SimpleNamespace(add=lambda *a, **k: None)))}
    core._S.setdefault("pc", None)
    res = asyncio.run(W.contract_accept(_Req()))
    assert res.get("accepted")
    ct = next(c for c in st.contracts(core._wid(), "active") if c["id"] == "ct:sift:npc:dunn:4320")
    assert ct["arc"]["beat"] == "active"
