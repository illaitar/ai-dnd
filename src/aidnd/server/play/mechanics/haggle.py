"""Emergent NPC↔NPC trade — value corridor + multi-tick haggle FSM + real store settlement.

Ported from the dormant `mind/trade.py`; runs in the play layer against the store (live.db purses +
inventory). The math here OWNS the numbers (corridor, concession, settle price) — the scene digest only
voices them, so no price is ever LLM-authored. Pure functions (no store) are unit-testable; `settle`
touches the store. See docs/superpowers/specs/2026-07-12-npc-trade-haggle-design.md.
"""

from __future__ import annotations


def money_demand(needs: dict, traits: dict) -> float:
    """How much one coin is worth to an agent (demand for money from need/nature). Ported trade.py:23."""
    return (0.4 + 0.8 * needs.get("wealth", 0.0)
            + 0.3 * traits.get("greed", 0.5) + 0.2 * traits.get("ambition", 0.5))


def deal_corridor(good_worth, seller_needs, seller_traits, buyer_needs, buyer_traits, buyer_wants):
    """Coin corridor (lo=seller-minimum, hi=buyer-maximum). None if no profitable price (hi ≤ lo).
    `buyer_wants` ∈ [0,1] — how much the buyer's agenda/need targets THIS good (raises what he'll pay)."""
    md_s = money_demand(seller_needs, seller_traits)
    md_b = money_demand(buyer_needs, buyer_traits)
    sw = float(good_worth)                                          # seller keeps a surplus good → base
    bw = float(good_worth) * (1.0 + 0.5 * max(0.0, min(1.0, buyer_wants)))   # a wanting buyer pays more
    lo, hi = sw / md_s, bw / md_b
    if hi <= lo:
        return None
    return (round(lo, 2), round(hi, 2))


def concession(needs: dict, traits: dict, side: str, s_base: float, b_base: float) -> float:
    """Per-round concession fraction toward the midpoint, from traits. A greedy seller concedes slower;
    a needy buyer concedes faster. Clamped so a deal can always eventually close or time out."""
    if side == "seller":
        return max(0.1, min(0.8, s_base - 0.5 * traits.get("greed", 0.5) + 0.3 * needs.get("wealth", 0.0)))
    return max(0.1, min(0.9, b_base + 0.5 * needs.get("wealth", 0.0) + 0.2 * traits.get("kindness", 0.0)))


def haggle_tick(deal: dict, s_conc: float, b_conc: float, eps: float):
    """One negotiation round on a live deal (mutates ask/bid/patience/round in place). Returns
    (status, price): 'settle'+int / 'walk'+None / 'haggle'+None. The caller voices ask/bid FIRST,
    then calls this: so the offers spoken each round are the pre-concession values."""
    gap = deal["ask"] - deal["bid"]
    if gap <= eps:                                                 # offers met → strike a deal at the mean
        return "settle", int(round((deal["ask"] + deal["bid"]) / 2.0))
    if deal["patience"] <= 0:                                      # out of patience, still apart → walk
        return "walk", None
    mid = (deal["lo"] + deal["hi"]) / 2.0                          # both concede toward the middle
    deal["ask"] -= (deal["ask"] - mid) * s_conc
    deal["bid"] += (mid - deal["bid"]) * b_conc
    deal["patience"] -= 1
    deal["round"] += 1
    return "haggle", None


def open_deal(lo: float, hi: float, patience: int) -> dict:
    """A fresh negotiation: seller anchors at his max (hi), buyer at his min (lo)."""
    return {"lo": lo, "hi": hi, "ask": hi, "bid": lo, "patience": patience, "round": 0}


def settle(store, world_id: int, buyer: str, seller: str, item_id: str, price: int) -> dict:
    """Move REAL state: buyer pays coins, seller receives, the item moves seller→buyer. Store-side."""
    store.purse_add(world_id, buyer, -price)
    store.purse_add(world_id, seller, price)
    store.inv_move(world_id, item_id, buyer)
    return {"price": price,
            "buyer_coins": store.purse_get(world_id, buyer),
            "seller_coins": store.purse_get(world_id, seller)}
