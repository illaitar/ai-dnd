from __future__ import annotations

from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core, incidents
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


def _person(pid, name, role, home, work):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    return SimpleNamespace(id=pid, name=name, role=role, home=home, work=work, persona={"a": 1},
                           state=st)


@pytest.fixture
def world(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    st.save_building(1, "house:medovar", False, 372, "дом семьи Медовар",
                     {"name": "дом семьи Медовар", "type": "жилой дом"})
    people = {
        "p_dead": _person("p_dead", "Ольд Медовар", "пасечник", 372, None),
        "p_kin": _person("p_kin", "Марта Медовар", "швея", 372, None),
    }
    cr2b = {372: "house:medovar"}
    d = core._S._d(); saved = dict(d)
    try:
        d.clear()
        d.update(wid=1, gt=600, people=people, cr2b=cr2b, keynode={}, loc=50, city=None)
        yield st
    finally:
        d.clear(); d.update(saved)


_HAUNT = {"key": "haunt", "w": 2, "foe": "undead", "victim": "dead_home", "goal": "clear",
          "env": "Ruin", "cr": [0.6, 1.2], "esc": False,
          "title": "неупокоенный — {place}",
          "pitch": "С тех пор как {dead} нашли мёртвым, в его стенах стонет и холодит."}


def test_dead_home_giver_matches_kin_patron(world):
    """Review finding: dead_home set patron=kin but left giver='guild', so the journal named
    the kin while incident_resolve paid from guild coffers. giver must follow patron."""
    people = core._S["people"]
    dead = {"p_dead"}
    alive = {pid: p for pid, p in people.items() if pid not in dead}
    rng = __import__("random").Random("fixed-seed")
    inc = incidents._try_build(_HAUNT, alive, dead, rng)
    assert inc is not None
    assert inc["patron"] == "p_kin"
    assert inc["giver"] == "p_kin"                        # was "guild" — the bug
    assert "Марта Медовар" in inc["news"]                  # journal names the kin (patron)


def test_dead_home_giver_none_when_no_kin(world):
    """When the dead has no living kin, patron stays None and giver stays the guild default —
    the fix must not force a giver that doesn't exist."""
    people = core._S["people"]
    # drop the kin so no relative remains alive
    del people["p_kin"]
    dead = {"p_dead"}
    alive = {pid: p for pid, p in people.items() if pid not in dead}
    rng = __import__("random").Random("fixed-seed")
    inc = incidents._try_build(_HAUNT, alive, dead, rng)
    assert inc is not None
    assert inc["patron"] is None
    assert inc["giver"] == "guild"


def test_dead_home_resolve_pays_from_kin_purse(world):
    """Unit-level: incident_resolve must actually pay the reward out of the kin's own purse
    (not the guild's) when giver is a pid, exactly like home/work incidents already do."""
    st = world
    st.purse_add(1, "p_kin", 50)                          # kin has coin to pay with
    inc = {"id": "inc|test|haunt", "type": "haunt", "goal": "clear", "cr": 0.8,
           "esc": False, "made_gt": 600, "stash": 0, "members": [], "captive": None,
           "patron": "p_kin", "giver": "p_kin", "place": "дом, где жил Ольд Медовар",
           "dead_name": "Ольд Медовар", "vid": "p_dead", "bid": "house:medovar", "node": 372,
           "title": "неупокоенный — дом, где жил Ольд Медовар", "reward": 5}
    st.save_contract(1, inc["id"], "incident", inc)
    kin_before = st.purse_get(1, "p_kin")
    pc_before = st.purse_get(1, "pc")
    narr = incidents.incident_resolve(inc["id"], [])
    kin_after = st.purse_get(1, "p_kin")
    pc_after = st.purse_get(1, "pc")
    assert kin_after == kin_before - 5                     # paid from kin's own wallet
    assert pc_after == pc_before + 5
    assert any("Марта Медовар" in line for line in narr)    # narration names the payer (kin)
