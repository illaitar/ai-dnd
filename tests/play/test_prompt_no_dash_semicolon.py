"""Style rule: every prose-producing narrator/voice/DM system prompt must tell the LLM to avoid
the em-dash «—» and the semicolon «;» in its OUTPUT (an AI tell) — commas/periods/parens/colons
instead. Structured/JSON-decision prompts (intent arbiter, geo judge veto-only fields, npc_mind)
are untouched; this covers only the prompts whose output is player-facing prose.

The instruction line itself legitimately contains an em-dash and is Cyrillic — it is source code
written by us telling the model what NOT to do, not model output, so that's expected.
"""
from types import SimpleNamespace

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core
from aidnd.server.play.engine import geo as geo_mod
from aidnd.server.play.engine import journal as journal_mod
from aidnd.server.play.engine.narrator import scene_digest as sd
from aidnd.server.play.engine.narrator import voice as voice_mod
from aidnd.server.play.engine.quests import framing as framing_mod

_MARK = "НЕ используй тире «—» и точку с запятой «;»"


def test_dm_sys_has_punctuation_rule():
    assert _MARK in voice_mod._DM_SYS


def test_scene_digest_sys_has_punctuation_rule():
    assert _MARK in sd._SYS


def test_journal_sys_has_punctuation_rule():
    assert _MARK in journal_mod._J_SYS


def test_geo_router_sys_has_punctuation_rule():
    assert _MARK in geo_mod._ROUTER_SYS


def test_quest_framer_sys_has_punctuation_rule():
    assert _MARK in framing_mod._FRAMER_SYS


class _CaptureStub:
    """Stand-in ModelManager.call — captures the messages sent to the narrator LLM."""

    def __init__(self):
        self.calls = []

    def call(self, role, messages, **kw):
        self.calls.append(messages)
        return {"content": '{"say": "...", "player_tone": "neutral"}'}


def test_voice_bits_system_prompt_has_punctuation_rule(monkeypatch):
    saved = dict(core._S._d())
    d = core._S._d()
    d.clear()
    d.update(wid=1, gt=600, city_name="Городок", live={}, loc="loc:square")
    monkeypatch.setattr(core, "_binfo", lambda bid: {"name": "площадь"})
    monkeypatch.setattr(core, "_city_name", lambda: "Городок")
    stub = _CaptureStub()
    monkeypatch.setattr(core, "_model", lambda: stub)

    st = NpcState.from_config(NpcConfig(id="npc:m", name="Марья Ольхова", role="торговка"))
    npc = SimpleNamespace(id="npc:m", name="Марья Ольхова", role="торговка", state=st, persona={})
    try:
        voice_mod._voice(npc, {"affinity": 0.0}, "greet")
    finally:
        d.clear()
        d.update(saved)

    sys_content = stub.calls[-1][0]["content"]
    assert _MARK in sys_content
