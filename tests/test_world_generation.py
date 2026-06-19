"""Мир, KG-инварианты, генерация (main §3, док 01-02, §12.4)."""

from aidnd.content import build_world
from aidnd.gen import RARITY_GATE, check_world_invariants, party_tier


def test_kg_queries(world):
    assert world.kg.works_at("npc:linene_graywind") == "building:lionshield_coster"
    assert world.kg.lives_in("npc:toblen_stonehill") == "building:stonehill_inn"
    # обратный обход: кто живёт в трактире
    residents = world.kg.subjects_of("lives_in", "building:stonehill_inn")
    assert "npc:toblen_stonehill" in residents


def test_world_invariants_hold(world):
    # каждый профессиональный NPC имеет works_at и lives_in; лавки имеют владельца
    violations = check_world_invariants(world)
    assert violations == [], [v.detail for v in violations]


def test_pregen_deterministic_by_seed():
    w1 = build_world(seed=2024, roster_size=10)
    w2 = build_world(seed=2024, roster_size=10)
    assert w1.state_hash() == w2.state_hash()
    # разный сид → другой мир
    w3 = build_world(seed=999, roster_size=10)
    assert w1.state_hash() != w3.state_hash()


def test_names_unique(world):
    from aidnd.world.components import Persona
    names = [world.ecs.get(n, Persona).name for n in world.npcs()]
    assert len(names) == len(set(names)), "имена NPC должны быть уникальны"


def test_rarity_gate_tier1_caps_at_rare():
    gate = RARITY_GATE[party_tier(3)]
    assert gate["very_rare"] == 0.0 and gate["legendary"] == 0.0
    assert gate["rare"] > 0


def test_fixed_loot_placed(world):
    # Staff of Defense у Glasstaff (док 03 §3)
    assert world.kg.has("it:staff_of_defense", "owned_by", "npc:iarno_glasstaff")
    # ящик Lionshield несёт провенанс владельца (квестовый крючок)
    assert world.kg.has("it:lionshield_crate", "was_owned_by", "npc:linene_graywind")
