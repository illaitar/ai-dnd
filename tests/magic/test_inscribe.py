"""Инскрипция: кламп закона по бюджету рисунка, заглушка, ограниченное меню дикой магии."""

from __future__ import annotations

from aidnd.magic import WILD_EFFECTS, StubInscriber, clamp_law, power_budget


def test_clamp_law_respects_budget():
    comp = [{"id": "огонь", "size": 0.2, "angle": 0, "ring": 0}]   # крошечный огонь: бюджет ~1.5
    wild_claim = {"name": "Солнце Гнева", "power": 99, "range": 99, "duration": 99,
                  "mech": {"dice": "20d12", "dmg_type": "fire",
                           "aoe": {"shape": "burst", "radius": 40}, "heal": 999}}
    law = clamp_law(wild_claim, comp)
    budget = max(1, round(power_budget(comp)))
    assert law["power"] <= budget
    assert int(law["mech"]["damage"]["dice"].split("d")[0]) <= law["power"]
    assert law["mech"]["aoe"]["radius"] <= 1 + law["power"] // 3
    assert law["mech"]["heal"] <= 2 * law["power"]
    assert law["range"] <= 12 and law["duration"] <= 20
    assert law["name"] == "Солнце Гнева"                    # суть свободна — сила в рамках


def test_stub_scribe_and_wild():
    comp = ["свет", "исцелить"]
    law = StubInscriber().scribe_law(comp, {})
    assert law["name"] and law["power"] >= 1 and "mech" in law
    w = StubInscriber().wild(comp, "стихии рвут круг", in_combat=False)
    assert w["effect"] in WILD_EFFECTS and 1 <= w["magnitude"] <= 3 and w["text"]
