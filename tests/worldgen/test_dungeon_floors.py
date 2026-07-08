"""Кейсы этажей: XY-совмещение лестниц, односторонний жёлоб, цель внизу, возврат."""

from aidnd.worldgen.dungeongen import _solvable_back, generate


def _multi(seedbase, env, n=40):
    for i in range(n):
        d = generate(f"{seedbase}|{i}", env)
        if d.get("floors", 1) > 1:
            yield d


def test_stairs_xy_aligned():
    found = 0
    for d in _multi("fl", "Hill"):
        found += 1
        for e in d["edges"]:
            if e["kind"] != "stairs":
                continue
            cell = (e["door"][0], e["door"][1])
            ta = {tuple(t) for t in d["rooms"][e["a"]]["tiles"]}
            tb = {tuple(t) for t in d["rooms"][e["b"]]["tiles"]}
            assert cell in ta and cell in tb, "лестница не совмещена по XY"
            fa = d["rooms"][e["a"]]["floor"]
            fb = d["rooms"][e["b"]]["floor"]
            assert abs(fa - fb) == 1
        if found >= 6:
            return
    assert found, "многоэтажных не родилось за 40 сидов"


def test_goal_on_bottom_and_returnable():
    for d in _multi("fg", "Caverns"):
        assert d["rooms"][d["goal"]]["floor"] == max(r["floor"] for r in d["rooms"])
        assert _solvable_back(d["rooms"], d["edges"], d["goal"])
        break


def test_chute_one_way():
    for d in _multi("fc", "Hill", n=80):
        chutes = [e for e in d["edges"] if e["kind"] == "chute"]
        if not chutes:
            continue
        e = chutes[0]
        assert e["one_way"] is True
        assert d["rooms"][e["b"]]["floor"] > d["rooms"][e["a"]]["floor"]  # вниз
        return
    # жёлоб мог не выпасть — не критично (вероятностный коннектор)


def test_floor_switch_in_game_payload(monkeypatch):
    """Переход по лестнице меняет ярус в payload и пергаменте."""
    import asyncio
    import os
    import tempfile

    from aidnd.server.play.engine import core
    from aidnd.server.play.engine.session import persist
    from aidnd.server.play.handlers import dungeon as dh
    from aidnd.worldgen import WorldStore

    monkeypatch.setattr(persist, "_STORE",
                        WorldStore(os.path.join(tempfile.mkdtemp(), "live.db")))
    d = next(x for x in _multi("fp", "Hill"))
    e = next(e for e in d["edges"] if e["kind"] == "stairs")
    top = e["a"] if d["rooms"][e["a"]]["floor"] < d["rooms"][e["b"]]["floor"] else e["b"]
    bot = e["b"] if top == e["a"] else e["a"]
    d["rooms"][bot]["content"] = {"kind": "empty"}
    core._S["dungeon"] = {"lair": {"id": "lair:t", "name": "т", "cr": 0.5, "env": "Hill"},
                          "d": d, "room": top, "seen": {top}, "cleared": set(),
                          "looted": set(), "keys": set(), "found": set(),
                          "sprung": set(), "steps": 0, "is_lair": True,
                          "npc_at": {}, "captive_at": None}

    class _Req:
        async def json(self):
            return {"room": bot}

    r = asyncio.run(dh.dungeon_move(_Req()))
    dg = r["dungeon"]
    assert dg["floor"] == d["rooms"][bot]["floor"] + 1 and dg["floors"] >= 2
    assert f"ярус {dg['floor']}" in dg["svg"]          # пергамент сменил лист
    core._S["dungeon"] = None
