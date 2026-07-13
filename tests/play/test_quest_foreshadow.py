"""Фор-тень: реплика достигает контекста разума (как oath), тик считается, потом → offered."""
import os
import tempfile

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core
from aidnd.server.play.engine.quests import foreshadow as FS
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


def _store(monkeypatch):
    tmp = tempfile.mkdtemp()
    st = WorldStore(os.path.join(tmp, "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    return st


def _foreshadow_ct(st, left):
    st.save_contract(core._wid(), "ct:sift:npc:dunn:4320", "queued",
                     {"src": "sift", "giver": "npc:dunn", "giver_name": "Дунн",
                      "seed": {"pattern": "kin_debt"}, "roles": {"giver": "npc:dunn"},
                      "arc": {"beat": "foreshadow", "fore_left": left},
                      "framer": {"foreshadow": "Тебя гложет долг Марты — гроссбух у Ральфа."}})


def test_line_reaches_cast_and_counts_down(monkeypatch):
    st = _store(monkeypatch)
    monkeypatch.setitem(core.PB, "quest_foreshadow_ticks", 2)
    _foreshadow_ct(st, left=2)
    lines = FS.lines(["npc:dunn", "npc:other"])
    assert lines["npc:dunn"].startswith("Тебя гложет")
    assert "npc:other" not in lines
    ct = st.contracts(core._wid(), "queued")[0]
    assert ct["arc"]["fore_left"] == 1                 # один тик списан


def test_countdown_hits_zero_promotes_to_offered(monkeypatch):
    st = _store(monkeypatch)
    _foreshadow_ct(st, left=1)
    FS.lines(["npc:dunn"])                              # last foreshadow tick
    assert not st.contracts(core._wid(), "queued")
    off = st.contracts(core._wid(), "offered")
    assert off and off[0]["arc"]["beat"] == "offered"


def test_prompt_injects_foreshadow_like_oath():
    from aidnd.mind.llm_agent import _build_prompt_probe  # thin test hook (added below)
    npc = NpcState.from_config(NpcConfig(id="npc:dunn", name="Дунн"))
    ctx = {"foreshadow": {"npc:dunn": "Тебя гложет долг Марты."}}
    text = _build_prompt_probe(npc, ctx)
    assert "Тебя гложет долг Марты." in text
