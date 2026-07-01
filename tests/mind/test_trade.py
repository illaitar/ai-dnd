"""Сделка ВЫПАДАЕТ из субъективной ценности (worth) — без хардкода sell/buy. Деньги — предмет,
у агентов инвентарь, обмен = двойной give в ценностном коридоре. Проверяем: торговец ПРОВОДИТ
продажу голодному; не продаёт нищему (нечем платить); тот же worth даёт бартер (плата — товар).
"""

from __future__ import annotations

from aidnd.mind import TRAITS, Body, Item, NpcConfig, NpcState
from aidnd.mind.trade import money_of, propose_sale, settle_sale, worth
from aidnd.mind.world import World


def _npc(nid, world, traits=None, needs=None, carrying=None):
    cfg = NpcConfig(id=nid, name=nid, traits={**dict.fromkeys(TRAITS, 0.5), **(traits or {})})
    st = NpcState.from_config(cfg)
    for k, v in (needs or {}).items():
        st.needs[k] = v
    world.add(Body(id=nid, place="лавка", carrying=list(carrying or [])))
    return st


def _bread(n):
    return [Item("каравай", .3, satisfies="hunger") for _ in range(n)]


# ── торговец ПРОВОДИТ продажу: голодный покупатель с монетами уходит с хлебом ──
def test_merchant_completes_sale():
    w = World()
    seller = _npc("Торговец", w, traits={"greed": .85}, needs={"wealth": .5}, carrying=_bread(8))
    buyer = _npc("Покупатель", w, traits={"greed": .5}, needs={"hunger": .8, "wealth": .3},
                 carrying=[Item("монеты", 1.0, kind="coin", amount=12.0)])

    deal = propose_sale(seller, buyer, w)
    assert deal is not None                                # выгода от обмена есть → сделка предложена
    good, price, gain = deal
    assert good.name == "каравай" and price > 0

    before = money_of(buyer, w)
    res = settle_sale(deal, seller, buyer, w)
    # товар переехал, монеты переехали — сделка ПРОВЕДЕНА
    assert any(i.name == "каравай" for i in w.bodies["Покупатель"].carrying)
    assert money_of(buyer, w) < before
    assert money_of(seller, w) == round(price, 3)
    assert sum(1 for i in w.bodies["Торговец"].carrying if i.name == "каравай") == 7
    assert res["price"] == price


# ── нищему не продаст: нет монет → цена не покрывает минимум продавца ──
def test_no_sale_when_broke():
    w = World()
    seller = _npc("Торговец", w, traits={"greed": .85}, needs={"wealth": .5}, carrying=_bread(8))
    broke = _npc("Нищий", w, needs={"hunger": .9}, carrying=[])   # ни монеты
    assert propose_sale(seller, broke, w) is None


# ── субъективность: 10-й каравай торговцу ДЁШЕВ, голодному ДОРОГ (из этого и растёт сделка) ──
def test_worth_is_subjective():
    w = World()
    seller = _npc("Торговец", w, needs={"hunger": 0.0}, carrying=_bread(10))   # сыт
    buyer = _npc("Едок", w, needs={"hunger": .9}, carrying=[])
    loaf = w.bodies["Торговец"].carrying[0]
    assert worth(loaf, seller, w) < 0.1                    # запас обесценил
    spare = Item("каравай", .3, satisfies="hunger")
    w.bodies["Едок"].carrying.append(spare)
    assert worth(spare, buyer, w) > worth(loaf, seller, w) * 3   # голодному куда ценнее


# ── тот же worth даёт БАРТЕР: у каждого избыток одного и нужда в другом ──
def test_barter_emerges_from_worth():
    w = World()
    # у каждого ИЗБЫТОК своего товара (дёшев) и НУЖДА (оба голодны) в чужом
    a = _npc("Пекарь", w, needs={"hunger": .8},
             carrying=[Item("каравай", .3, satisfies="hunger") for _ in range(5)])
    b = _npc("Мясник", w, needs={"hunger": .8},
             carrying=[Item("окорок", .3, satisfies="hunger") for _ in range(5)])
    loaf = w.bodies["Пекарь"].carrying[0]
    ham = w.bodies["Мясник"].carrying[0]
    # каждый ценит ЧУЖОЙ товар выше своего (у него избыток) → выгодный обмен существует без денег
    assert worth(ham, a, w) > worth(ham, b, w)             # окорок пекарю ценнее (у мясника запас)
    assert worth(loaf, b, w) > worth(loaf, a, w)           # каравай мяснику ценнее (у пекаря запас)
