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
    core._S["city"] = None                              # форс пересборки мира в СВЕЖИЙ store
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


def test_aspirant_buys_out_venue(world):
    ec.ensure()
    # найти venue с ролью и его работников; убить всех → вакансия
    from aidnd.server.play.engine.core import _S, _binfo, _role_for_building
    from aidnd.server.play.engine.economy import _VENUE_PRICE
    bid = next((b for b in (_S.get("keynode") or {})
                if any(w in _binfo(b)["kind"] and c > 0 for w, c in _VENUE_PRICE.items())), None)
    assert bid is not None, "в городе нет продаваемого venue"
    role = _role_for_building(bid)
    workers = [pid for pid, p in world.items() if p.work == bid]
    for pid in workers:
        core._store().flag_set(core._wid(), f"dead|{pid}")  # вакансия
    # детерминированно: ТОЛЬКО наш аспирант годен (прочих обесточиваем/лишаем ремесла)
    for pid, p in world.items():
        if p.role == "подёнщик":
            p.former_role = None
    asp = next(pid for pid, p in world.items() if p.work != bid)
    world[asp].role = "подёнщик"
    world[asp].former_role = role
    core._store().purse_add(core._wid(), asp,
                            300 - core._store().purse_get(core._wid(), asp))
    news = ec.venue_buyouts()
    # ИСХОД (не конкретный pid — выкупить мог любой подходящий аспирант): venue обрёл живого
    # владельца нужной роли, есть новость и deed acquire
    dead = {k.split("|", 1)[1] for k in core._store().flags_prefix(core._wid(), "dead|")}
    buyer = next((pid for pid, p in world.items()
                  if p.work == bid and p.role == role and pid not in dead), None)
    assert buyer is not None, "venue не выкуплен — ремесло не восстановлено"
    assert any("выкупил" in n for n in news)
    assert core._store().deeds(core._wid(), verb="acquire")
