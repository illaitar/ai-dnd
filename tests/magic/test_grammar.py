"""Магия: грамматика круга (empty/clean/wild) + механический спек эффекта из глифов."""

from aidnd.magic import build_spec, classify, known_ids, load


def test_vocabulary_loaded():
    g = load()
    assert len(g["elements"]) == 6 and len(g["glyphs"]) == 12
    assert {"огонь", "лёд", "свет", "тьма", "яд", "камень"} <= set(g["elements"])
    assert "стрела" in g["glyphs"] and "исцелить" in g["glyphs"]


def test_empty_circle_wont_cast():
    assert classify([])["kind"] == "empty"
    assert classify(["стрела"])["kind"] == "empty"          # форма без сути
    assert classify(["больше", "дальше"])["kind"] == "empty"


def test_clean_damage_circle():
    c = classify(["огонь", "стрела", "дальше"])
    assert c["kind"] == "clean"
    s = build_spec(["огонь", "стрела", "дальше"])
    assert s["damage"]["type"] == "fire" and s["damage"]["dice"] == "1d6"
    assert s["area"]["shape"] == "bolt" and s["range"] == 11        # 6 + 5×1
    assert s["mana_cost"] >= 5


def test_size_and_burst_scale():
    s = build_spec(["лёд", "взрыв", "больше", "больше"])
    assert s["damage"]["type"] == "cold" and s["damage"]["dice"] == "3d6"   # 1 + 2 size
    assert s["area"] == {"shape": "burst", "radius": 3}                     # 1 + 2 size


def test_verbs_bind_heal_reveal():
    assert build_spec(["связать", "камень", "стрела", "дольше"])["status"] == {"kind": "bound", "turns": 2}
    assert build_spec(["исцелить", "больше"])["heal"] == 7                  # 4 + 3
    assert build_spec(["явить", "свет"]).get("reveal") is True


def test_wild_contradictions():
    assert classify(["огонь", "лёд", "стрела"])["kind"] == "wild"           # противостоящие стихии
    assert classify(["свет", "тьма"])["kind"] == "wild"
    assert classify(["исцелить", "огонь"])["kind"] == "wild"                # лечение + губящая стихия
    assert classify(["огонь", "стрела", "взрыв"])["kind"] == "wild"         # две формы


def test_unknown_ids_ignored():
    c = classify(["огонь", "стрела", "ЧУШЬ"])
    assert c["kind"] == "clean" and "ЧУШЬ" not in c["elements"] + c["forms"]


def test_deterministic():
    assert build_spec(["огонь", "взрыв", "больше"]) == build_spec(["огонь", "взрыв", "больше"])
