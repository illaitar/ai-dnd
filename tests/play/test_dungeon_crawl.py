"""Кейсы обхода данжа: вход/туман, замок-ключ, ловушка с кубиком, лут клада, выход."""

import asyncio
import os
import tempfile

import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.engine.session import persist
from aidnd.server.play.handlers import dungeon as dh


class _Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


@pytest.fixture
def crawl(monkeypatch):
    from aidnd.worldgen import WorldStore

    tmp = tempfile.mkdtemp()
    monkeypatch.setattr(persist, "_STORE", WorldStore(os.path.join(tmp, "live.db")))
    lair = {"id": "lair:t", "name": "Тест-логово", "env": "Caverns", "cr": 0.8,
            "cleared": False}
    r = dh.delve_enter(lair)
    return r, dh._dng()


def _move(room):
    return asyncio.run(dh.dungeon_move(_Req({"room": room})))


def _loot():
    return asyncio.run(dh.dungeon_loot(_Req({})))


def test_enter_fog_and_clickable_svg(crawl):
    r, st = crawl
    assert len(st["seen"]) == 1 and st["room"] == st["d"]["entrance"]
    dg = r["dungeon"]
    assert dg["svg"].startswith("<svg") and 'data-room' in dg["svg"] and ">?<" in dg["svg"]
    assert dg["exits"], "у входа должны быть выходы"


def test_move_validation_and_time(crawl):
    _r, st = crawl
    bad = _move(999)
    assert bad.get("error")
    ex = next(x for x in dh._exits(st) if not x["locked"])
    tgt = st["d"]["rooms"][ex["room"]]
    tgt["content"] = {"kind": "empty", "flavor": {"name": "тишь", "note": "пыль"}}
    gt0 = core._gt()
    ok = _move(ex["room"])
    assert not ok.get("error") and st["room"] == ex["room"]
    assert core._gt() == gt0 + core.PB["dungeon_step_min"]
    assert ex["room"] in st["seen"]


def test_locked_needs_key(crawl):
    _r, st = crawl
    d = st["d"]
    ex = next(x for x in dh._exits(st) if not x["locked"])
    e = d["edges"][ex["eid"]]
    e["kind"], e["lock"] = "locked", "k9"              # запираем дверь у входа
    d["rooms"][ex["room"]]["content"] = {"kind": "empty"}
    refused = _move(ex["room"])
    assert "Заперто" in (refused.get("narr") or [""])[0]
    st["keys"].add("k9")
    ok = _move(ex["room"])
    assert not ok.get("error") and st["room"] == ex["room"]


def test_trap_rolls_and_sprung_once(crawl):
    _r, st = crawl
    ex = next(x for x in dh._exits(st) if not x["locked"])
    st["d"]["rooms"][ex["room"]]["content"] = {
        "kind": "trap",
        "trap": {"name": "яма", "telegraph": "проседшая плита", "effect": "провал",
                 "dmg": "1d4", "save": "dex", "dc": 12},
    }
    r = _move(ex["room"])
    assert r.get("dice") and r["dice"]["dc"] == 12
    assert ex["room"] in st["sprung"]
    _move(st["d"]["entrance"])
    again = _move(ex["room"])                          # разряжена — второй раз не бьёт
    assert not again.get("dice")


def test_loot_treasure_and_key(crawl):
    _r, st = crawl
    rid = st["room"]
    st["d"]["rooms"][rid]["content"] = {
        "kind": "empty",
        "treasure": {"worth": 7, "container": "ларец", "concealment": "под плитой",
                     "guarded": False},
    }
    st["d"]["keys"].append({"id": "k5", "room": rid})
    coins0 = core._store().purse_get(core._wid(), "pc")
    r = _loot()
    assert any("Клад" in n for n in r["narr"])
    assert core._store().purse_get(core._wid(), "pc") == coins0 + 7
    assert "k5" in st["keys"]
    r2 = _loot()
    assert any("перетряс" in n for n in r2["narr"])    # повторный обыск пуст


def test_exit_clears_state(crawl):
    _r, _st = crawl
    r = asyncio.run(dh.dungeon_exit(_Req({})))
    assert dh._dng() is None and "выбираешься" in r["narr"][0]
