"""_voice folds salient structured character + current emotion into the prompt (one call). A
callous glad cultist and a shaken condemning priest get OPPOSITE bits. Boast beat at self_regard>0.8.
Spec §5 Example D."""
from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core
from aidnd.server.play.engine.narrator import voice as V
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


class _Capture:
    def __init__(self): self.calls = []
    def call(self, role, messages, **kw):
        self.calls.append(messages)
        return {"content": '{"say": "…", "player_tone": "neutral"}'}


def _npc(name, traits, wv, emotion):
    cfg = NpcConfig(id="npc:" + name, name=name, role="головорез", traits=traits, worldview=wv)
    st = NpcState.from_config(cfg)
    st.emotion.update(emotion)
    return SimpleNamespace(id="npc:" + name, name=name, role="головорез", state=st,
                           persona={}, portraits={}, work=None, keys=[])


@pytest.fixture
def wired(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    stub = _Capture()
    monkeypatch.setattr(core, "_model", lambda: stub)
    saved = dict(core._S._d()); d = core._S._d()
    try:
        d.clear(); d.update(wid=1, gt=600, city_name="Городок")
        yield stub
    finally:
        d.clear(); d.update(saved)


def test_cultist_glad_bits(wired):
    merek = _npc("merek", {"malice": 0.47, "bravery": 0.78, "pride": 0.45, "empathy": 0.16},
                 {"faith": "Багровый", "morals": {"death": 0.84, "authority": -0.6}, "taboos": []},
                 {"joy": 0.11, "fear": 0.20})
    V._voice(merek, {"affinity": 0.0}, "reply", "кто ты?")
    sys = wired.calls[-1][0]["content"]
    assert "НАТУРА" in sys and "храбр" in sys.lower()
    assert "смерть" in sys.lower()                          # death morals surfaced (буднична)
    assert "радост" in sys.lower() or "СЕЙЧАС" in sys       # current joy surfaced


def test_priest_shaken_condemning_bits(wired):
    osvin = _npc("osvin", {"empathy": 0.93, "bravery": 0.48, "devotion": 0.77},
                 {"faith": "Светлая-Мать", "morals": {"death": -0.5, "violence": -1.0},
                  "taboos": ["убийство"]},
                 {"distress": 0.40, "disgust": 0.76})
    V._voice(osvin, {"affinity": 0.0}, "reply", "кто ты?")
    sys = wired.calls[-1][0]["content"]
    assert "убийство" in sys.lower()                        # taboo surfaced
    assert "СЕЙЧАС" in sys                                   # shaken emotion surfaced


def test_boast_beat_at_high_self_regard(wired):
    brag = _npc("brag", {"pride": 0.95, "bravery": 0.95, "ambition": 0.9},
                {"morals": {}}, {})
    V._voice(brag, {"affinity": 0.0}, "reply", "кто ты?")
    sys = wired.calls[-1][0]["content"]
    assert "хвал" in sys.lower() or "больше, чем" in sys.lower() or "бахвал" in sys.lower()
