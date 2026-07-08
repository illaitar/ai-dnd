"""Initial world generation: location enrichment (layer over city graph) + world DB.

Graph (aidnd.citygraph) — skeleton; this package — ENRICHMENT LAYER (fact-sheet characteristics via LLM),
separate from graph and from script. Result is stored in DB (WorldStore) under world_id for cheap
reuse. Image generation hook — imagegen (for future).

Key functions
-------------
enrich_city() : Enrich all locations in city graph with LLM-generated details.
store_world() : Persist enriched world data to database under world_id.
Enrichment : Result model holding enriched building/location details.
Enricher : Base class for location enrichment strategies (LLM or stub).
WorldStore : Database interface for persisting and retrieving world data.
ImageGen : Interface for generating and managing entity portraits/images.
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
