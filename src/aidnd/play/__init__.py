"""Гринфилд-контур игрока на новом стеке: mind (мозги NPC) + citygraph (карта) + worldgen
(знание/локации). Никакого Фэндалина и старого движка — всё генерится обобщённо."""

from __future__ import annotations

from .population import Townsperson, populate

__all__ = ["Townsperson", "populate"]
