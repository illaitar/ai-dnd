"""Подсчёт прогресса насыщения. Единица плана — БАТЧ: число зданий, делённое на максимум
одновременных промптов. Прогресс = сделано/всего зданий + текущий/всего батчей."""

from __future__ import annotations

import math


class Progress:
    def __init__(self, total: int, max_concurrent: int, on_update=None, label: str = ""):
        self.total = max(0, int(total))
        self.max_concurrent = max(1, int(max_concurrent))
        self.batches_total = math.ceil(self.total / self.max_concurrent) if self.total else 0
        self.done = 0
        self.batch = 0
        self.label = label                       # метка фазы (здания / суб-помещения)
        self.on_update = on_update

    def tick(self, n: int = 1) -> dict:
        """Отметить n завершённых зданий."""
        self.done = min(self.total, self.done + n)
        self.batch = math.ceil(self.done / self.max_concurrent) if self.done else 0
        snap = self.snapshot()
        if self.on_update:
            try:
                self.on_update(snap)
            except Exception:  # noqa: BLE001 — прогресс не должен валить генерацию
                pass
        return snap

    def snapshot(self) -> dict:
        return {"phase": self.label, "done": self.done, "total": self.total,
                "batch": self.batch, "batches_total": self.batches_total,
                "max_concurrent": self.max_concurrent,
                "pct": round(100.0 * self.done / self.total, 1) if self.total else 100.0}
