"""Утренний конвейер: один seed всплывает; приватный → offered, публичный → board; протухший → compost."""
import json
import os
import re
import tempfile
from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.mind.agenda import Agenda, Milestone
from aidnd.server.play.engine import core
from aidnd.server.play.engine.quests import pipeline as P
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


class _Stub:
    """Сценарно-нейтральный дублёр LLM: судья ранжирует ЛЮБОЙ поданный seed (по его sid из
    payload'а), фреймер называет только заказчика (он всегда в списке МОЖНО НАЗЫВАТЬ) — поэтому один
    и тот же дублёр обслуживает и приватный (Дунн), и публичный (Марта) сценарии без подгонки."""

    def call(self, role, messages, **kw):
        sys, usr = messages[0]["content"], messages[1]["content"]
        if "редактор" in sys:                       # judge
            sids = re.findall(r"seed_[a-z_]+", usr)
            top = sids[0] if sids else ""
            return {"content": json.dumps({"rank": [top], "veto": [],
                                           "why": {top: "тёплый крючок"}}, ensure_ascii=False)}
        m = re.search(r"ЗАКАЗЧИК:\s*(.+?)\.", usr)   # framer
        giver = (m.group(1) if m else "Заказчик").split()[0]   # имя без фамилии (валидатор дробит на токены)
        return {"content": json.dumps(
            {"pitch": f"{giver} ищет помощи, награда найдётся.",
             "foreshadow": f"{giver} не находит покоя.",
             "reveal": f"{giver} ещё вспомнит обиду."}, ensure_ascii=False)}


def _person(pid, name, role, agendas=(), rels=None):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    st.agendas = list(agendas)
    st.relationships = dict(rels or {})
    return SimpleNamespace(name=name, role=role, state=st, persona={}, work=None)


@pytest.fixture
def town(monkeypatch):
    snap = dict(core._S._d())                        # снимок сессии world-1 — вернём после теста
    tmp = tempfile.mkdtemp()
    st = WorldStore(os.path.join(tmp, "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    monkeypatch.setattr(core, "_model", lambda: _Stub())
    gt = 3 * 1440
    core._S["gt"] = gt
    dunn_ms = Milestone("вернуть гроссбух сестры", "acquire", "debt:marta", {},
                        {"type": "have", "item": "гроссбух"})
    dunn = _person("npc:dunn", "Дунн Ли", "охотник",
                   agendas=[Agenda("вернуть гроссбух сестры", "ambition", 0.7, [dunn_ms])],
                   rels={"npc:ralf": {"affinity": -0.4}})
    ralf = _person("npc:ralf", "Ральф Ли", "ростовщик", rels={"npc:dunn": {"affinity": -0.1}})
    marta = _person("npc:marta", "Марта Ли", "торговка", rels={"npc:ralf": {"affinity": -0.6}})
    core._S["people"] = {"npc:dunn": dunn, "npc:ralf": ralf, "npc:marta": marta}
    core._S["crof"] = {"npc:dunn": 7, "npc:ralf": 9, "npc:marta": 4}
    core._S["loc"] = 7                              # игрок в узле Дунна
    core._S["city"] = None
    st.purse_add(core._wid(), "npc:dunn", 41)
    st.deed_add(core._wid(), gt - 1440, "npc:ralf", "promise", "npc:marta", "",
                status="broken", data={"what": "вернуть гроссбух", "made_gt": gt - 1440})
    yield st
    core._S._d().clear()
    core._S._d().update(snap)


def test_one_seed_surfaces_private(town):
    news = P.quest_morning()
    assert news
    offered = town.contracts(core._wid(), "offered")
    emergent = [c for c in offered if c.get("src") == "sift"]
    assert len(emergent) == 1
    ct = emergent[0]
    assert ct["giver"] == "npc:dunn" and ct["arc"]["beat"] == "offered"
    assert ct["done_any"] == [{"type": "have", "item": "гроссбух"}]  # done_any[0] = дословная веха
    assert ct["step"] == 0
    assert ct["steps"][0]["kind"] == "bring"


def test_public_pattern_goes_to_board(town, monkeypatch):
    # заставим просев выдать только публичный паттерн: у Дунна убираем агенду
    core._S["people"]["npc:dunn"].state.agendas = []
    P.quest_morning()
    board = [c for c in town.contracts(core._wid(), "board") if c.get("src") == "sift"]
    assert board and board[0]["giver"] == "npc:marta"
    # grievance pattern: pipeline materialized a REAL revenge milestone on Марта (mirrors deals.py) →
    # done_any[0] is verbatim from it and quest_writeback can advance her cursor uniformly.
    assert board[0]["done_any"][0] == {"type": "dead", "id": "npc:ralf"}
    marta_ag = core._S["people"]["npc:marta"].state.agendas
    assert marta_ag and marta_ag[-1].kind == "revenge"
    assert marta_ag[-1].current().done == {"type": "dead", "id": "npc:ralf"}
    assert f"agenda:npc:marta:{len(marta_ag) - 1}" in board[0]["seed"]["evidence"]


def test_accepted_emergent_contract_survives_give_and_talk(town):
    """CRITICAL regression: an accepted (status→'active') emergent contract used to persist
    step=<dict> — every legacy reader (_ct_cur/_ct_advance) treats 'step' as an int index, so
    min(dict, 0) crashed on the very next give/move/talk while the contract was active."""
    from aidnd.server.play.mechanics import contracts as C

    P.quest_morning()
    ct = next(c for c in town.contracts(core._wid(), "offered") if c.get("src") == "sift")
    assert ct["step"] == 0                            # int, as _make_contract persists it
    # mirror contract_accept (world.py:162-178): flip status to active, data untouched
    town.save_contract(core._wid(), ct["id"], "active",
                       {k: v for k, v in ct.items() if k not in ("id", "status")})
    # unrelated item/npc drive the improvised-contract triggers — must not raise
    assert C._contract_on_give("npc:ralf", {"name": "морковь", "kind": "misc"}) is None
    assert C._contract_on_talk("npc:ralf") is None
    still = next(c for c in town.contracts(core._wid(), "active") if c["id"] == ct["id"])
    assert still["step"] == 0                          # untouched — improvised machinery intact


def test_window_one_holds_across_mornings(town):
    news1 = P.quest_morning()
    assert news1
    first = next(c for c in town.contracts(core._wid(), "offered") if c.get("src") == "sift")
    news2 = P.quest_morning()                          # next morning — window still occupied
    assert not any("зреет дело" in n for n in news2)
    offered = [c for c in town.contracts(core._wid(), "offered") if c.get("src") == "sift"]
    assert len(offered) == 1 and offered[0]["id"] == first["id"]
    core._S["gt"] += (core.PB["quest_offer_days"] + 1) * 1440   # compost frees the window
    news3 = P.quest_morning()
    assert any("зреет дело" in n for n in news3)
    fresh = [c for c in town.contracts(core._wid(), "offered") if c.get("src") == "sift"] + \
            [c for c in town.contracts(core._wid(), "board") if c.get("src") == "sift"]
    assert len(fresh) == 1 and fresh[0]["id"] != first["id"]


def test_llm_unavailable_in_quest_morning_returns_no_offer(town, monkeypatch):
    from aidnd.inference.client import LLMUnavailable

    class _DownStub:
        def call(self, role, messages, **kw):
            raise LLMUnavailable("no model")

    monkeypatch.setattr(core, "_model", lambda: _DownStub())
    news = P.quest_morning()
    assert news == []
    assert not [c for c in town.contracts(core._wid(), "offered") if c.get("src") == "sift"]
    assert not [c for c in town.contracts(core._wid(), "queued") if c.get("src") == "sift"]


def test_expire_compost_closes_offer_and_keeps_agenda(town):
    P.quest_morning()
    ct = next(c for c in town.contracts(core._wid(), "offered") if c.get("src") == "sift")
    core._S["gt"] += (core.PB["quest_offer_days"] + 1) * 1440   # два дня спустя
    news = P._expire_stale()
    assert any("протух" in n or "сам" in n for n in news)
    assert not town.contracts(core._wid(), "offered")
    closed = next(c for c in town.contracts(core._wid(), "closed") if c["id"] == ct["id"])
    assert closed["arc"]["beat"] == "expired"
    assert core._S["people"]["npc:dunn"].state.agendas[0].cursor == 0   # агенда цела — сам займётся
