"""Detailed log of the CURRENT session to a file (data/debug/play.log) — for debugging. Write ALL
to DEBUG (loggers aidnd/uvicorn/…) + FULL tracebacks of unhandled exceptions (via middleware in app).
Each record is tagged with world id. Downloaded/cleared via /api/play/debuglog. Noisy third-party
DEBUG (httpx/asyncio/…) suppressed to INFO.

Key functions
-------------
setup(wid_getter=None) -> str : Initialize file logging with world ID tracking.
read_log(tail_bytes: int | None = None) -> str : Read session debug log, optionally tail N bytes.
clear_log() -> None : Clear the debug log file.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "debug"))
LOG_PATH = os.path.join(_DIR, "play.log")

_configured = False
_wid_getter = lambda: None                                 # noqa: E731 — will be reset in setup()


class _WorldFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.world = _wid_getter()
        except Exception:                                  # noqa: BLE001 — tag must not crash the log
            record.world = None
        record.world = record.world if record.world is not None else "-"
        return True


def setup(wid_getter=None) -> str:
    """Initialize file logging (idempotent). wid_getter — how to get the current request's world id."""
    global _configured, _wid_getter
    if wid_getter:
        _wid_getter = wid_getter
    if _configured:
        return LOG_PATH
    os.makedirs(_DIR, exist_ok=True)
    h = RotatingFileHandler(LOG_PATH, maxBytes=4_000_000, backupCount=1, encoding="utf-8")
    h.setLevel(logging.DEBUG)
    h.addFilter(_WorldFilter())
    h.setFormatter(logging.Formatter("%(asctime)s [w%(world)s] %(levelname)s %(name)s: %(message)s",
                                     "%H:%M:%S"))
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(h)
    for noisy in ("httpx", "httpcore", "asyncio", "urllib3", "multipart", "aiosqlite",
                  "watchfiles", "PIL"):
        logging.getLogger(noisy).setLevel(logging.INFO)
    _configured = True
    logging.getLogger("aidnd").info("=== старт файлового лога сессии (%s) ===", LOG_PATH)
    return LOG_PATH


def read_log(tail_bytes: int | None = None) -> str:
    try:
        with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
            if tail_bytes:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - tail_bytes))
            return f.read()
    except FileNotFoundError:
        return ""


def clear_log() -> None:
    try:
        open(LOG_PATH, "w").close()
        logging.getLogger("aidnd").info("=== лог очищен из интерфейса ===")
    except OSError:
        pass
