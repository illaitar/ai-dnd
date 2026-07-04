"""Библия сюжета: стаб валиден, валидатор ловит нарушения балки «иерархия ≠ важность», кастинг."""

from __future__ import annotations

from types import SimpleNamespace

from aidnd.plot import StubArchitect, match_cast, validate_bible


def _bible():
    return StubArchitect().build("исчезают люди", "Костяной Мост")


def test_stub_bible_valid():
    b = _bible()
    assert validate_bible(b) == []
    assert len(b["каст"]) >= 30
    assert len({a["иерархия"]["ранг"] for a in b["каст"] if a.get("иерархия")}) >= 4


def test_validator_catches_axis_gap():
    b = _bible()
    for a in b["каст"]:                                    # ломаем балку: правда больше не внизу
        if a.get("иерархия", {}).get("ранг", 0) >= 3 and (a.get("важность") or 0) >= 8:
            a["важность"] = 5
            a["чехов"] = a.get("чехов")
    errs = validate_bible(b)
    assert any("правда не внизу" in e for e in errs)


def test_validator_catches_missing_chekhov():
    b = _bible()
    imp = next(a for a in b["каст"] if (a.get("важность") or 0) >= 7)
    imp["чехов"] = None
    assert any("без чехова" in e for e in validate_bible(b))


def test_casting_matches_people():
    b = _bible()
    people = {f"pool:{i:04d}": SimpleNamespace(role=r) for i, r in enumerate(
        ["знахарка", "жрец", "стражник", "лавочник", "трактирщик", "маг", "писец",
         "кузнец", "головорез", "бродяга", "мельник", "оружейник"] + ["горожанин"] * 25)}
    res = match_cast(b["каст"], people)
    matched = [a for a in b["каст"] if a["актёр"] and a["актёр"] != "NEW"]
    assert len(matched) >= int(0.8 * len(b["каст"]))       # решение С3: ~80% на существующих
    boss = next(a for a in b["каст"] if a["роль"] == "антагонист-в-тени")
    assert people[boss["актёр"]].role in ("знахарка", "жрец", "маг", "писец")
    pids = [a["актёр"] for a in matched]
    assert len(pids) == len(set(pids))                     # один NPC — один актёр
    assert set(res) == {a["id"] for a in b["каст"]}
