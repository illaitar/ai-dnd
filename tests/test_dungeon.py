"""Генератор подземелий: детерминизм и структурные инварианты (док 05/07)."""

from aidnd.gen.dungeon import FLOOR, DungeonBrief, generate

BRIEF = DungeonBrief(site_key="cragmaw_hideout", theme="cave", tier=2, floors=2,
                     faction="faction:cragmaw", boss="npc:klarg")


def _reachable(d, start, allow):
    seen, stack = {start}, [start]
    while stack:
        cur = stack.pop()
        for nb, kind in d.neighbors(cur):
            if kind in allow and nb not in seen:
                seen.add(nb); stack.append(nb)
    return seen


def test_deterministic_by_seed():
    a = generate(BRIEF, 777)
    b = generate(BRIEF, 777)
    assert [f.grid for f in a.floors] == [f.grid for f in b.floors]
    assert generate(BRIEF, 778).floors[0].grid != a.floors[0].grid


def test_has_entrance_and_boss_reachable():
    d = generate(BRIEF, 777)
    assert d.rooms[d.entrance].role == "entrance"
    assert d.rooms[d.boss_room].role == "boss"
    # босс достижим из входа по проходимым рёбрам (любым, кроме секретного)
    reach = _reachable(d, d.entrance, {"door", "locked", "stairs"})
    assert d.boss_room in reach


def test_lock_has_key():
    d = generate(BRIEF, 777)
    locked = [(a, b) for a, b, k in d.edges if k == "locked"]
    assert locked, "должна быть хотя бы одна запертая дверь"
    keys = [c for r in d.rooms.values() for c in r.contents if c["kind"] == "key"]
    assert keys, "к запертой двери должен существовать ключ"


def test_secret_room_only_behind_secret_door():
    d = generate(BRIEF, 777)
    secrets = [r for r in d.rooms.values() if r.secret]
    assert len(secrets) >= 1
    for s in secrets:
        kinds = {k for _, k in d.neighbors(s.rid)}
        assert kinds == {"secret"}, "в скрытую комнату ведёт только секретная дверь"
        # без раскрытия секрета она недостижима из входа
        assert s.rid not in _reachable(d, d.entrance, {"door", "locked", "stairs"})


def test_room_shapes_vary():
    d = generate(BRIEF, 777)
    shapes = {r.shape for r in d.rooms.values()}
    assert shapes - {"rect"}, "должны быть не только прямоугольные комнаты"


def test_rooms_dont_overlap_and_have_floor():
    d = generate(BRIEF, 777)
    for f in d.floors:
        seen: set = set()
        for rid in f.rooms:
            r = d.rooms[rid]
            assert r.cells, f"комната {rid} без пола"
            assert r.center in r.cells
            assert f.grid[r.center[1]][r.center[0]] in (FLOOR, "E", "<", ">")
            assert not (r.cells & seen), f"комнаты пересекаются: {rid}"
            seen |= r.cells
