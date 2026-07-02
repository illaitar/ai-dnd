"""Инскрипция: стабильный хэш круга, детерминированная заглушка имени, ограниченное меню дикой магии."""

from __future__ import annotations

from aidnd.magic import WILD_EFFECTS, StubInscriber, build_spec, circle_hash


def test_hash_order_independent():
    assert circle_hash(["огонь", "стрела"]) == circle_hash(["стрела", "огонь"])
    assert circle_hash(["огонь", "стрела"]) != circle_hash(["лёд", "стрела"])


def test_stub_names_clean_circle():
    comp = ["огонь", "стрела"]
    spec = build_spec(comp)
    named = StubInscriber().name_circle(comp, spec)
    assert named["name"] and isinstance(named["name"], str)
    assert "flavor" in named and "sensory" in named


def test_stub_wild_within_menu():
    w = StubInscriber().wild(["огонь", "лёд"], "стихии рвут круг", in_combat=False)
    assert w["effect"] in WILD_EFFECTS
    assert 1 <= w["magnitude"] <= 3
    assert w["text"]
