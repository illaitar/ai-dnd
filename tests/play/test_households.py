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
    # инвариант D1 — на ВЗРОСЛЫХ (дети/старики докидываются к главе и могут раздуть дом)
    adult_per_home = [sum(1 for q in v if world[q].role not in ("дитя", "старик"))
                      for v in homes.values()]
    assert max(adult_per_home) <= 5                       # семья взрослых, не барак
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


# ── D2: иждивенцы (дети/старики) в пуле (docs/citysim.md §D) ──
def test_dependents_settle_with_family_and_dont_work(world):
    from aidnd.server.play.engine.world import _surname
    deps = [p for p in world.values() if p.role in ("дитя", "старик")]
    assert len(deps) > 100, "иждивенцы не расселились (депген не прогнан?)"
    assert all(p.work is None for p in deps)             # иждивенцы НЕ работают
    homes = _by_home(world)
    with_kin = 0
    for d in deps:
        mates = [world[q] for q in homes[d.home] if q != d.id]
        adults = [m for m in mates if m.role not in ("дитя", "старик")]
        if adults and any(_surname(m.name) == _surname(d.name) for m in adults):
            with_kin += 1
    assert with_kin > len(deps) * 0.9                    # почти все — под крышей взрослой родни


def test_dependent_topup_for_old_world(world, monkeypatch):
    """Старый мир (иждивенцев расселили ПОСЛЕ) — top-up доселяет их к главе, не тревожа взрослых."""
    from aidnd.server.play.engine.world import _play
    wid = core._wid()
    dep_ids = [pid for pid, p in world.items() if p.role in ("дитя", "старик")]
    adult_home = {pid: p.home for pid, p in world.items() if p.role not in ("дитя", "старик")}
    with core._store()._conn() as c:                     # «откатить» мир к состоянию без иждивенцев
        c.executemany("DELETE FROM placements WHERE world_id=? AND npc_id=?",
                      [(wid, pid) for pid in dep_ids])
    core._S["city"] = None                               # пере-заход в мир (restore-путь)
    _c, people2, _cr, _c2, _l = _play()
    deps2 = [p for p in people2.values() if p.role in ("дитя", "старик")]
    assert len(deps2) >= len(dep_ids) * 0.9              # top-up вернул иждивенцев
    moved = sum(1 for pid, h in adult_home.items()
                if pid in people2 and people2[pid].home != h)
    assert moved == 0                                    # размещённых взрослых НЕ тронул
