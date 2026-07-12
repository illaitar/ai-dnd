import os
import tempfile

from aidnd.server.play.mechanics.haggle import (
    deal_corridor,
    haggle_tick,
    open_deal,
    settle,
)
from aidnd.worldgen import WorldStore


def test_deal_corridor_wanting_buyer_vs_none():
    c = deal_corridor(10, {"wealth": 0.4}, {"greed": 0.5}, {"wealth": 0.3}, {"greed": 0.4}, 0.8)
    assert c is not None and c[1] > c[0]                     # a wanting buyer → a real corridor
    none = deal_corridor(10, {"wealth": 0.0}, {"greed": 0.2, "ambition": 0.2},
                         {"wealth": 1.0}, {"greed": 1.0, "ambition": 1.0}, 0.0)
    assert none is None                                      # uninterested, cash-hungry buyer → no deal


def test_haggle_converges_over_four_ticks_to_9():
    """Spec Example A: corridor [6,12], concessions 0.45/0.50, ε=1.0 → settles at 9 on tick 4."""
    deal = open_deal(6.0, 12.0, 4)
    steps = []
    for _ in range(6):
        steps.append(haggle_tick(deal, 0.45, 0.50, 1.0))
        if steps[-1][0] != "haggle":
            break
    assert steps[-1] == ("settle", 9)
    assert len(steps) == 4


def test_haggle_walks_when_out_of_patience():
    """Spec Example C: too few rounds to close the gap → walk away, no deal."""
    deal = open_deal(6.0, 12.0, 2)
    res = []
    for _ in range(5):
        res.append(haggle_tick(deal, 0.3, 0.3, 1.0))
        if res[-1][0] != "haggle":
            break
    assert res[-1] == ("walk", None)


def test_settle_moves_real_coins_and_the_item():
    s = WorldStore(os.path.join(tempfile.mkdtemp(), "live.db"))
    s.purse_add(1, "seller1", 5)
    s.purse_add(1, "buyer1", 20)
    s.save_item({"id": "it:knife1", "kind": "weapon", "name": "нож"})
    s.inv_add(1, "it:knife1", "seller1")
    res = settle(s, 1, "buyer1", "seller1", "it:knife1", 9)
    assert res["price"] == 9
    assert s.purse_get(1, "buyer1") == 11 and s.purse_get(1, "seller1") == 14   # coins moved
    assert any(r["item_id"] == "it:knife1" for r in s.inventory(1, "buyer1"))    # knife → buyer
    assert not any(r["item_id"] == "it:knife1" for r in s.inventory(1, "seller1"))


class _Mem:
    def add(self, *a, **k):
        pass


def _state(needs, traits, agenda=None):
    cfg = type("Cfg", (), {"traits": traits, "id": "?", "name": "?", "role": "?"})()
    ag = [type("Ag", (), {"summary": agenda})()] if agenda else []
    return type("St", (), {"needs": needs, "config": cfg, "agendas": ag, "memory": _Mem()})()


def _people_seller_buyer():
    return {
        "seller": type("P", (), {"state": _state({"wealth": 0.3}, {"greed": 0.4})})(),
        "buyer": type("P", (), {"state": _state({"wealth": 0.2}, {"greed": 0.3})})(),
    }


def test_npc_trade_step_opens_from_a_buy_action_and_settles(monkeypatch):
    """The mind emits a `buy` action → a deal opens, haggles over several ticks (voiced as speech),
    and settles for real in the store. The LLM's CHOICE to buy is the driver (no code heuristic)."""
    from aidnd.server.play.engine import world as W
    from aidnd.server.play.engine.session import persist

    s = WorldStore(os.path.join(tempfile.mkdtemp(), "live.db"))
    monkeypatch.setattr(persist, "_STORE", s)
    monkeypatch.setattr(W, "_wid", lambda: 1)
    monkeypatch.setattr(W, "_display", lambda pid, people: pid)

    people = _people_seller_buyer()
    s.save_item({"id": "it:kn", "kind": "weapon", "name": "нож", "worth": 10})
    s.inv_add(1, "it:kn", "seller")
    s.purse_add(1, "seller", 2)
    s.purse_add(1, "buyer", 30)
    order = ["seller", "buyer"]
    lv = {"clock": 100, "haggle": {}, "names": {"seller": "Кузнец", "buyer": "Ветл"}}
    decisions = {"buyer": {"actions": [{"tool": "buy", "seller": "Кузнец", "good": "нож"}]}}
    feeds = []
    for _ in range(8):
        feed = []
        W._npc_trade_step(people, order, decisions, lv, feed)
        feeds.append(feed)
        if not lv["haggle"]:
            break
    assert any(r["item_id"] == "it:kn" for r in s.inventory(1, "buyer"))     # knife changed hands
    assert s.purse_get(1, "seller") > 2 and s.purse_get(1, "buyer") < 30      # real coins moved
    assert any(e.get("k") == "deed" and "переходит" in e.get("text", "") for f in feeds for e in f)
    assert len([e for f in feeds for e in f if e.get("k") == "speech"]) >= 4   # ≥2 haggle rounds, voiced


def test_npc_trade_step_needs_a_buy_action_and_a_good(monkeypatch):
    from aidnd.server.play.engine import world as W
    from aidnd.server.play.engine.session import persist

    s = WorldStore(os.path.join(tempfile.mkdtemp(), "live.db"))
    monkeypatch.setattr(persist, "_STORE", s)
    monkeypatch.setattr(W, "_wid", lambda: 1)
    monkeypatch.setattr(W, "_display", lambda pid, people: pid)
    people = _people_seller_buyer()
    s.save_item({"id": "it:kn", "kind": "weapon", "name": "нож", "worth": 10})
    s.inv_add(1, "it:kn", "seller")
    s.purse_add(1, "buyer", 30)
    order = ["seller", "buyer"]
    lv = {"clock": 1, "haggle": {}, "names": {"seller": "Кузнец", "buyer": "Ветл"}}
    W._npc_trade_step(people, order, {}, lv, [])            # no buy action → no deal, even with a corridor
    assert lv["haggle"] == {}
    s.inv_move(1, "it:kn", "used")                          # seller now holds nothing sellable
    W._npc_trade_step(people, order, {"buyer": {"actions": [{"tool": "buy", "seller": "Кузнец"}]}}, lv, [])
    assert lv["haggle"] == {}                                # buy intent but no good → still no deal


def test_background_hum_opens_from_a_commercial_agenda(monkeypatch):
    """The background trickle: a commercially-minded buyer (no explicit `buy` action) opens a deal."""
    from aidnd.server.play.engine import world as W
    from aidnd.server.play.engine.session import persist

    s = WorldStore(os.path.join(tempfile.mkdtemp(), "live.db"))
    monkeypatch.setattr(persist, "_STORE", s)
    monkeypatch.setattr(W, "_wid", lambda: 1)
    monkeypatch.setattr(W, "_display", lambda pid, people: pid)
    monkeypatch.setitem(W.PB, "haggle_bg_p", 1.0)          # force the trickle to fire

    people = {
        "seller": type("P", (), {"state": _state({"wealth": 0.3}, {"greed": 0.4})})(),
        "buyer": type("P", (), {"state": _state({"wealth": 0.2}, {"greed": 0.3},
                                                "накопить монет и купить нож")})(),
    }
    s.save_item({"id": "it:kn", "kind": "weapon", "name": "нож", "worth": 10})
    s.inv_add(1, "it:kn", "seller")
    s.purse_add(1, "buyer", 30)
    lv = {"clock": 100, "haggle": {}, "names": {"seller": "Кузнец", "buyer": "Ветл"}}
    W._npc_trade_step(people, ["seller", "buyer"], {}, lv, [])   # NO buy action; the agenda drives it
    assert lv["haggle"]                                          # a deal opened from the agenda hum
