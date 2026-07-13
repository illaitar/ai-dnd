"""Кастинг (чистый код): reward = min(30, наличность); step — от Inc-1 bridge; DC растёт от статов злодея."""
import os
import tempfile

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core
from aidnd.server.play.engine.quests import casting as C
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


def _store(monkeypatch):
    tmp = tempfile.mkdtemp()
    st = WorldStore(os.path.join(tmp, "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    return st


def _villain(strong=False):
    cfg = NpcConfig(id="npc:ralf", name="Ральф", role="ростовщик",
                    traits={"malice": 0.8 if strong else 0.3})
    return NpcState.from_config(cfg)


def test_reward_clamped_by_real_purse(monkeypatch):
    st = _store(monkeypatch)
    st.purse_add(core._wid(), "npc:dunn", 41)
    giver = NpcState.from_config(NpcConfig(id="npc:dunn", name="Дунн"))
    seed = {"motivation": "serenity",
            "goal": {"kind": "acquire", "target": "debt:marta",
                     "done": {"type": "have", "item": "гроссбух"}}}
    out = C.cast(seed, giver, _villain(), st, core._wid())
    assert out["reward"] == 30                      # min(30, 41)
    assert out["step"]["kind"] == "bring" and out["step"]["want"] == "гроссбух"


def test_reward_clamped_when_poor(monkeypatch):
    st = _store(monkeypatch)
    st.purse_add(core._wid(), "npc:dunn", 12)
    giver = NpcState.from_config(NpcConfig(id="npc:dunn", name="Дунн"))
    seed = {"motivation": "serenity",
            "goal": {"kind": "acquire", "target": "debt:marta",
                     "done": {"type": "have", "item": "гроссбух"}}}
    out = C.cast(seed, giver, _villain(), st, core._wid())
    assert out["reward"] == 12                      # min(30, 12)


def test_cast_handles_villain_less_plain_need_seed(monkeypatch):
    """plain_need seeds have no villain — casting.cast(..., villain_state=None, ...) must fall back
    to a base DC / default danger rather than crashing on a None villain_state."""
    st = _store(monkeypatch)
    giver = NpcState.from_config(NpcConfig(id="npc:znah", name="Знахарка"))
    seed = {"motivation": "equipment",
            "goal": {"kind": "acquire", "target": "npc:smith", "done": {"type": "have", "item": "herbs"}}}
    out = C.cast(seed, giver, None, st, core._wid())
    assert out["dc"] == C._DC_BASE + round(0.3 * 10)   # default malice fallback (matches _villain(weak))
    assert out["danger"] == 0.3


def test_dc_rises_with_villain_malice(monkeypatch):
    st = _store(monkeypatch)
    giver = NpcState.from_config(NpcConfig(id="npc:dunn", name="Дунн"))
    seed = {"motivation": "justice",
            "goal": {"kind": "harm", "target": "npc:ralf", "done": {"type": "dead", "id": "npc:ralf"}}}
    weak = C.cast(seed, giver, _villain(strong=False), st, core._wid())
    strong = C.cast(seed, giver, _villain(strong=True), st, core._wid())
    assert strong["dc"] > weak["dc"]
