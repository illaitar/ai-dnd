"""Судья — один mgr.call, строгий JSON {rank,veto,why}; парс-сбой → пусто, LLM-падение → пробрасывается."""
import pytest

from aidnd.inference import LLMUnavailable
from aidnd.server.play.engine.quests import framing as F


def _seeds():
    return [
        {"pattern": "kin_debt", "sid": "seed_dunn_kindebt", "giver": "npc:dunn",
         "giver_name": "Дунн", "goal": {"done": {"type": "have", "item": "гроссбух"}},
         "cast": {"villain": "npc:ralf", "prize": "npc:marta"}, "evidence": ["d123"]},
        {"pattern": "broken_promise", "sid": "seed_marta_broken", "giver": "npc:marta",
         "giver_name": "Марта", "goal": {"done": {"type": "dead", "id": "npc:ralf"}},
         "cast": {"villain": "npc:ralf", "prize": None}, "evidence": ["d123"]},
    ]


_DEEDS = {"d123": {"id": "d123", "verb": "promise", "actor": "npc:ralf", "obj": "npc:marta",
                   "data": {"what": "вернуть гроссбух"}, "gt": 0}}
_NAMES = {"npc:dunn": "Дунн", "npc:ralf": "Ральф", "npc:marta": "Марта"}


class _Stub:
    def __init__(self, content):
        self.content = content
        self.seen = None

    def call(self, role, messages, **kw):
        self.seen = messages
        return {"content": self.content}


def test_judge_ranks_and_attaches_why():
    stub = _Stub('{"rank":["seed_dunn_kindebt","seed_marta_broken"],"veto":[],'
                 '"why":{"seed_dunn_kindebt":"тёплый крючок","seed_marta_broken":"бледнее"}}')
    kept = F.judge(_seeds(), _DEEDS, _NAMES, stub)
    assert [s["sid"] for s in kept] == ["seed_dunn_kindebt", "seed_marta_broken"]
    assert kept[0]["why"] == "тёплый крючок"
    assert "Дунн" in stub.seen[1]["content"] and "гроссбух" in stub.seen[1]["content"]


def test_judge_drops_vetoed():
    stub = _Stub('{"rank":["seed_dunn_kindebt"],"veto":["seed_marta_broken"],'
                 '"why":{"seed_dunn_kindebt":"ок"}}')
    kept = F.judge(_seeds(), _DEEDS, _NAMES, stub)
    assert [s["sid"] for s in kept] == ["seed_dunn_kindebt"]


def test_judge_parse_failure_returns_empty():
    kept = F.judge(_seeds(), _DEEDS, _NAMES, _Stub("не json вовсе"))
    assert kept == []


def test_judge_llm_unavailable_propagates():
    class _Boom:
        def call(self, *a, **k):
            raise LLMUnavailable("нет модели")

    with pytest.raises(LLMUnavailable):
        F.judge(_seeds(), _DEEDS, _NAMES, _Boom())


def test_render_evidence_strips_deed_prefix():
    """seeds.py anchors carry deed:-prefix — the judge must still see the fact."""
    seed = {"sid": "s1", "pattern": "kin_debt", "giver_name": "Дунн",
            "cast": {"villain": "npc:ralf"}, "evidence": ["deed:d123"]}
    deeds = {"d123": {"actor": "npc:ralf", "verb": "promise", "data": {"what": "обещал вернуть гроссбух"}}}
    out = F.render_evidence(seed, deeds, {"npc:ralf": "Ральф"})
    assert "обещал вернуть гроссбух" in out and "Ральф" in out
