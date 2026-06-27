"""Параллельный прогон ген-вызовов enrich — с сохранением порядка (детерминизм apply).

Модель-вызовы (network-bound для облака) гоняются в пуле; РЕЗУЛЬТАТЫ собираются строго в
порядке входа → вызывающий применяет их к миру последовательно (тот же порядок → тот же
event-лог → replay-устойчиво). На локальной Ollama concurrency=1 → обычный цикл."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any


def _safe(fn: Callable, item: Any) -> Any:
    try:
        return fn(item)
    except Exception:
        return None


def pmap(items: Sequence[Any], fn: Callable[[Any], Any], concurrency: int = 1,
         on_done: Callable[[int, Any], None] | None = None) -> list:
    """fn(item) для каждого элемента; результаты В ПОРЯДКЕ ВХОДА. concurrency≤1 → последовательно.
    on_done(done_count, item) — колбэк прогресса по мере завершения вызовов."""
    n = len(items)
    if n == 0:
        return []
    if concurrency <= 1:
        out = []
        for i, it in enumerate(items):
            out.append(_safe(fn, it))
            if on_done:
                on_done(i + 1, it)
        return out
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results: list = [None] * n
    with ThreadPoolExecutor(max_workers=min(concurrency, n)) as ex:
        futs = {ex.submit(_safe, fn, it): i for i, it in enumerate(items)}
        done = 0
        for fut in as_completed(futs):
            idx = futs[fut]
            results[idx] = fut.result()
            done += 1
            if on_done:
                on_done(done, items[idx])
    return results
