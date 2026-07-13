"""direction_line: a thin formatter over City.route — minutes (steps × step_min → RU numeral) +
compass side + nearest landmark. Exact arithmetic from spec §5 Example A step 6.

Also covers acquaintances(pid, from_node): kin/friend/coworker homes → where_line, including the
coworker-home source (carried from T1 review — two people sharing a work bid)."""
from types import SimpleNamespace

import pytest

from aidnd.citygraph.model import Nearby, Route
from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core, geo
from aidnd.server.play.engine.session.config import PB


class _RouteCity:
    """City stub whose route() returns a canned Route keyed by (from_node, bid)."""
    def __init__(self, table):
        self.table = table

    def route(self, a, b):
        return self.table.get((a, b), Route(found=False))


def _person(pid, name, role, home, work):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    return SimpleNamespace(id=pid, name=name, role=role, home=home, work=work,
                           persona={}, state=st)


@pytest.fixture
def wired(monkeypatch):
    saved = dict(core._S._d()); d = core._S._d()
    table = {
        # spec §5 step 6: 5 steps, bearing С, nearest = рыночная площадь
        (50, "b_smithy"): Route(found=True, nodes=[50, 52, 53, 47, 46, 48], bearing="С",
                                near_target=Nearby("b_market", "рыночная площадь", 42.7),
                                landmarks=[]),
        # example C: 2 steps, bearing З, nearest = колодец
        (50, "b_house_gorm"): Route(found=True, nodes=[50, 51, 40], bearing="З",
                                    near_target=Nearby("b_well", "колодец", 30.0), landmarks=[]),
    }
    try:
        d.clear()
        d.update(wid=1, city=_RouteCity(table), loc=50, people={})
        yield d
    finally:
        d.clear(); d.update(saved)


def test_exact_direction_sentence(wired):
    assert geo.direction_line(50, "b_smithy") == "минут пять ходу к северу, за рыночной площадью"


def test_step_min_scaling(wired, monkeypatch):
    monkeypatch.setitem(PB, "step_min", 2)                 # 5 steps × 2 → 10 минут
    assert geo.direction_line(50, "b_smithy") == "минут десять ходу к северу, за рыночной площадью"


def test_west_two_steps(wired):
    assert geo.direction_line(50, "b_house_gorm") == "в паре минут ходу к западу, у колодца"


def test_disconnected_target(wired):
    # Review Finding 3: incidents.py compares against geo.FAR_LINE, not a duplicated literal —
    # pin the module constant to the exact sentence direction_line returns when unroutable.
    assert geo.FAR_LINE == "это на другом конце города"
    assert geo.direction_line(50, "b_nowhere") == geo.FAR_LINE


def test_bearing_all_eight_winds():
    assert geo._SIDE["С"] == "к северу"
    assert geo._SIDE["СВ"] == "к северо-востоку"
    assert geo._SIDE["В"] == "к востоку"
    assert geo._SIDE["ЮВ"] == "к юго-востоку"
    assert geo._SIDE["Ю"] == "к югу"
    assert geo._SIDE["ЮЗ"] == "к юго-западу"
    assert geo._SIDE["З"] == "к западу"
    assert geo._SIDE["СЗ"] == "к северо-западу"


@pytest.fixture
def acq_town(monkeypatch):
    """Ада Вент (viewer) has a kin (Горм Вент, same surname) and a coworker (Иво Лаас, same
    work bid b_market_stall, no kinship, low affinity) — both homes known, both referrable."""
    saved = dict(core._S._d()); d = core._S._d()
    table = {
        (50, "b_house_gorm"): Route(found=True, nodes=[50, 51, 40], bearing="З",
                                    near_target=Nearby("b_well", "колодец", 30.0), landmarks=[]),
        (50, "b_house_ivo"): Route(found=True, nodes=[50, 44, 45], bearing="В",
                                   near_target=None, landmarks=[]),
    }
    people = {
        "p_ada": _person("p_ada", "Ада Вент", "швея", 42, "b_market_stall"),
        "p_gorm": _person("p_gorm", "Горм Вент", "кузнец", 40, "b_smithy"),
        "p_ivo": _person("p_ivo", "Иво Лаас", "кузнец", 45, "b_market_stall"),
    }
    cr2b = {40: "b_house_gorm", 45: "b_house_ivo"}
    try:
        d.clear()
        d.update(wid=1, city=_RouteCity(table), loc=50, people=people, cr2b=cr2b)
        yield d
    finally:
        d.clear(); d.update(saved)


def test_acquaintances_includes_kin_with_where_line(acq_town):
    entries = {e["pid"]: e for e in geo.acquaintances("p_ada", 50)}
    assert entries["p_gorm"]["name"] == "Горм Вент"
    assert entries["p_gorm"]["role"] == "кузнец"
    assert entries["p_gorm"]["home"] == 40
    assert entries["p_gorm"]["where_line"] == "в паре минут ходу к западу, у колодца"


def test_acquaintances_includes_coworker_with_where_line(acq_town):
    """Carried from T1 review: coworker-home source (two people sharing a work bid) must
    surface in acquaintances (mirrors the known_places "свои" coworker path)."""
    entries = {e["pid"]: e for e in geo.acquaintances("p_ada", 50)}
    assert "p_ivo" in entries
    assert entries["p_ivo"]["role"] == "кузнец"
    assert entries["p_ivo"]["home"] == 45
    assert entries["p_ivo"]["where_line"] == geo.direction_line(50, "b_house_ivo")
