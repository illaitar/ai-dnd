"""Базовые знания профессий/фракций: наследование и гейтинг по доверию (док 02 §4)."""

from aidnd.content import build_world
from aidnd.content.knowledge import (
    PROFESSION_KNOWLEDGE,
    disclosable,
    inherit_knowledge,
)
from aidnd.world.components import Persona


def test_named_npc_inherits_profession_and_faction_knowledge():
    w = build_world(seed=1337, roster_size=2)
    halia = w.ecs.get("npc:halia_thornton", Persona)   # merchant + Zhentarim
    topics = {k["topic"] for k in halia.knowledge}
    assert "lionshield" in topics                      # из профессии merchant
    assert "zhentarim_secret" in topics                # из фракции Zhentarim


def test_generated_npc_inherits_profession_knowledge():
    w = build_world(seed=1337, roster_size=12)
    checked = [w.ecs.get(n, Persona) for n in w.npcs()]
    pros = [p for p in checked if p and p.profession in PROFESSION_KNOWLEDGE]
    assert pros, "в ростере нет NPC со знакомой профессией"
    assert all(p.knowledge for p in pros), "генерируемый NPC без базовых знаний профессии"


def test_disclosure_gated_by_trust():
    w = build_world(seed=1337, roster_size=2)
    halia = w.ecs.get("npc:halia_thornton", Persona)
    low = {k["fact"] for k in disclosable(halia, trust=0.0)}
    high = {k["fact"] for k in disclosable(halia, trust=0.8)}
    secret = next(k["fact"] for k in halia.knowledge if k["topic"] == "zhentarim_secret")
    assert secret not in low        # тайна закрыта при низком доверии
    assert secret in high           # и открыта при высоком
    assert low <= high              # высокий trust раскрывает надмножество


def test_inherit_no_duplicates():
    p = Persona(name="Тест", archetype="guard", profession="guard")
    inherit_knowledge(p, "guard", None)
    n1 = len(p.knowledge)
    inherit_knowledge(p, "guard", None)   # повторно — без дублей
    assert len(p.knowledge) == n1


def test_topic_filtered_disclosure():
    w = build_world(seed=1337, roster_size=2)
    harbin = w.ecs.get("npc:harbin_wester", Persona)
    facts = disclosable(harbin, trust=0.5, topic="wyvern_tor")
    assert facts and all(k["topic"] in ("wyvern_tor", "") for k in facts)
