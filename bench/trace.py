"""Per-turn 4-face trace record + streaming JSONL writer (bench/).

Composes the three already-built bench/ pieces into one record per turn: the driver
(`bench.harness.Harness.act`), the backend reflector (`bench.snapshot.snapshot`), and the LLM
recorder (`bench.llmtap.llm_tap`). Each `record_turn` call opens its own `llm_tap()` scope around a
single `Harness.act` so the recorded `LLMCall`s belong to exactly that turn, not to whatever ran
before or after it. `TraceWriter` then serializes records to disk one line at a time (streaming,
flushed after every line) so a long `--full` run survives a crash with every turn up to that point
already durable on disk, instead of losing the whole run to an in-memory buffer.

Key functions
-------------
record_turn(h, endpoint, turn=None, **params) -> TurnRecord : drive one `h.act(endpoint, **params)`
    turn inside a fresh `llm_tap()`; bundle input/frontend/backend/llm into one dict.
TraceWriter(path) : `.append(rec)` writes one JSON line and flushes; `.close()` closes the file.
"""

from __future__ import annotations

import dataclasses
import itertools
import json
from pathlib import Path
from typing import Any

from bench.harness import Harness
from bench.llmtap import llm_tap
from bench.snapshot import snapshot

TurnRecord = dict[str, Any]

# Fallback turn counter shared across calls that don't pass an explicit `turn=` — keeps
# `record_turn(h, "look")` deterministic and simple to call in a loop without a caller-side counter.
_turn_counter = itertools.count()


def record_turn(h: Harness, endpoint: str, turn: int | None = None, **params) -> TurnRecord:
    """Drive one `h.act(endpoint, **params)` turn and capture all four faces of it.

    `input` is the request as sent; `frontend` is the decoded response body; `backend` is a full
    `snapshot()` taken right after the turn settles; `llm` is every `ModelManager.call` made while
    `h.act` ran, in call order. `turn` defaults to a private auto-incrementing counter so callers
    that don't care about numbering can just do `record_turn(h, "look")` in a loop.
    """
    if turn is None:
        turn = next(_turn_counter)
    with llm_tap() as calls:
        resp = h.act(endpoint, **params)
    return {
        "turn": turn,
        "input": {"endpoint": endpoint, "params": params},
        "frontend": resp.json(),
        "backend": snapshot(),
        "llm": [dataclasses.asdict(c) for c in calls],
    }


def _json_default(obj: Any) -> Any:
    """Best-effort fallback for `json.dumps` on values a trace record might contain.

    Covers the non-JSON-native shapes seen across bench/*'s data (dataclasses already handled by
    `record_turn` via `asdict`, but defends the writer against future fields too): sets/frozensets
    become lists, and anything else falls back to `str()` rather than raising mid-run.
    """
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    return str(obj)


class TraceWriter:
    """Streams `TurnRecord`s to a JSONL file, one flushed line per `.append`."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self._path.open("a", encoding="utf-8")

    def append(self, rec: TurnRecord) -> None:
        """Write one record as a single JSON line and flush it to disk immediately."""
        self._fh.write(json.dumps(rec, default=_json_default, ensure_ascii=False))
        self._fh.write("\n")
        self._fh.flush()

    def close(self) -> None:
        """Close the underlying file handle."""
        self._fh.close()
