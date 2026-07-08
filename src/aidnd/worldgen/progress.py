"""Progress tracking for saturation. Unit of plan — BATCH: number of buildings divided by maximum
concurrent prompts. Progress = done/total buildings + current/total batches.

Key functions
-------------
Progress(total, max_concurrent, on_update, label) -> instance : Progress tracker for worldgen
  batches; computes done/total and current batch index out of batch count.
tick(n) -> dict : Mark n buildings completed, trigger on_update callback, return snapshot dict.
snapshot() -> dict : Return current state (phase, done/total, batch/batches_total, percentage)."""

from __future__ import annotations

import math


class Progress:
    def __init__(self, total: int, max_concurrent: int, on_update=None, label: str = ""):
        self.total = max(0, int(total))
        self.max_concurrent = max(1, int(max_concurrent))
        self.batches_total = math.ceil(self.total / self.max_concurrent) if self.total else 0
        self.done = 0
        self.batch = 0
        self.label = label                       # phase label (buildings / sub-locations)
        self.on_update = on_update

    def tick(self, n: int = 1) -> dict:
        """Mark n completed buildings."""
        self.done = min(self.total, self.done + n)
        self.batch = math.ceil(self.done / self.max_concurrent) if self.done else 0
        snap = self.snapshot()
        if self.on_update:
            try:
                self.on_update(snap)
            except Exception:  # noqa: BLE001 — progress must not crash generation
                pass
        return snap

    def snapshot(self) -> dict:
        return {"phase": self.label, "done": self.done, "total": self.total,
                "batch": self.batch, "batches_total": self.batches_total,
                "max_concurrent": self.max_concurrent,
                "pct": round(100.0 * self.done / self.total, 1) if self.total else 100.0}
