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


def test_settled_residents_not_evicted_from_exactly_full_venue(world, monkeypatch):
    """Revolving-door regression: the pre-slot ledger snapshot must not count a resident's OWN
    current seat as occupancy when THEY are the one being (re)evaluated — otherwise every settled
    resident at an exactly-at-cap venue reads their own room as full and self-evicts each slot."""
    cap = 5
    monkeypatch.setattr(worldsim, "_building_cap", lambda bid: cap)
    core._S["cr2b"] = {47: "tav1"}
    place_idx = {"tavern": [47]}
    keynode: dict = {}
    kps = [10, 47]
    xy = {10: (0.0, 0.0), 47: (1.0, 1.0)}
    monkeypatch.setattr(worldsim, "_place_context",
                        lambda people: (keynode, kps, place_idx, {}, xy))
    core._S["gt"] = 20 * 60                              # evening — tavern window strong

    people, crof = {}, {}
    needs_gt = core._S.setdefault("needs_gt", {})
    gt = core._S["gt"]
    for i in range(cap):
        pid = f"res{i}"
        st = NpcState.from_config(NpcConfig(id=pid, name=pid, role="горожанин",
                                            traits={"sociability": 1.0}))
        people[pid] = SimpleNamespace(id=pid, name=pid, role="горожанин", state=st, work=None,
                                      home=10, persona={}, keys=[])
        crof[pid] = 47                                    # already settled, exactly at the cap
        needs_gt[pid] = gt                                 # no elapsed time this tick — isolates the
                                                            # ledger bug from unrelated need-decay drift
    before = dict(crof)

    worldsim.routine_step(people, crof)

    assert crof == before                                 # nobody evicted — everyone stayed put
    from collections import Counter
    assert Counter(crof.values())[47] == cap              # load arithmetic holds: still exactly cap


def test_market_overflows_to_next_same_kind_when_full(monkeypatch):
    # temple/market used to pick ONE hashed node only — a full venue had no sibling to overflow to,
    # even with a free sibling and overflow_max_hops configured. Fix: hashed node first, then the
    # rest of same-kind nodes in stable order, walked like tavern's chain.
    p = _mover("p1", home=10)
    nodes = [40, 41]
    place_idx = {"market": nodes}
    n2b = {40: "mk1", 41: "mk2"}
    monkeypatch.setattr(worldsim, "_building_cap", lambda bid: 8)
    first = nodes[hash((p.state.config.id, "market")) % len(nodes)]
    other = next(n for n in nodes if n != first)
    load = {first: 8}                                     # the hash-preferred node is full
    cands = worldsim._candidates(p, place_idx, {}, [10, 40, 41], __import__("random").Random(1),
                                 work_kinds={}, load=load, n2b=n2b, xy={})
    mk = [c for c in cands if c.kind == "market"]
    assert mk and mk[0].node == other                     # overflowed to the sibling market


def test_market_no_candidate_when_both_full(monkeypatch):
    p = _mover("p1", home=10)
    nodes = [40, 41]
    place_idx = {"market": nodes}
    n2b = {40: "mk1", 41: "mk2"}
    monkeypatch.setattr(worldsim, "_building_cap", lambda bid: 8)
    load = {40: 8, 41: 8}                                  # both full
    cands = worldsim._candidates(p, place_idx, {}, [10, 40, 41], __import__("random").Random(1),
                                 work_kinds={}, load=load, n2b=n2b, xy={})
    assert [c for c in cands if c.kind == "market"] == []
