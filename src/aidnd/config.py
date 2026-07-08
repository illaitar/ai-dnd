"""Global engine configuration.

Ollama address and model request parameters are taken from the ai-dnd project
(the only thing reused from there). Other parameters are from open solutions in
the main design doc §8 and docs 06-09.
"""

from __future__ import annotations

import os

# --------------------------------------------------------------------------- #
#  Inference. Model request from server (mechanism from ai-dnd/ollama_client.py). #
# --------------------------------------------------------------------------- #
# Ollama server is typically tunneled via SSH to localhost:
#   ssh -L 11434:localhost:11434 nikalutis@192.168.3.26
# so by default we connect to localhost. Prod runs on the deepseek profile.
# Project rule: the engine does NOT work without LLM (no model → LLMUnavailable).
OLLAMA_HOST: str = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# Base model (open solution §8). Design choice: Qwen3-8B / Qwen3.5-9B.
BASE_MODEL: str = os.environ.get("AIDND_MODEL", "qwen3.5:9b")
# Tiny intent-parser model kept separate for speed (doc 08 §3).
INTENT_MODEL: str = os.environ.get("AIDND_INTENT_MODEL", "qwen3.5:2b")
# Fine-tuned quest generator (LoRA on BASE_MODEL, merged and exported to Ollama
# as aidnd-quest; 0%→85% valid quests on held-out sample, see training/).
# If model not on server — model_for() falls back to BASE_MODEL.
QUEST_MODEL: str = os.environ.get("AIDND_QUEST_MODEL", "aidnd-quest")
# Fine-tuned intent router (LoRA on BASE_MODEL → aidnd-router in Ollama;
# held-out kind 75%→92%, full 50%→71%, see training/). Falls back to BASE_MODEL if missing.
ROUTER_MODEL: str = os.environ.get("AIDND_ROUTER_MODEL", "aidnd-router")
# Fine-tuned arbiter for freeform actions (decide_resolution → aidnd-arbiter in Ollama;
# held-out resolution 10%→83%, dc±2 100%, see training/). Falls back to BASE_MODEL if missing.
ARBITER_MODEL: str = os.environ.get("AIDND_ARBITER_MODEL", "aidnd-arbiter")
# Fine-tuned consequence agent (world_effects → aidnd-consequence in Ollama;
# held-out valid-schema 47%→100%, full 43%→83%, see training/). Falls back to BASE_MODEL.
CONSEQUENCE_MODEL: str = os.environ.get("AIDND_CONSEQUENCE_MODEL", "aidnd-consequence")
# Fine-tuned narrator (LoRA on BASE_MODEL → aidnd-narrator in Ollama; 522 samples
# of prose by mode, before/after: canon names not mangled, dry live style instead of
# theatrical, see training/). Falls back to BASE_MODEL if model missing.
NARRATOR_MODEL: str = os.environ.get("AIDND_NARRATOR_MODEL", "aidnd-narrator")
# Location description generator (separate LoRA on 14B → aidnd-location in Ollama; 14B performs best
# at descriptions, see training/). Before training, falls back to bare qwen3:14b (also best base for descriptions).
LOCATION_MODEL: str = os.environ.get("AIDND_LOCATION_MODEL", "qwen3:14b")

# --- launch profile: which backend/model for which role (see inference/profiles.py) ---
# local (default, tuned in Ollama) | deepseek (all in DeepSeek) | hybrid (brains in DeepSeek)
LLM_PROFILE: str = os.environ.get("AIDND_PROFILE", "local")
DEEPSEEK_API_KEY: str = os.environ.get("DEEPSEEK_API_KEY", "")
if not DEEPSEEK_API_KEY:                # dev convenience: key from .secrets if env empty
    _KEY_PATH = os.path.join(os.path.dirname(__file__), "..", "..", ".secrets", "deepseek.key")
    if os.path.exists(_KEY_PATH):
        with open(_KEY_PATH, encoding="utf-8") as _f:
            DEEPSEEK_API_KEY = _f.read().strip()
DEEPSEEK_BASE: str = os.environ.get("DEEPSEEK_BASE", "https://api.deepseek.com")
DEEPSEEK_MODEL: str = os.environ.get("AIDND_DEEPSEEK_MODEL", "deepseek-chat")
# enrich parallelism: cloud (network-bound) parallelized, local Ollama not (swap on 1 GPU)
DEEPSEEK_CONCURRENCY: int = int(os.environ.get("AIDND_DEEPSEEK_CONCURRENCY", "8"))
# live-scene NPC decisions run concurrently (network-bound LLM calls, no client lock). Raise for a
# busier scene, bounded by the LLM provider's rate/concurrency limit (too high → 429s).
LIVE_CONCURRENCY: int = int(os.environ.get("AIDND_LIVE_CONCURRENCY", "16"))

# --- service: user/session/game DB (Postgres, async) + auth ---
DATABASE_URL: str = os.environ.get("AIDND_DATABASE_URL", "postgresql+asyncpg://localhost/aidnd_dev")
SESSION_TTL_DAYS: int = int(os.environ.get("AIDND_SESSION_TTL_DAYS", "30"))
COOKIE_SECURE: bool = os.environ.get("AIDND_COOKIE_SECURE", "0") == "1"   # Secure cookie (HTTPS only, behind TLS)
FREE_ENRICH: int = int(os.environ.get("AIDND_FREE_ENRICH", "1"))       # free world generations
FREE_REQUESTS: int = int(os.environ.get("AIDND_FREE_REQUESTS", "100"))  # free game requests
DAILY_LLM: int = int(os.environ.get("AIDND_DAILY_LLM", "300"))          # LLM calls per day without code
GOOGLE_CLIENT_ID: str = os.environ.get("AIDND_GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET: str = os.environ.get("AIDND_GOOGLE_CLIENT_SECRET", "")

KEEP_ALIVE: str = os.environ.get("AIDND_KEEP_ALIVE", "30m")
HTTP_TIMEOUT: float = float(os.environ.get("AIDND_TIMEOUT", "300"))

# Reasoning mode in qwen3.x: thousands of hidden tokens → +15-20 sec. Default off.
THINK_DEFAULT: bool = os.environ.get("AIDND_THINK", "0") == "1"

# Native Ollama tool-calls. Small models break → default is text
# marker protocol. Enable for large models with reliable function calling.
USE_NATIVE_TOOLS: bool = os.environ.get("AIDND_NATIVE_TOOLS", "0") == "1"

# --------------------------------------------------------------------------- #
#  World and determinism                                                        #
# --------------------------------------------------------------------------- #
WORLD_SEED: int = int(os.environ.get("AIDND_SEED", "1337"))
SAVE_DIR: str = os.environ.get("AIDND_SAVE_DIR", os.path.expanduser("~/.aidnd/save"))

# Narrative language (open solution §8). System prompts in English for
# quality; output language to player is a separate config.
NARRATIVE_LANGUAGE: str = os.environ.get("AIDND_LANG", "ru")

# Dice trust mode (doc 07 §8): trust | server_animated | manual_physical.
DICE_TRUST_MODE: str = os.environ.get("AIDND_DICE_MODE", "server_animated")

# --------------------------------------------------------------------------- #
#  LOD simulation (main §4.2)                                                   #
# --------------------------------------------------------------------------- #
TAU_HIGH: float = 0.7        # promotion threshold to L3 (with dialogue)
TAU_MID: float = 0.35        # L2 threshold
AOI_HOPS: int = 2            # area of interest: location graph hops
MAX_L3_NPCS: int = 3         # cap of expensive cognitions per tick (main §4.2)
DEMOTE_COOLDOWN_TICKS: int = 30  # hysteresis for demotion from L3

# Salience weights
W_DIST, W_ROLE, W_RECENT, W_ACTIVE = 0.4, 0.3, 0.2, 0.3

# Place importance index: accumulates on interaction (visits, interior inspection).
# Upon reaching threshold, ordinary place (house) promoted to key and labeled on map.
PLACE_IMPORTANCE_KEY: int = 3

# Save directory (JSON). Loading = pre-gen from seed + replay runtime tail.
SAVE_DIR: str = os.environ.get("AIDND_SAVE_DIR", os.path.expanduser("~/.aidnd/saves"))

# --------------------------------------------------------------------------- #
#  Time and environment (doc 08 §8)                                            #
# --------------------------------------------------------------------------- #
SIM_MINUTES_PER_TICK: int = 10
START_HOUR: int = 9             # start hour for new game (morning — shops open, not dead night)
START_SEASON: str = os.environ.get("AIDND_SEASON", "autumn")  # starting season
DAYS_PER_SEASON: int = 28

# --------------------------------------------------------------------------- #
#  Memory (main §5.2-5.3)                                                      #
# --------------------------------------------------------------------------- #
MEM_RECENCY_LAMBDA: float = 0.01   # recency decay
MEM_ALPHA, MEM_BETA, MEM_GAMMA = 1.0, 1.0, 1.0  # recency/importance/relevance
MEM_FORGET_TAU: float = 200.0
MEM_TOPK: int = 12

# Knowledge diffusion: every DIFFUSE_EVERY ticks rumor spreads to new NPCs (knowledge graph)
DIFFUSE_EVERY: int = 6
DIFFUSE_MAX_PER_STEP: int = 3
