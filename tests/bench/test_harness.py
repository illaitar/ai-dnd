# Spike: /api/play/scene is a FastAPI dependency (`core._play_session`) that resolves the world
# from a cookie → user → world id, with an AIDND_OPEN_PLAY escape hatch that pins everyone to a
# shared "world 1" without login (see server/app.py:play_page and engine/core.py:_play_session).
# bench_world() sets that env var, points core._STORE at a fresh temp live.db, and pre-seeds
# core._SESS[1] with a fresh session (city=None, seed=seed) so the FIRST /scene request builds a
# brand-new city deterministically from `seed` instead of reusing a stale in-process world.
from bench.harness import bench_world


def test_scene_reachable_over_http():
    with bench_world(seed=7) as h:
        r = h.act("scene")            # GET /api/play/scene
        assert r.status_code == 200
        body = r.json()
        assert "location" in body and "here" in body   # scene dict shape
