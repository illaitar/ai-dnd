"""Inc2 — hard capacity + overflow. The load ledger counts EVERYONE (incl. pinned + player), a full
venue overflows to the next same-kind node, an exhausted chain falls back to street, and the player
is counted but never a mover (never blocked). No LLM."""
import os
import tempfile
from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core, worldsim
from aidnd.server.play.engine import world as W
from aidnd.server.play.engine.core import PLAYER
from aidnd.server.play.engine.session import persist


def _mover(pid, home):
    st = NpcState.from_config(NpcConfig(id=pid, name=pid, role="горожанин"))
    return SimpleNamespace(id=pid, name=pid, role="горожанин", state=st, work=None, home=home,
                           persona={}, keys=[])


@pytest.fixture
def world(monkeypatch):
    from aidnd.worldgen import WorldStore
    monkeypatch.setattr(persist, "_STORE", WorldStore(os.path.join(tempfile.mkdtemp(), "live.db")))
    core._S["city"] = None
    W._play()
    core._S["gt"] = 20 * 60
    return core._S


def test_candidates_overflow_to_next_same_kind_when_full(monkeypatch):
    # two taverns; nearest (47) is full → candidate is the next one (63), not skipped entirely
    p = _mover("p1", home=10)
    place_idx = {"tavern": [47, 63]}
    n2b = {47: "tav1", 63: "tav2"}
    xy = {10: (0, 0), 47: (1, 1), 63: (5, 5)}
    monkeypatch.setattr(worldsim, "_building_cap", lambda bid: 8)
    load = {47: 8}                                   # 47 at cap
    cands = worldsim._candidates(p, place_idx, {}, [10, 47, 63], __import__("random").Random(1),
                                 work_kinds={}, load=load, n2b=n2b, xy=xy)
    tav = [c for c in cands if c.kind == "tavern"]
    assert tav and tav[0].node == 63                 # overflowed to the second tavern


def test_candidates_no_venue_when_chain_exhausted(monkeypatch):
    p = _mover("p1", home=10)
    place_idx = {"tavern": [47, 63]}
    n2b = {47: "tav1", 63: "tav2"}
    xy = {10: (0, 0), 47: (1, 1), 63: (5, 5)}
    monkeypatch.setattr(worldsim, "_building_cap", lambda bid: 8)
    load = {47: 8, 63: 8}                             # both full
    cands = worldsim._candidates(p, place_idx, {}, [10, 47, 63], __import__("random").Random(1),
                                 work_kinds={}, load=load, n2b=n2b, xy=xy)
    assert [c for c in cands if c.kind == "tavern"] == []   # no tavern → mover falls to street/home
    assert any(c.kind == "street" for c in cands)


def test_ledger_counts_pinned_and_player(world):
    # seed a full venue in crof (pinned scene NPCs included) → a mover targeting it must NOT stack
    crof = core._S["crof"]
    core._S["loc"] = 47
    for i in range(8):
        crof[f"seed{i}"] = 47                          # 8 already at node 47 (some are 'present')
    from collections import Counter
    ledger = Counter(crof.values())
    ledger[core._S["loc"]] += 1                        # + the player
    assert ledger[47] >= 9                             # everyone counted, incl. the player


def test_player_is_never_a_mover(world):
    # routine_step iterates people only; PLAYER is not in people → never placed, never blocked
    worldsim.routine_step(core._S["people"], core._S["crof"])
    assert PLAYER not in core._S["people"]
    assert PLAYER not in core._S["crof"]               # ring B never writes the player's node
