"""Framer grounding: the giver's known-place NAMES widen _allowed; a pitch naming a known place
gets the real direction_line appended. A place ∉ giver's set cannot enter allowed."""
from types import SimpleNamespace

import pytest

from aidnd.citygraph.model import Nearby, Route
from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core
from aidnd.server.play.engine.quests import framing as F
from aidnd.server.play.engine.quests import pipeline as P
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


class _City:
    def __init__(self):
        self._adj = {}

    def route(self, a, b):
        return Route(found=True, nodes=[50, 1, 2, 3, 48], bearing="С",
                     near_target=Nearby("b_market", "рыночная площадь", 42.7), landmarks=[])


def _person(pid, name, role, home, work):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    return SimpleNamespace(id=pid, name=name, role=role, home=home, work=work,
                           persona={}, state=st)


@pytest.fixture
def town(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    st.save_building(1, "b_smithy", True, 48, None,
                    {"name": "кузница «Молот и мех»", "type": "кузница оружейная"})
    st.save_building(1, "b_house_gorm", True, 40, None,
                    {"name": "дом Горма", "type": "жилой дом"})
    keynode = {"b_smithy": 48, "b_house_gorm": 40}
    cr2b = {48: "b_smithy", 40: "b_house_gorm"}
    people = {"npc:gorm": _person("npc:gorm", "Горм Вент", "кузнец", 40, "b_smithy")}
    saved = dict(core._S._d()); d = core._S._d()
    try:
        d.clear()
        d.update(wid=1, gt=600, city=_City(), people=people, keynode=keynode, cr2b=cr2b, loc=50)
        yield
    finally:
        d.clear(); d.update(saved)


def _seed():
    return {"sid": "s1", "pattern": "plain_need", "giver": "npc:gorm", "giver_name": "Горм Вент",
            "why": "нужда", "goal": {"done": {"type": "have", "item": "молот"}},
            "cast": {"villain": None, "prize": None}}


def test_allowed_includes_known_place_names(town):
    allowed = P._allowed(_seed())
    assert "кузница «Молот и мех»" in allowed


def test_place_outside_giver_set_absent_from_allowed(town):
    allowed = P._allowed(_seed())
    assert "b_castle" not in allowed and "замок" not in allowed


class _Stub:
    def __init__(self, content):
        self.content = content

    def call(self, role, messages, **kw):
        return {"content": self.content}


def test_pitch_naming_known_place_gets_direction_appended(town, monkeypatch):
    good = ('{"pitch":"Приходи в кузницу «Молот и мех».",'
            '"foreshadow":"Тебя гложет нужда.","reveal":""}')
    allowed = P._allowed(_seed())
    art = F.framer(_seed(), allowed, _Stub([good]) if False else _Stub(good))
    assert art is not None
    assert "минут" in art["pitch"] and "к северу" in art["pitch"]     # direction_line appended
