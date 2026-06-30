"""Начальная генерация мира: насыщение локаций (слой поверх графа города).

Граф (aidnd.citygraph) — скелет; этот пакет — СЛОЙ НАСЫЩЕНИЯ (контент через LLM), отдельный
от графа и от скрипта. Публично:
    from aidnd.worldgen import enrich_city, Enrichment, LLMEnricher, StubEnricher, Progress
"""

from __future__ import annotations

from .enrich_llm import BuildingCtx, Enricher, LLMEnricher, StubEnricher
from .enrichment import Building, Enrichment, enrich_city
from .progress import Progress

__all__ = ["enrich_city", "Enrichment", "Building", "Enricher", "LLMEnricher",
           "StubEnricher", "BuildingCtx", "Progress"]
