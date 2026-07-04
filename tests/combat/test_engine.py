"""Боевой движок: правила, детерминизм, авторезолв, сборка энкаунтеров из данных."""

from aidnd.combat import (
    Encounter,
    bestiary,
    from_monster,
    from_npc,
    from_pc,
    pick_encounter,
    resolve,
)


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


def test_ranged_reaches_far_and_melee_cannot():
    """Лучник бьёт с дистанции; ближнее оружие с той же клетки — «не дотянуться»."""
    arch = from_pc({"str": 10, "dex": 16}, 18, 18, weapon={"name": "длинный лук", "quality": "fine"})
    melee = from_pc({"str": 16, "dex": 10}, 18, 18, weapon={"name": "меч", "quality": "fine"})
    assert arch.range >= 10 and melee.range == 1
    e = Encounter([arch], [_goblin("g0")], seed="r1")
    a, g = e.units["pc"], e.units["g0"]
    a.x, a.y, g.x, g.y = 0, 0, 9, 0                     # 9 клеток между ними
    e.acted = False
    assert e.act_attack(a, "g0") is None                # выстрел долетает
    e.acted = False
    b = Encounter([melee], [_goblin("g1")], seed="r2")
    m, g2 = b.units["pc"], b.units["g1"]
    m.x, m.y, g2.x, g2.y = 0, 0, 9, 0
    assert b.act_attack(m, "g1") == "не дотянуться"      # мечом — никак


def test_ranged_disadvantage_when_adjacent():
    """Дальнобой в упор бьёт с помехой (min из двух d20) — статистически слабее."""
    def hits(seed, adjacent):
        arch = from_pc({"str": 10, "dex": 20}, 18, 18, weapon={"name": "лук", "quality": "fine"})
        e = Encounter([arch], [_goblin("g0")], seed=seed)
        a, g = e.units["pc"], e.units["g0"]
        a.x, a.y = 0, 0
        g.x, g.y = (1, 0) if adjacent else (8, 0)
        e.acted, g.hp = False, 999                       # не убить, только фиксируем попадание
        before = g.hp
        e.act_attack(a, "g0")
        return g.hp < before
    far = sum(hits(f"far{i}", False) for i in range(60))
    near = sum(hits(f"near{i}", True) for i in range(60))
    assert near < far                                    # помеха у стрельбы в упор снижает попадания


def test_dungeon_obstacles_traversable():
    from aidnd.combat import dungeon
    obs = dungeon.obstacles(12, 9, "Swamp", "s1")
    assert 4 <= len(obs) <= 30                              # структура есть, но не сплошная стена
    assert all(y != 4 for _x, y in obs)                    # сквозной коридор чист
    assert all(2 <= x <= 9 for x, _y in obs)               # края спавна свободны
    assert obs == dungeon.obstacles(12, 9, "Swamp", "s1")  # детерминизм


def test_dungeon_waves_and_spawn():
    from aidnd.combat import Encounter, dungeon
    wv = dungeon.waves(1.5, "Forest", "s2", n=2)
    assert 1 <= len(wv) <= 3 and all(wv)
    e = Encounter([_pc()], wv[0], seed="w", waves=wv[1:])
    for u in list(e.units.values()):                       # перебить первую волну
        if u.side == "foes":
            u.alive = False
    assert e.foes_cleared()
    assert e.next_wave() is True                            # накат подмоги
    assert not e.foes_cleared()                             # снова есть живые враги
