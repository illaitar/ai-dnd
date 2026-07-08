"""Profiles: role → (backend, model). Selection via config.LLM_PROFILE (env AIDND_PROFILE).

«local» is generated from ModelManager.ROLE_MODELS (current behavior, tuned in Ollama). Here —
cloud/hybrid options. «default» applies to roles without explicit mapping.

Key functions
-------------
routing_for(profile_name, role_models) -> dict : Select LLM backend routing for a profile.
make_backends(routing, ollama_client=None) -> dict : Instantiate backend client objects for routing.
"""

from __future__ import annotations

from .. import config
from .backends import OllamaBackend, OpenAICompatBackend

_DS = ("deepseek", config.DEEPSEEK_MODEL)            # tag: role → DeepSeek

# roles that remain LOCAL in hybrid (have fine-tuned adapter / latency-critical)
_LOCAL_TUNED = {
    "narrator": config.NARRATOR_MODEL, "location_writer": config.LOCATION_MODEL,
    "router": config.ROUTER_MODEL, "arbiter": config.ARBITER_MODEL,
    "consequence": config.CONSEQUENCE_MODEL, "quest_writer": config.QUEST_MODEL,
    "intent": config.INTENT_MODEL,
}

# minds/lore/direction — to DeepSeek (not fine-tuned, latency-tolerant)
_DS_ROLES = ("cognition", "character_gen", "persona_gen", "faction_gen", "lore_keeper",
             "loremaster", "campaign_architect", "campaign_director", "event_director",
             "plausibility", "reflection", "director", "tactician", "merchant", "street_event",
             "quest_merge", "event_quest", "map_features", "npc_ref", "agenda", "event_batch",
             "spell_scribe", "wild_magic")

PROFILES: dict[str, dict] = {
    "deepseek": {"default": _DS},
    "hybrid": {"default": ("ollama", config.BASE_MODEL),
               **{r: ("ollama", m) for r, m in _LOCAL_TUNED.items()},
               **{r: _DS for r in _DS_ROLES}},
}


def routing_for(profile_name: str, role_models: dict) -> dict:
    """role → (backend, model) for the active profile. local built from ROLE_MODELS."""
    if profile_name not in PROFILES:                 # local (or unknown → local)
        out = {"default": ("ollama", config.BASE_MODEL)}
        out.update({role: ("ollama", spec[0]) for role, spec in role_models.items()})
        return out
    return PROFILES[profile_name]


def make_backends(routing: dict, ollama_client=None) -> dict:
    """Instantiate only backends actually used by the profile (by their names in routing)."""
    used = {bk for bk, _ in routing.values()}
    out: dict = {}
    if "ollama" in used:
        out["ollama"] = OllamaBackend(ollama_client)
    if "deepseek" in used:
        out["deepseek"] = OpenAICompatBackend("deepseek", config.DEEPSEEK_BASE,
                                              config.DEEPSEEK_API_KEY, config.DEEPSEEK_MODEL)
    return out
