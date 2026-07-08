"""Trade as an ABSTRACTION (not hardcoded sell/buy). Money is just an item (kind='coin', divisible
amount). Value is SUBJECTIVE: worth(item, agent) depends on needs/inventory/nature. A deal = mutually
beneficial exchange via the same primitive give: seller gives goods (cheap for him — inventory), buyer
gives coins (valuable to him — need). The same worth+give yields commerce, barter (payment is another
good) and bribery (payment for favor). The player is just another agent: their "consent" comes from the player.

No "sell" in the code — a deal EMERGES from the value corridor between two worth values.

Key functions
-------------
money_demand(st) -> float : Agent's demand for money based on wealth/greed/ambition traits.
money_of(st, world) -> float : Total coins an agent currently carries.
worth(item, st, world) -> float : Subjective value of owning an item (scales by possession & need).
propose_sale(seller_st, buyer_st, world) -> tuple|None : Find mutually beneficial trade within price corridor.
settle_sale(deal, seller_st, buyer_st, world) -> dict : Execute trade (transfer item & coins).
"""

from __future__ import annotations

from .world import Item


def money_demand(st) -> float:
    """How much one coin is worth FOR an agent (demand for money from need/nature)."""
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
    """Subjective value of POSSESSING an item for an agent (not for looting — for living)."""
    if item.kind == "coin":
        return item.amount * money_demand(st)
    have = sum(i.amount for i in _inv(st, world) if i.name == item.name and i is not item)
    base = item.value / (1.0 + 0.4 * have)                 # possession devalues (cheap for a merchant)
    if item.satisfies and item.satisfies in st.needs:
        base += st.needs[item.satisfies] * 0.7             # need raises value
    return base


def propose_sale(seller_st, buyer_st, world):
    """Find a mutually profitable sale of goods for coins. Returns (item, price, buyer_gain) or None.
    Price fits in the corridor [seller's minimum … buyer's maximum] — negotiation converges to the middle."""
    seller = world.bodies[seller_st.config.id]
    cw_s, cw_b = money_demand(seller_st), money_demand(buyer_st)
    purse = money_of(buyer_st, world)
    best = None
    for good in list(seller.carrying):
        if good.kind == "coin":
            continue
        sw = worth(good, seller_st, world)                 # what the seller asks to part with
        bw = worth(good, buyer_st, world)                  # how much it's worth to the buyer
        lo, hi = sw / cw_s, bw / cw_b                       # price corridor IN COINS
        if bw <= sw or lo > hi:
            continue                                       # no benefit from exchange
        price = min((lo + hi) / 2.0, purse)                # midpoint, but not more than purse
        if price < lo:                                     # buyer doesn't have enough → not profitable for seller
            continue
        gain = bw - price * cw_b                           # buyer's gain from the deal
        if gain > 0 and (best is None or gain > best[2]):
            best = (good, round(price, 3), round(gain, 3))
    return best


def settle_sale(deal, seller_st, buyer_st, world) -> dict:
    """Execute a deal via the same give: goods from seller→buyer, coins from buyer→seller."""
    good, price, _ = deal
    seller, buyer = world.bodies[seller_st.config.id], world.bodies[buyer_st.config.id]
    seller.carrying.remove(good)
    buyer.carrying.append(good)
    _purse(buyer_st, world).amount -= price
    _purse(seller_st, world).amount += price
    return {"sold": good.name, "price": price,
            "buyer_money": round(money_of(buyer_st, world), 3),
            "seller_money": round(money_of(seller_st, world), 3)}
