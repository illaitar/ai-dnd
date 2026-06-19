"""Контракты общения с NPC по слайдерам отношения (main §5.4).

Офлайн (use_model=False) — детерминированный фоллбэк-путь: те же инварианты, что
обязаны держаться и на модели. На живой модели тот же харнесс захватывает её
выходы для судейства (python -m aidnd.eval conversations).
"""

import pytest
from aidnd.bootstrap import new_session
from aidnd.cognition import gate_open
from aidnd.eval.conversations import load_cases, run_conversation
from aidnd.world.components import Relationships, RelEdge

CASES = load_cases()


def _sess():
    return new_session(seed=1337, roster_size=4, use_model=False)


@pytest.mark.parametrize("sc", CASES, ids=[s.key for s in CASES])
def test_conversation_contracts(sc):
    t = run_conversation(_sess(), sc)
    failed = [str(c) for c in t.checks if c.hard and not c.passed]
    assert not failed, f"{sc.key}: " + "; ".join(failed)


def test_secret_gate_low_vs_high_trust():
    """Один NPC: при низком trust секрет закрыт, при высоком — открыт (слайдер рулит)."""
    w = _sess().world
    npc = "npc:halia_thornton"
    rels = w.ecs.get(npc, Relationships) or Relationships()
    w.ecs.add(npc, rels)
    rels.edges["pc:hero"] = RelEdge(trust=0.0)
    assert not gate_open(w, npc, "pc:hero", "share_secret")
    rels.edges["pc:hero"] = RelEdge(trust=0.7)
    assert gate_open(w, npc, "pc:hero", "share_secret")


def test_fear_gate_opens_flight():
    w = _sess().world
    npc = "npc:toblen_stonehill"
    rels = w.ecs.get(npc, Relationships) or Relationships()
    w.ecs.add(npc, rels)
    rels.edges["pc:hero"] = RelEdge(fear=0.1)
    assert not gate_open(w, npc, "pc:hero", "flee")
    rels.edges["pc:hero"] = RelEdge(fear=0.7)
    assert gate_open(w, npc, "pc:hero", "flee")


def test_fallback_policy_reacts_to_sliders():
    """Фоллбэк-политика меняет действие в зависимости от слайдеров."""
    s = _sess()
    npc = "npc:halia_thornton"
    rels = s.world.ecs.get(npc, Relationships) or Relationships()
    s.world.ecs.add(npc, rels)
    # доверенный → делится
    rels.edges["pc:hero"] = RelEdge(trust=0.7)
    ctx = s.cognition.retrieve(npc, "секрет", "pc:hero")
    assert s.cognition._fallback_policy(npc, "persuade", "friendly", ctx, "pc:hero")["action"] == "share_info"
    # недоверяемый → молчит
    rels.edges["pc:hero"] = RelEdge(trust=0.0)
    ctx = s.cognition.retrieve(npc, "секрет", "pc:hero")
    assert s.cognition._fallback_policy(npc, "persuade", "neutral", ctx, "pc:hero")["action"] == "withhold"
    # испуган + угроза → бежит/зовёт стражу/сдаётся
    rels.edges["pc:hero"] = RelEdge(fear=0.7)
    ctx = s.cognition.retrieve(npc, "угроза", "pc:hero")
    assert s.cognition._fallback_policy(npc, "intimidate", "hostile", ctx, "pc:hero")["action"] in (
        "flee", "yield", "call_guards")
