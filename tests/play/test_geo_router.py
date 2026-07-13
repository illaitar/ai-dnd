"""route_geo_ask: ONE mind-call decides help + which place/person; code clamps the chosen ids to
its own sets. Stub manager feeds canned JSON: share / refuse / refer / out-of-set / parse-fail."""
from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core, geo
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


class _Stub:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def call(self, role, messages, **kw):
        self.calls.append(messages)
        return {"content": self.content}


def _person(pid, name, role, home, work):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    return SimpleNamespace(id=pid, name=name, role=role, home=home, work=work,
                           persona={"нрав": "практичная"}, state=st)


class _FakeCity:
    def __init__(self):
        self._adj = {42: {43}, 43: {42}}

    def route(self, a, b):
        from aidnd.citygraph.model import Nearby, Route
        return Route(found=True, nodes=[a, 1, b if isinstance(b, int) else 40], bearing="З",
                     near_target=Nearby("b_well", "колодец", 30.0), landmarks=[])


@pytest.fixture
def town(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    st.save_building(1, "b_house_oda", False, 42, "дом Оды",
                     {"name": "дом Оды", "type": "жилой дом"})
    st.save_building(1, "b_smithy", True, 48, "кузница «Молот и мех»",
                     {"name": "кузница «Молот и мех»", "type": "кузница оружейная"})
    st.save_building(1, "b_house_gorm", False, 40, "дом Горма",
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
        d.update(wid=1, gt=600, city=_FakeCity(), people=people, keynode=keynode, cr2b=cr2b, loc=50)
        yield
    finally:
        d.clear(); d.update(saved)


def _run(monkeypatch, content):
    stub = _Stub(content)
    monkeypatch.setattr(core, "_model", lambda: stub)
    return geo.route_geo_ask("p_oda", "где купить оружие?", 50), stub


def test_share(town, monkeypatch):
    dec, _ = _run(monkeypatch, '{"help":"да","bid":"b_smithy","refer_pid":null,"манера":"по-деловому"}')
    assert dec["kind"] == "share" and dec["place"]["bid"] == "b_smithy"


def test_refuse(town, monkeypatch):
    dec, _ = _run(monkeypatch, '{"help":"нет","bid":null,"refer_pid":null,"манера":"отвернувшись"}')
    assert dec["kind"] == "refuse" and dec["place"] is None


def test_refer(town, monkeypatch):
    dec, _ = _run(monkeypatch, '{"help":"да","bid":null,"refer_pid":"p_gorm","манера":"пожав плечами"}')
    assert dec["kind"] == "refer" and dec["refer"]["pid"] == "p_gorm"


def test_out_of_set_bid_clamps_to_deflect(town, monkeypatch):
    dec, _ = _run(monkeypatch, '{"help":"да","bid":"b_castle","refer_pid":null,"манера":"махнув рукой"}')
    assert dec["kind"] == "deflect" and dec["place"] is None


def test_bid_field_holding_the_place_name_resolves_to_share(town, monkeypatch):
    """The model sometimes echoes the NAME instead of the [bid] tag — FIX 1 name-fallback clamp
    must still resolve it to the real place (never invent, but don't collapse to deflect either)."""
    dec, _ = _run(monkeypatch,
                  '{"help":"да","bid":"кузница «Молот и мех»","refer_pid":null,"манера":"x"}')
    assert dec["kind"] == "share" and dec["place"]["bid"] == "b_smithy"


def test_garbage_name_in_bid_still_deflects(town, monkeypatch):
    dec, _ = _run(monkeypatch, '{"help":"да","bid":"замок на горе","refer_pid":null,"манера":"x"}')
    assert dec["kind"] == "deflect" and dec["place"] is None


def test_deflect_drops_manera_even_if_model_wrote_one(town, monkeypatch):
    """FIX 2: a deflect must never carry the model's leaked residue via манера."""
    dec, _ = _run(monkeypatch,
                  '{"help":"уклончиво","bid":"b_castle","refer_pid":null,'
                  '"манера":"ну, это у кузницы «Молот и мех», иди на север"}')
    assert dec["kind"] == "deflect" and dec["манера"] == ""


def test_parse_failure_deflects(town, monkeypatch):
    dec, _ = _run(monkeypatch, "не JSON вовсе")
    assert dec["kind"] == "deflect" and dec["place"] is None and dec["refer"] is None


def test_prompt_lists_only_known_places(town, monkeypatch):
    _, stub = _run(monkeypatch, '{"help":"да","bid":"b_smithy","refer_pid":null,"манера":"x"}')
    sys = stub.calls[-1][0]["content"]
    assert "кузница «Молот и мех»" in sys and "b_castle" not in sys


def test_resolver_strips_bracketed_id():
    """Live finding: the model echoes the rendered format — "[key:9]" must resolve to key:9."""
    from aidnd.server.play.engine.geo import _resolve_place, _resolve_refer
    places = [{"bid": "key:9", "name": "Оружейная у моста", "kind": "лавка", "goods": "оружие", "node": 5, "why_known": "все знают"}]
    assert _resolve_place("[key:9]", places)["bid"] == "key:9"
    assert _resolve_place("«Оружейная у моста»", places)["bid"] == "key:9"
    acq = [{"pid": "pool:0007", "name": "Сельма Косой", "role": "горожанин", "home": 3, "where_line": "рядом"}]
    assert _resolve_refer("[pool:0007]", acq)["pid"] == "pool:0007"
