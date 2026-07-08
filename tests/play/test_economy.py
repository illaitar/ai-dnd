"""Слой B (экономика, docs/citysim.md §B): сохранение монеты, цепочки, цена-от-дефицита, wealth."""

import os
import tempfile

import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.engine import economy as ec
from aidnd.server.play.engine.session import persist


@pytest.fixture
def world(monkeypatch):
    from aidnd.server.play.engine.world import _play
    from aidnd.worldgen import WorldStore

    monkeypatch.setattr(persist, "_STORE",
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
    for _pid, p in world.items():
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


# ── B2: товарный рынок игрока (docs/citysim.md §B2) ──
def _first_venue_chain():
    """Первая цепочка с живым venue и производителями — площадка для B2-тестов."""
    return next((c for c in ec._chains() if c.get("venue") and c["producers"]), None)


def test_player_buy_drains_stock_raises_price(world):
    ec.economy_step()                                    # накопить запас
    ch = _first_venue_chain()
    assert ch is not None, "нет цепочки с venue"
    bid, key = ch["venue"], ch["key"]
    core._store().purse_add(core._wid(), "pc", 1000)     # у игрока есть деньги
    m0 = ec.money_supply()
    p0, s0 = ec.market_here(bid)[0]["price"], ec.market_here(bid)[0]["stock"]
    r = ec.player_buy(bid, key, min(3, s0))
    assert "error" not in r, r
    now = next(g for g in ec.market_here(bid) if g["key"] == key)
    assert now["stock"] == s0 - r["qty"]                 # запас ушёл игроку
    assert now["price"] >= p0                            # спрос → цена не ниже
    assert now["have"] == r["qty"]                       # в котомке игрока
    assert ec.money_supply() > m0                        # монета игрока влилась в город (инфляция)


def test_player_sell_returns_coin_lowers_price(world):
    ec.economy_step()
    ch = _first_venue_chain()
    bid, key = ch["venue"], ch["key"]
    core._store().purse_add(core._wid(), "pc", 1000)
    ec.player_buy(bid, key, 2)                            # сначала купить (наполнить котомку)
    p_before = next(g for g in ec.market_here(bid) if g["key"] == key)["price"]
    m_before = ec.money_supply()
    r = ec.player_sell(bid, key, 2)
    assert "error" not in r, r
    now = next(g for g in ec.market_here(bid) if g["key"] == key)
    assert now["have"] == 0                               # котомка опустела
    assert now["price"] <= p_before                       # переизбыток → дешевеет
    assert ec.money_supply() <= m_before                  # монета утекла к игроку (дефляция)


def test_buy_rejects_over_stock_and_broke(world):
    ch = _first_venue_chain()
    bid, key = ch["venue"], ch["key"]
    stock = next(g for g in ec.market_here(bid) if g["key"] == key)["stock"]
    assert "error" in ec.player_buy(bid, key, stock + 999)   # больше запаса нельзя
    core._store().purse_add(core._wid(), "pc",
                            -core._store().purse_get(core._wid(), "pc"))  # обнулить кошелёк
    if stock > 0:
        assert "error" in ec.player_buy(bid, key, stock)      # без монет — нельзя
    assert "error" in ec.player_buy(bid, "нет-такой", 1)      # чужой venue/ключ
