"""Обмен как АБСТРАКЦИЯ (не хардкод sell/buy). Деньги — такой же предмет (kind='coin', делимая сумма
amount). Ценность СУБЪЕКТИВНА: worth(предмет, агент) зависит от нужд/запаса/натуры. Сделка = обоюдно
выгодный обмен через тот же примитив give: продавец отдаёт товар (у него дёшев — запас), покупатель
отдаёт монеты (товар ему ценен — нужда). Тот же worth+give даёт куплю-продажу, бартер (плата — другой
товар) и взятку (плата — за расположение). Игрок — такой же агент: его «согласен» приходит от игрока.

Никакого «продать» в коде нет — сделка ВЫПАДАЕТ из ценностного коридора между двумя worth.
"""

from __future__ import annotations

from .world import Item


def money_demand(st) -> float:
    """Сколько одна монета стоит ДЛЯ агента (спрос на деньги от нужды/натуры)."""
    t = st.config.traits
    return 0.4 + 0.8 * st.needs.get("wealth", 0.0) + 0.3 * t.get("greed", 0.5) + 0.2 * t.get("ambition", 0.5)


def _inv(st, world) -> list:
    return world.bodies[st.config.id].carrying


def money_of(st, world) -> float:
    return sum(i.amount for i in _inv(st, world) if i.kind == "coin")


def _purse(st, world) -> Item:
    body = world.bodies[st.config.id]
    for i in body.carrying:
        if i.kind == "coin":
            return i
    p = Item("монеты", value=1.0, kind="coin", amount=0.0)
    body.carrying.append(p)
    return p


def worth(item: Item, st, world) -> float:
    """Субъективная ценность ОБЛАДАНИЯ предметом для агента (не для добычи — для жизни)."""
    if item.kind == "coin":
        return item.amount * money_demand(st)
    have = sum(i.amount for i in _inv(st, world) if i.name == item.name and i is not item)
    base = item.value / (1.0 + 0.4 * have)                 # запас обесценивает (у торговца дёшево)
    if item.satisfies and item.satisfies in st.needs:
        base += st.needs[item.satisfies] * 0.7             # нужда поднимает ценность
    return base


def propose_sale(seller_st, buyer_st, world):
    """Найти обоюдно выгодную продажу товара за монеты. Возвращает (item, price, buyer_gain) или None.
    Цена садится в коридор [минимум продавца … максимум покупателя] — торг сходится к середине."""
    seller = world.bodies[seller_st.config.id]
    cw_s, cw_b = money_demand(seller_st), money_demand(buyer_st)
    purse = money_of(buyer_st, world)
    best = None
    for good in list(seller.carrying):
        if good.kind == "coin":
            continue
        sw = worth(good, seller_st, world)                 # почём продавцу расстаться
        bw = worth(good, buyer_st, world)                  # сколько стоит покупателю
        lo, hi = sw / cw_s, bw / cw_b                       # ценовой коридор В МОНЕТАХ
        if bw <= sw or lo > hi:
            continue                                       # нет выгоды от обмена
        price = min((lo + hi) / 2.0, purse)                # середина, но не больше кошелька
        if price < lo:                                     # покупателю не хватает → продавцу невыгодно
            continue
        gain = bw - price * cw_b                           # выгода покупателя от сделки
        if gain > 0 and (best is None or gain > best[2]):
            best = (good, round(price, 3), round(gain, 3))
    return best


def settle_sale(deal, seller_st, buyer_st, world) -> dict:
    """Провести сделку тем же give: товар продавец→покупатель, монеты покупатель→продавец."""
    good, price, _ = deal
    seller, buyer = world.bodies[seller_st.config.id], world.bodies[buyer_st.config.id]
    seller.carrying.remove(good)
    buyer.carrying.append(good)
    _purse(buyer_st, world).amount -= price
    _purse(seller_st, world).amount += price
    return {"sold": good.name, "price": price,
            "buyer_money": round(money_of(buyer_st, world), 3),
            "seller_money": round(money_of(seller_st, world), 3)}
