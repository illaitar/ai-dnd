"""End-to-end Inc 1: a where-question with an exact place name → say() speaks a real direction,
reveals the building (seen|<bid>), and writes a place/told journal row. A non-place line does
neither (regression-safe)."""
import asyncio
from types import SimpleNamespace

import pytest

from aidnd.citygraph.model import Nearby, Route
from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core, geo
from aidnd.server.play.engine.session import persist
from aidnd.server.play.handlers import dialogue as dlg
from aidnd.worldgen import WorldStore


class _Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


class _Voice:
    def call(self, role, messages, **kw):
        sys = messages[0]["content"]
        # route_geo_ask's router prompt is distinguishable by its own fixed wording; answer it
        # with a canned share so geo_answer() can build the geo_line for the real voice call below.
        if "МЕСТА, КОТОРЫЕ ТЫ ЗНАЕШЬ" in sys:
            return {"content": '{"help":"да","bid":"b_smithy","refer_pid":null,"манера":"x"}'}
        # echo whether a geo-fact reached the prompt, so the test can assert wiring
        say = "Ступай к кузнице." if "ГЕО-ФАКТ" in sys else "Не знаю, о чём ты."
        return {"content": f'{{"say": "{say}", "player_tone": "neutral"}}'}


class _RouteCity:
    def __init__(self, table):
        self.table = table
        self._adj = {}
        self.key_buildings = {}  # _world_lookup iterates this — empty means no unrelated match

    def route(self, a, b):
        return self.table.get((a, b), Route(found=False))


def _npc(pid, name, role, home, work):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    return SimpleNamespace(id=pid, name=name, role=role, home=home, work=work,
                           persona={}, portraits={}, state=st, keys=[])


@pytest.fixture
def town(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    st.save_building(1, "b_smithy", True, 48, "кузница «Молот и мех»",
                     {"name": "кузница «Молот и мех»", "type": "кузница оружейная"})
    st.save_building(1, "b_house_oda", True, 42, "дом Оды",
                     {"name": "дом Оды", "type": "жилой дом"})
    keynode = {"b_smithy": 48, "b_house_oda": 42}
    cr2b = {48: "b_smithy", 42: "b_house_oda"}
    table = {(50, "b_smithy"): Route(found=True, nodes=[50, 52, 53, 47, 46, 48], bearing="С",
                                     near_target=Nearby("b_market", "рыночная площадь", 42.7),
                                     landmarks=[])}
    people = {"npc:oda": _npc("npc:oda", "Ода Вент", "лавочница", 42, "b_smithy")}
    crof = {"npc:oda": 50}
    monkeypatch.setattr(dlg, "_play", lambda: (people["npc:oda"], people, crof, cr2b, 50))
    monkeypatch.setattr(dlg, "_world_tick_fast", lambda: {})
    monkeypatch.setattr(dlg, "_pc_coins", lambda: 0)
    monkeypatch.setattr(dlg, "_here_settled", lambda loc, crof_: list(people))  # say() gate is settled-only
    monkeypatch.setattr(core, "_model", lambda: _Voice())
    saved = dict(core._S._d()); d = core._S._d()
    try:
        d.clear()
        d.update(wid=1, gt=600, city_name="Городок", city=_RouteCity(table), people=people,
                 keynode=keynode, cr2b=cr2b, loc=50, seen=None)
        yield st
    finally:
        d.clear(); d.update(saved)


def test_where_question_shares_direction_and_reveals(town):
    res = asyncio.run(dlg.say(_Req({"npc": "npc:oda", "text": "где кузница?"})))
    assert res["line"] == "Ступай к кузнице."                # geo fact reached the voice
    from aidnd.server.play.engine.pc.hero import _seen
    assert "b_smithy" in _seen()                             # map reveal


def test_geo_answer_inside_target_building_no_fake_direction(town):
    """Playtest bug: player asks for a place while already standing inside it (Хельга, «Гнилой
    зуб») — the router still shares b_smithy, but geo_answer must not invent a direction/route to
    where the player already stands, and must skip the map-mark (already inside == already seen)."""
    core._S["inside"] = "b_smithy"
    try:
        ga = geo.geo_answer("npc:oda", "где кузница?", core._S.get("loc"))
    finally:
        core._S["inside"] = None
    assert ga is not None
    assert "уже здесь" in ga["geo_line"]
    assert "ходу" not in ga["geo_line"]          # no minutes/direction phrase
    assert "к северу" not in ga["geo_line"]
    assert ga["reveal"] is None                 # no map-mark for an already-inside share


def test_ordinary_line_no_geo_no_mark(town):
    res = asyncio.run(dlg.say(_Req({"npc": "npc:oda", "text": "как твои дела?"})))
    assert res["line"] == "Не знаю, о чём ты."               # no geo fact injected
    from aidnd.server.play.engine.pc.hero import _seen
    assert "b_smithy" not in _seen()


def test_geo_question_regex():
    assert geo.geo_question("где кузница?")
    assert geo.geo_question("как пройти к храму")
    assert geo.geo_question("где я могу купить оружие")
    assert not geo.geo_question("как твои дела")


def test_geo_question_excludes_vague_hearsay():
    assert not geo.geo_question("где-то слышал об этом")
    assert not geo.geo_question("куда-то дел свой нож")
    assert geo.geo_question("где кузница?")
    assert geo.geo_question("куда мне идти?")
