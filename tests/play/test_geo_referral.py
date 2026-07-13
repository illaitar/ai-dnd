"""geo_answer via the router: share reveals; refer names a real findable person with NO map mark;
refuse/deflect stay mark-free; a non-place line returns None (say() runs unchanged)."""
from types import SimpleNamespace

import pytest

from aidnd.citygraph.model import Nearby, Route
from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core, geo
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


class _Stub:
    def __init__(self, content):
        self.content = content

    def call(self, role, messages, **kw):
        return {"content": self.content}


def _person(pid, name, role, home, work):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    return SimpleNamespace(id=pid, name=name, role=role, home=home, work=work,
                           persona={"нрав": "практичная"}, state=st)


class _City:
    def __init__(self):
        self._adj = {42: {43}, 43: {42}}

    def route(self, a, b):
        return Route(found=True, nodes=[50, 51, 40], bearing="З",
                     near_target=Nearby("b_well", "колодец", 30.0), landmarks=[])


@pytest.fixture
def town(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    st.save_building(1, "b_house_oda", True, 42, "дом Оды",
                     {"name": "дом Оды", "type": "жилой дом"})
    st.save_building(1, "b_smithy", True, 48, "кузница «Молот и мех»",
                     {"name": "кузница «Молот и мех»", "type": "кузница оружейная"})
    st.save_building(1, "b_house_gorm", True, 40, "дом Горма",
                     {"name": "дом Горма", "type": "жилой дом"})
    keynode = {"b_house_oda": 42, "b_smithy": 48, "b_house_gorm": 40}
    cr2b = {42: "b_house_oda", 48: "b_smithy", 40: "b_house_gorm"}
    people = {
        "p_oda": _person("p_oda", "Ода Вент", "лавочница", 42, "b_smithy"),
        "p_gorm": _person("p_gorm", "Горм Вент", "кузнец", 40, "b_smithy"),
    }
    saved = dict(core._S._d()); d = core._S._d()
    try:
        d.clear()
        d.update(wid=1, gt=600, city=_City(), people=people, keynode=keynode, cr2b=cr2b, loc=50)
        yield
    finally:
        d.clear(); d.update(saved)


def test_share_answer_has_reveal(town, monkeypatch):
    monkeypatch.setattr(core, "_model",
                        lambda: _Stub('{"help":"да","bid":"b_smithy","refer_pid":null,"манера":"x"}'))
    ans = geo.geo_answer("p_oda", "где купить оружие?", 50)
    assert ans["reveal"] and ans["reveal"]["bid"] == "b_smithy"
    assert "кузница" in ans["geo_line"]


def test_refer_answer_no_reveal_names_person(town, monkeypatch):
    monkeypatch.setattr(core, "_model",
                        lambda: _Stub('{"help":"да","bid":null,"refer_pid":"p_gorm","манера":"y"}'))
    ans = geo.geo_answer("p_oda", "где дом Ветла?", 50)
    assert ans["reveal"] is None                              # nothing revealed on a referral
    assert "Горм" in ans["geo_line"] and "у колодца" in ans["geo_line"]


def test_refuse_answer_no_reveal(town, monkeypatch):
    monkeypatch.setattr(core, "_model",
                        lambda: _Stub('{"help":"нет","bid":null,"refer_pid":null,"манера":"z"}'))
    ans = geo.geo_answer("p_oda", "где кузница?", 50)
    assert ans["reveal"] is None


def test_non_place_line_returns_none(town, monkeypatch):
    monkeypatch.setattr(core, "_model", lambda: _Stub("{}"))
    assert geo.geo_answer("p_oda", "как твои дела?", 50) is None
