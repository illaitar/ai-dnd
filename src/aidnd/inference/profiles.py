"""Профили запуска: role → (backend, model). Выбор — config.LLM_PROFILE (env AIDND_PROFILE).

«local» генерится из ModelManager.ROLE_MODELS (текущее поведение, тюненое в Ollama). Здесь —
облачные/гибридные варианты. «default» применяется к ролям без явного маппинга."""

from __future__ import annotations

from .. import config
from .backends import OllamaBackend, OpenAICompatBackend

_DS = ("deepseek", config.DEEPSEEK_MODEL)            # ярлык: роль → DeepSeek

# роли, что остаются ЛОКАЛЬНЫМИ в hybrid (есть дообученный адаптер / латентность-критичны)
_LOCAL_TUNED = {
    "narrator": config.NARRATOR_MODEL, "location_writer": config.LOCATION_MODEL,
    "router": config.ROUTER_MODEL, "arbiter": config.ARBITER_MODEL,
    "consequence": config.CONSEQUENCE_MODEL, "quest_writer": config.QUEST_MODEL,
    "intent": config.INTENT_MODEL,
}

# мозги/лор/режиссура — в DeepSeek (недообученные, латентность-терпимые)
_DS_ROLES = ("cognition", "character_gen", "persona_gen", "faction_gen", "lore_keeper",
             "loremaster", "campaign_architect", "campaign_director", "event_director",
             "plausibility", "reflection", "director", "tactician", "merchant", "street_event")

PROFILES: dict[str, dict] = {
    "deepseek": {"default": _DS},
    "hybrid": {"default": ("ollama", config.BASE_MODEL),
               **{r: ("ollama", m) for r, m in _LOCAL_TUNED.items()},
               **{r: _DS for r in _DS_ROLES}},
}


def routing_for(profile_name: str, role_models: dict) -> dict:
    """role → (backend, model) для активного профиля. local строим из ROLE_MODELS."""
    if profile_name not in PROFILES:                 # local (или неизвестный → local)
        out = {"default": ("ollama", config.BASE_MODEL)}
        out.update({role: ("ollama", spec[0]) for role, spec in role_models.items()})
        return out
    return PROFILES[profile_name]


def make_backends(routing: dict, ollama_client=None) -> dict:
    """Поднять только бэкенды, которые реально использует профиль (по их именам в routing)."""
    used = {bk for bk, _ in routing.values()}
    out: dict = {}
    if "ollama" in used:
        out["ollama"] = OllamaBackend(ollama_client)
    if "deepseek" in used:
        out["deepseek"] = OpenAICompatBackend("deepseek", config.DEEPSEEK_BASE,
                                              config.DEEPSEEK_API_KEY, config.DEEPSEEK_MODEL)
    return out
