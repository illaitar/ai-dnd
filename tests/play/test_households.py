"""Слой D1 (демография, docs/citysim.md §D): семьи-домохозяйства селятся вместе (одна фамилия,
один дом), а не 900 одиночек по случайным домам."""

import os
import random
import tempfile
from collections import defaultdict

import pytest

from aidnd.server.play.engine import core


@pytest.fixture
def world(monkeypatch):
    from aidnd.server.play.engine.world import _play
    from aidnd.worldgen import WorldStore

    monkeypatch.setattr(core, "_STORE",
                        WorldStore(os.path.join(tempfile.mkdtemp(), "live.db")))
    core._S["city"] = None                              # свежее расселение в чистый store
    _city, people, _crof, _cr2b, _loc = _play()
    return people


def _by_home(people):
    h = defaultdict(list)
    for pid, p in people.items():
        h[p.home].append(pid)
    return h


def test_households_share_surname_and_home(world):
    from aidnd.server.play.engine.world import _surname
    homes = _by_home(world)
    families = {h: pids for h, pids in homes.items() if len(pids) >= 2}
    assert len(families) > 50, "семей почти нет — все живут поодиночке"
    for pids in families.values():                       # в одном доме — одна фамилия (семья)
        surs = {_surname(world[p].name) for p in pids}
        assert len(surs) == 1, f"смешанная семья в доме: {[world[p].name for p in pids]}"


def test_household_size_bounded(world):
    homes = _by_home(world)
    assert max(len(v) for v in homes.values()) <= 5     # семья, не барак
    multi = sum(1 for v in homes.values() if len(v) >= 2)
    assert multi > len(homes) * 0.4                      # заметная доля домов — семейные


def test_partition_covers_everyone_deterministic(world):
    from aidnd.server.play.engine.world import _households
    rows = core._pool().list_people(limit=100000)
    a = _households(rows, random.Random("settle|x"))
    b = _households(rows, random.Random("settle|x"))
    assert [len(x) for x in a] == [len(x) for x in b]    # детерминизм при том же seed
    flat = [pid for hh in a for pid in hh]
    assert len(flat) == len(set(flat)) == len(rows)      # разбиение — покрытие без пересечений
    assert all(1 <= len(hh) <= 5 for hh in a)
