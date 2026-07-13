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
    assert ct["step"]["kind"] == "bring"


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
