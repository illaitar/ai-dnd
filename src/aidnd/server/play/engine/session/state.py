"""Session state machinery — the per-world session blob and its contextvar handle.

Key functions
-------------
_fresh_sess(wid, seed) -> dict : Build a fresh in-memory world session.
_SessProxy : Proxy so code can keep saying _S[...] while it resolves to the CURRENT world session.
_wid() -> int : World id of the current session.
current_world_id() : World ID of current request (for log tagging) or None outside play session.
"""

from __future__ import annotations

import contextvars

_SESS: dict = {}  # world_id → world session (in memory)
_CUR = contextvars.ContextVar("play_sess", default=None)
_UID = contextvars.ContextVar("play_uid", default=None)


def _fresh_sess(wid: int, seed: int) -> dict:
    return {
        "wid": wid,
        "seed": seed,
        "city": None,
        "people": None,
        "crof": None,
        "cr2b": None,
        "loc": None,
        "geom": None,
        "model": None,
    }


class _SessProxy:
    """Code still says _S[...] — behind it stands CURRENT world session (contextvar).
    Outside auth boundary (tests/dev) — shared world 1."""

    def _d(self) -> dict:
        d = _CUR.get()
        if d is None:
            d = _SESS.setdefault(1, _fresh_sess(1, 1))
            _CUR.set(d)
        return d

    def __getitem__(self, k):
        return self._d()[k]

    def __setitem__(self, k, v):
        self._d()[k] = v

    def __contains__(self, k):
        return k in self._d()

    def get(self, k, default=None):
        return self._d().get(k, default)

    def setdefault(self, k, default=None):
        return self._d().setdefault(k, default)

    def pop(self, k, default=None):
        return self._d().pop(k, default)

    def update(self, *a, **kw):
        self._d().update(*a, **kw)


_S = _SessProxy()


def _wid() -> int:
    return _S["wid"]


def current_world_id():
    """World ID of current request (for log tagging) or None outside play session."""
    s = _CUR.get()
    return s.get("wid") if s else None
