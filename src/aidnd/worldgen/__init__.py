"""Начальная генерация мира: насыщение локаций (слой поверх графа города) + БД миров.

Граф (aidnd.citygraph) — скелет; этот пакет — СЛОЙ НАСЫЩЕНИЯ (фактшит-характеристики через LLM),
отдельный от графа и от скрипта. Результат складывается в БД (WorldStore) под world_id для дешёвого
переиспользования. Хук генерации изображений — imagegen (на будущее).
"""

from __future__ import annotations

from .enrich_llm import BuildingCtx, Enricher, LLMEnricher, StubEnricher
from .enrichment import Building, Enrichment, building_ctx, enrich_city, store_world
from .imagegen import EMOTIONS, FluxImageGen, ImageGen, build_prompt, get_imagegen, portrait_prompt
from .persona_llm import LLMPersona, PersonaCtx, PersonaEnricher, StubPersona
from .progress import Progress
from .store import WorldStore

__all__ = ["enrich_city", "store_world", "building_ctx", "Enrichment", "Building",
           "Enricher", "LLMEnricher", "StubEnricher", "BuildingCtx", "Progress",
           "WorldStore", "ImageGen", "FluxImageGen", "get_imagegen", "build_prompt",
           "portrait_prompt", "EMOTIONS",
           "PersonaCtx", "PersonaEnricher", "LLMPersona", "StubPersona"]
