"""Слой B (экономика, docs/citysim.md §B): сохранение монеты, цепочки, цена-от-дефицита, wealth."""

import os
import tempfile

import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.engine import economy as ec


@pytest.fixture
def world(monkeypatch):
    from aidnd.server.play.engine.world import _play
    from aidnd.worldgen import WorldStore

    monkeypatch.setattr(core, "_STORE",
                        WorldStore(os.path.join(tempfile.mkdtemp(), "live.db")))
    _city, people, _crof, _cr2b, _loc = _play()
    core._S["gt"] = 8 * 60
    ec.ensure()
    return people


def test_money_conserved_across_days(world):
    m0 = ec.money_supply()
    assert m0 > 0                                        # монета роздана (M>0)
    for d in range(6):                                  # шесть суточных оборотов
        core._S["gt"] = (d + 1) * 1440 + 8 * 60
        ec.economy_step()
    assert ec.money_supply() == m0                       # СОХРАНЕНИЕ: только перемещение


def test_chains_instantiated_named(world):
    ch = ec.chains_view()
    assert len(ch) >= 5                                  # именованные цепочки собрались
    assert all(c["producers"] or c["broken"] for c in ch)
    assert any(c["good"] for c in ch)


def test_broken_chain_price_rises(world):
    core._S["gt"] = 1440 + 8 * 60
    ec.economy_step()
    ch = next(c for c in ec._chains() if c["producers"])
    p0 = ch["price"]
    for pid in ch["producers"]:                          # выбить всех производителей цепочки
        core._store().flag_set(core._wid(), f"dead|{pid}")
    for d in range(4):
        core._S["gt"] = (d + 2) * 1440 + 8 * 60
        ec.economy_step()
    ch2 = next(c for c in ec._chains() if c["key"] == ch["key"])
    assert ch2["price"] > p0                              # производить некому → дорожает


def test_wealth_need_from_purse(world):
    pid = next(iter(world))
    core._store().purse_add(core._wid(), pid, -core._store().purse_get(core._wid(), pid))  # 0
    ec._wealth_from_purse()
    assert world[pid].state.needs["wealth"] > 0.8        # нищий — сильная нужда заработать
    core._store().purse_add(core._wid(), pid, 100)
    ec._wealth_from_purse()
    assert world[pid].state.needs["wealth"] < 0.3        # богач — почти нет
