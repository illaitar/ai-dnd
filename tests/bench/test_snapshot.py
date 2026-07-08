# bench.snapshot reflects deep, read-only backend state over a benchmark world (bench/harness.py).
# It must work called directly after bench_world() (before any HTTP turn), loading/refreshing
# core._S via world._play() itself — see bench/snapshot.py docstring for the core._S-after-turn
# finding this relies on.
from bench.snapshot import snapshot

from bench.harness import bench_world


def test_snapshot_reads_economy_and_session():
    with bench_world(seed=7):
        snap = snapshot()
        assert snap["economy"]["money_supply"] > 0
        assert isinstance(snap["session"]["gt"], int)
