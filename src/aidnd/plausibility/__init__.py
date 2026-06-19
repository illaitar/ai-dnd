"""Plausibility — мягкий вероятностный гейт появления (док 06)."""

from .model import (
    K_CATEGORY,
    Candidate,
    SpawnContext,
    check,
    discover,
    feasible,
    plausibility,
    sample,
)

__all__ = [
    "SpawnContext", "Candidate", "plausibility", "sample", "check", "discover",
    "feasible", "K_CATEGORY",
]
