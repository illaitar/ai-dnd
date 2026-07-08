"""Records every LLM call made through `ModelManager.call` for the duration of a `with` block.

`ModelManager.on_call(role, model)` already fires per call but only carries the role/model name —
no prompt, no output, no timing — so it can't answer "what did the model actually see and say."
This module monkeypatches `ModelManager.call` itself (the class method, so it covers every
instance) for the lifetime of the context: each call is timed, its arguments and return value are
recorded into an `LLMCall`, and the real return value is passed straight back through unchanged —
callers inside the `with` block behave exactly as if untapped. The original `call` is restored on
exit, including when the block raises.

Key functions
-------------
LLMCall : dataclass — one recorded call: role, messages, raw (== parsed; call() returns a single
    already-decoded dict, so there is no separate parse step to distinguish — see class docstring).
llm_tap() -> contextmanager[list[LLMCall]] : monkeypatch ModelManager.call for the block; yields
    the (live, growing) list of LLMCall it records; restores the original call on exit.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from aidnd.inference.client import ModelManager


@dataclass
class LLMCall:
    """One recorded `ModelManager.call` invocation.

    `raw` and `parsed` are deliberately the same value: `ModelManager.call` returns a single
    already-decoded dict (`{"content", "tool_calls"}`), not a raw-response/parsed-result pair, so
    there is nothing further to distinguish. Both fields are kept (per the interface) so callers
    that only care about "the model's answer" can read whichever name reads better at the call
    site, and so a future backend that DOES separate raw transport output from a parsed structure
    can populate them differently without changing this dataclass's shape.
    """

    role: str
    messages: list
    raw: Any
    parsed: Any
    ms: float


@contextmanager
def llm_tap() -> Iterator[list[LLMCall]]:
    """Tap every `ModelManager.call` made inside this block.

    Monkeypatches the class attribute `ModelManager.call` (not an instance) so it covers every
    `ModelManager` instance created before or during the block. The wrapper times the real call,
    appends an `LLMCall`, and returns the real result unchanged — it never alters behavior or
    output. Restores the original `ModelManager.call` on exit, including on exception.
    """
    calls: list[LLMCall] = []
    original_call = ModelManager.call

    def _tapped(self: ModelManager, role: str, messages: list, **kwargs) -> dict:
        t0 = perf_counter()
        result = original_call(self, role, messages, **kwargs)
        ms = (perf_counter() - t0) * 1000
        calls.append(LLMCall(role=role, messages=messages, raw=result, parsed=result, ms=ms))
        return result

    ModelManager.call = _tapped
    try:
        yield calls
    finally:
        ModelManager.call = original_call
