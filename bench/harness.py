"""Fresh seeded world over real HTTP, for the benchmark harness (bench/).

`/api/play/*` resolves its world through a FastAPI dependency (`core._play_session`) that maps
cookie → user → world id, with an `AIDND_OPEN_PLAY` escape hatch that pins every unauthenticated
caller to a shared "world 1". This module flips that hatch, points the runtime store at a throwaway
temp `live.db`, and pre-seeds the world-1 session so the FIRST request builds a brand-new city
deterministically from the given seed — never touching game behavior, only how a test reaches it.

Key functions
-------------
bench_world(seed: int) -> AbstractContextManager[Harness] : spin up an isolated, seeded world and
    a TestClient bound to it; tears down store/env/session state on exit.
Harness.act(endpoint, **params) -> httpx.Response : call /api/play/<endpoint> with the right verb.
Harness.scene() -> dict : GET /api/play/scene, decoded JSON (convenience wrapper over act()).
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from aidnd.server.app import app
from aidnd.server.play.engine import core
from aidnd.worldgen import WorldStore

# /api/play/* endpoints that are GET (everything else in the real registry is POST — see
# engine/world.py + handlers/*.py route decorators).
_GET_ROUTES = frozenset({
    "scene", "contracts", "board", "debuglog", "deeds", "dungeon", "economy",
    "glyphs", "grimoire", "inventory", "map", "market", "plan", "schedule", "teachers", "wares",
})


@dataclass
class Harness:
    """A seeded world reachable over HTTP: `client` is a live TestClient(app) bound to it."""

    client: TestClient
    store: WorldStore
    seed: int

    def act(self, endpoint: str, **params) -> httpx.Response:
        """Call /api/play/<endpoint>: GET with query params, or POST with a JSON body."""
        path = f"/api/play/{endpoint}"
        if endpoint in _GET_ROUTES:
            return self.client.get(path, params=params or None)
        return self.client.post(path, json=params or None)

    def scene(self) -> dict:
        """GET /api/play/scene, decoded — raises if the server didn't return 200."""
        r = self.act("scene")
        r.raise_for_status()
        return r.json()


@contextmanager
def bench_world(seed: int) -> Iterator[Harness]:
    """Isolated, seeded world driven over TestClient(app) via the open-play auth bypass.

    Builds a temp live.db, patches core._STORE onto it, and force-seeds core._SESS[1] with a
    fresh session (city=None) so `_play()` rebuilds the whole city from `seed` on the first
    request instead of reusing whatever "world 1" happened to be cached in this process (_SESS
    is a module-global dict that otherwise survives across bench_world calls/tests).
    """
    tmpdir = tempfile.mkdtemp(prefix="bench_world_")
    store = WorldStore(os.path.join(tmpdir, "live.db"))
    prev_sess1 = core._SESS.get(1)
    core._SESS[1] = core._fresh_sess(1, seed)
    client = TestClient(app)
    try:
        with (
            patch.object(core, "_STORE", store),
            patch.dict(os.environ, {"AIDND_OPEN_PLAY": "1"}),
        ):
            yield Harness(client=client, store=store, seed=seed)
    finally:
        client.close()
        if prev_sess1 is not None:
            core._SESS[1] = prev_sess1
        else:
            core._SESS.pop(1, None)
        shutil.rmtree(tmpdir, ignore_errors=True)
