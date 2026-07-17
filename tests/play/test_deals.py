"""Кейс deal-гейта: заказ убийства — жадный/злой берётся (контракт+эскроу+агенда),
честный отказывает с доносом; авторезолв утром делает исход настоящим."""

import random
from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core
from aidnd.server.play.mechanics import deals

_ORIG_RANDOM = random.Random


class _P:
    def __init__(self, pid, name, role, traits):
        self.name, self.role, self.work, self.persona = name, role, None, {}
        cfg = NpcConfig(id=pid)          # real id: the victim branch matches event.target == config.id
        cfg.traits.update(traits)
        self.state = NpcState(config=cfg)


@pytest.fixture
def world(tmp_path, monkeypatch):
    from aidnd.server.play.engine import deeds as dd
    from aidnd.worldgen import WorldStore

    st = WorldStore(str(tmp_path / "live.db"))
    for mod in (core, deals, dd):
        monkeypatch.setattr(mod, "_store", lambda: st, raising=False)
        monkeypatch.setattr(mod, "_wid", lambda: 1, raising=False)
    st.purse_add(1, "pc", 100)
    people = {
        "bravo": _P("bravo", "Горм", "головорез", {"malice": 0.85, "honesty": 0.2, "greed": 0.8,
                                                   "bravery": 0.8}),
        "clerk": _P("clerk", "Ветл", "лавочник", {"malice": 0.1, "honesty": 0.9, "greed": 0.3}),
        "mark": _P("mark", "Дунн", "горожанин", {"bravery": 0.3}),
    }
    core._S["people"] = people
    core._S["live"] = {"zonemap": {}}
    core._S["gt"] = 8 * 60
    return st, people


def _deal(npc, people, st, **deal):
    out = {"narr": [], "refresh": False}
    return deals.deal_attempt(npc, deal, "openly", out, people, {}, 1), out


def test_bravo_takes_blood_contract(world, monkeypatch):
    st, people = world
    monkeypatch.setattr(deals, "random", SimpleNamespace(Random=lambda *a: _ORIG_RANDOM(5)))
    r, out = _deal("bravo", people, st, kind="dead", target="mark", stake_gold=40)
    assert r.get("refresh") and not r.get("fail"), out["narr"]
    assert st.purse_get(1, "pc") == 60                       # 40 ушли задатком
    act = people["bravo"].state.agendas
    assert act and "уговор" in act[0].summary
    assert any(c.get("executor") == "bravo" for c in st.contracts(1, "active"))


def test_honest_clerk_refuses_and_reports(world):
    st, people = world
    r, out = _deal("clerk", people, st, kind="dead", target="mark", stake_gold=40)
    assert r.get("fail")                                     # честный — без броска отказ
    assert st.purse_get(1, "pc") == 100                      # деньги на месте
    assert any(d["verb"] == "solicit" for d in st.deeds(1, actor="pc"))
    assert people["clerk"].state.rel("pc")["affinity"] <= -0.4


def test_morning_resolves_kill(world, monkeypatch):
    st, people = world
    monkeypatch.setattr(deals, "random", SimpleNamespace(Random=lambda *a: _ORIG_RANDOM(5)))
    deals.deal_attempt("bravo", {"kind": "dead", "target": "mark", "stake_gold": 40},
                       "openly", {"narr": []}, people, {}, 1)
    core._S["gt"] = core._gt() + core.PB["deal_night_min"] + 10
    news = deals._deal_jobs()
    dead = {k.split("|", 1)[1] for k in st.flags_prefix(1, "dead|")}
    if "mark" in dead:                                       # авторезолв — недетерминирован
        assert any("мёртв" in n for n in news)
        assert any(c.get("status") == "done" for c in st.contracts(1))


def test_chain_cut_by_salient(monkeypatch):
    from aidnd.server.play.handlers import freeform as ff

    core._S["live"] = {"salient": None}
    calls = []

    def fake_attempt(step, sc):
        calls.append(step["verb"])
        if step["verb"] == "say":                    # звено будит зал (донос/драка)
            core._S["live"]["salient"] = "крик"
        return {"narr": [f"шаг {step['verb']}"], "refresh": True}

    monkeypatch.setattr(ff, "_attempt", fake_attempt)
    res = ff._run_plan([{"verb": "say"}, {"verb": "move"}, {"verb": "take"}], {}, "т")
    assert calls == ["say"]                          # мир вклинился — остаток не исполнен
    assert res.get("stopped") and res.get("remaining") == "move → take"
    assert any("взрывается" in n for n in res["narr"])
