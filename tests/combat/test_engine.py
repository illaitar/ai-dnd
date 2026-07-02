"""Боевой движок: правила, детерминизм, авторезолв, сборка энкаунтеров из данных."""

from aidnd.combat import (Encounter, bestiary, from_monster, from_npc, from_pc,
                          pick_encounter, resolve)


def _pc(hp=18):
    return from_pc({"str": 14, "dex": 12}, hp, hp, weapon={"quality": "fine"})


def _goblin(cid="g0"):
    row = next(m for m in bestiary() if m["id"] == "srd:goblin")
    return from_monster(row, cid)


def test_bestiary_loaded():
    b = bestiary()
    assert len(b) >= 300
    assert all(m.get("name_ru") for m in b[:50])


def test_combatant_from_monster():
    g = _goblin()
    assert g.ac == 15 and g.hp == 7 and g.kind == "monster"
    assert g.dmg_dice == "1d6" and g.to_hit >= 2


def test_encounter_deterministic():
    a = Encounter([_pc()], [_goblin()], seed="x")
    b = Encounter([_pc()], [_goblin()], seed="x")
    assert a.order == b.order
    assert sorted(a.obstacles) == sorted(b.obstacles)


def test_attack_kills_and_status():
    pc = _pc()
    g = _goblin()
    enc = Encounter([pc], [g], seed="kill")
    g.x, g.y = pc.x + 1, pc.y                              # поставить рядом
    g.hp = 1
    err = enc.act_attack(pc, g.id)
    assert err is None
    # либо промах (жив), либо смерть
    assert g.alive or g.hp == 1
    g.hp = 0
    g.alive = False
    assert enc.status() == "won"


def test_move_budget():
    pc = _pc()
    enc = Encounter([pc], [_goblin()], seed="mv")
    err = enc.act_move(pc, min(enc.w - 1, pc.x + pc.speed + 3), pc.y)
    assert err is not None                                  # дальше скорости — нельзя


def test_autoresolve_party_beats_weak():
    party = [_pc(), from_npc("n1", "боец", {"abilities": {"str": 14, "dex": 12}}, hp=12)]
    foes = [_goblin("g1")]
    r = resolve(party, foes, seed="auto1")
    assert r["status"] in ("won", "draw")


def test_autoresolve_overwhelmed():
    party = [from_npc("n1", "хилый", {"abilities": {"str": 8, "dex": 8}}, hp=4)]
    ogre = next(m for m in bestiary() if m["cr"] >= 2 and m.get("attack"))
    foes = [from_monster(ogre, f"o{i}") for i in range(3)]
    r = resolve(party, foes, seed="auto2")
    assert r["status"] in ("lost", "draw")


def test_pick_encounter_env_and_budget():
    units = pick_encounter(1.0, "Forest", seed="e1")
    assert units
    assert sum(u.cr for u in units) <= 1.0 + 0.5
    units2 = pick_encounter(1.0, "Forest", seed="e1")
    assert [u.ref for u in units] == [u.ref for u in units2]   # детерминизм
