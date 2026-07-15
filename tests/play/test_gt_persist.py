"""Write-through game clock (bug: gt persisted LAZILY — only inside _pc_save(), which fires on
combat/magic/sleep/misc paths only). Cold start (session/time.py `_gt()`) reads pc_state.gt, so a
server restart / _SESS eviction between saves rewound world time to the last snapshot. Fix: every
`_gt_add`/`_gt_set` call now writes the gt straight into the pc_state row (targeted UPDATE via
`store.pc_set_gt`), so a cold read always sees the latest advance."""

import os
import tempfile

import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


@pytest.fixture
def world(monkeypatch):
    store = WorldStore(os.path.join(tempfile.mkdtemp(), "live.db"))
    monkeypatch.setattr(persist, "_STORE", store)
    saved = dict(core._S._d())
    try:
        core._S["city"] = None
        core._S["gt"] = 8 * 60
        yield store
    finally:
        d = core._S._d()
        d.clear()
        d.update(saved)


def test_gt_add_persists_to_row(world):
    """(a) unit: _gt_add() writes gt into pc_state, not just memory."""
    before = core._gt()
    core._gt_add(5)
    row = world.get_pc(core._wid()) or {}
    assert row.get("gt") == before + 5 == core._S["gt"]


def test_cold_start_reads_advanced_gt_not_stale_snapshot(world):
    """(b) the rewind regression, red-then-green: advance gt several times in memory (as a normal
    play session would across many actions), THEN simulate a cold start — clear the in-memory 'gt'
    key so `_gt()` must fall back to the persisted row. Before the fix, this returned the stale
    value frozen at the last `_pc_save()`; after the fix it returns the fully advanced value."""
    core._gt_add(10)
    core._gt_add(20)
    core._gt_add(30)                      # memory gt now 8*60 + 60, never touched by _pc_save()
    advanced = core._S["gt"]
    core._S._d().pop("gt", None)          # simulate cold start / _SESS eviction
    assert core._gt() == advanced         # NOT the stale pc_state row from a lazy save


def test_sleep_path_persists_wake_time(world):
    """(c) freeform rest sets `_S["gt"] = wake` directly (bypassing _gt_add) — now routed through
    `_gt_set`, so the wake time lands in the row too."""
    from aidnd.server.play.engine.session.time import _gt_set

    wake = 2 * 1440 + 7 * 60
    _gt_set(wake)
    row = world.get_pc(core._wid()) or {}
    assert row.get("gt") == wake
