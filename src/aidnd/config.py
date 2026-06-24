"""Глобальная конфигурация движка.

Адрес Ollama и параметры запроса модели взяты из проекта ai-dnd (это
единственное, что переиспользуется оттуда). Остальные параметры — из
открытых решений основного диздока §8 и доков 06-09.
"""

from __future__ import annotations

import os

# --------------------------------------------------------------------------- #
#  Инференс. Запрос модели с сервера (механизм из ai-dnd/ollama_client.py).    #
# --------------------------------------------------------------------------- #
# Сервер Ollama обычно проброшен SSH-туннелем на localhost:
#   ssh -L 11434:localhost:11434 nikalutis@192.168.3.26
# поэтому по умолчанию ходим на localhost. Доступа к серверу пока нет —
# движок работает на детерминированных фоллбэках (док 08 §9), а при наличии
# сервера те же вызовы пойдут к модели.
OLLAMA_HOST: str = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# Базовая модель (открытое решение §8). По дизайну — Qwen3-8B / Qwen3.5-9B.
BASE_MODEL: str = os.environ.get("AIDND_MODEL", "qwen3.5:9b")
# Крошечная модель интент-парсера держится отдельно ради мгновенности (док 08 §3).
INTENT_MODEL: str = os.environ.get("AIDND_INTENT_MODEL", "qwen3.5:2b")
# Дообученный квест-генератор (LoRA на BASE_MODEL, смерджен и экспортирован в Ollama
# как aidnd-quest; 0%→85% валидных квестов на отложенной выборке, см. training/).
# Если модели нет на сервере — model_for() откатывается на BASE_MODEL.
QUEST_MODEL: str = os.environ.get("AIDND_QUEST_MODEL", "aidnd-quest")
# Дообученный роутер намерений (LoRA на BASE_MODEL → aidnd-router в Ollama;
# held-out kind 75%→92%, full 50%→71%, см. training/). Откат на BASE_MODEL, если нет.
ROUTER_MODEL: str = os.environ.get("AIDND_ROUTER_MODEL", "aidnd-router")
# Дообученный арбитр freeform-действий (decide_resolution → aidnd-arbiter в Ollama;
# held-out resolution 10%→83%, dc±2 100%, см. training/). Откат на BASE_MODEL, если нет.
ARBITER_MODEL: str = os.environ.get("AIDND_ARBITER_MODEL", "aidnd-arbiter")
# Дообученный агент последствий (world_effects → aidnd-consequence в Ollama;
# held-out valid-схема 47%→100%, full 43%→83%, см. training/). Откат на BASE_MODEL.
CONSEQUENCE_MODEL: str = os.environ.get("AIDND_CONSEQUENCE_MODEL", "aidnd-consequence")
# Дообученный нарратор (LoRA на BASE_MODEL → aidnd-narrator в Ollama; 522 примера
# проза по mode, before/after: канон-имена не коверкает, сухой живой стиль вместо
# наигранного, см. training/). Откат на BASE_MODEL, если модели нет.
NARRATOR_MODEL: str = os.environ.get("AIDND_NARRATOR_MODEL", "aidnd-narrator")

KEEP_ALIVE: str = os.environ.get("AIDND_KEEP_ALIVE", "30m")
HTTP_TIMEOUT: float = float(os.environ.get("AIDND_TIMEOUT", "300"))

# Режим reasoning у qwen3.x: тысячи скрытых токенов → +15-20 c. По умолчанию off.
THINK_DEFAULT: bool = os.environ.get("AIDND_THINK", "0") == "1"

# Нативные tool-calls Ollama. Маленькие модели ломаются → по умолчанию текстовый
# маркер-протокол. Включить для крупных моделей с надёжным function calling.
USE_NATIVE_TOOLS: bool = os.environ.get("AIDND_NATIVE_TOOLS", "0") == "1"

# Если сервер недоступен — не падать, а использовать детерминированные фоллбэки.
# Это позволяет всему движку работать end-to-end без модели.
LLM_REQUIRED: bool = os.environ.get("AIDND_LLM_REQUIRED", "0") == "1"

# --------------------------------------------------------------------------- #
#  Мир и детерминизм                                                           #
# --------------------------------------------------------------------------- #
WORLD_SEED: int = int(os.environ.get("AIDND_SEED", "1337"))
SAVE_DIR: str = os.environ.get("AIDND_SAVE_DIR", os.path.expanduser("~/.aidnd/save"))

# Язык нарратива (открытое решение §8). Системные промпты на английском для
# качества, язык вывода игроку — отдельный конфиг.
NARRATIVE_LANGUAGE: str = os.environ.get("AIDND_LANG", "ru")

# Режим доверия бросков (док 07 §8): trust | server_animated | manual_physical.
DICE_TRUST_MODE: str = os.environ.get("AIDND_DICE_MODE", "server_animated")

# --------------------------------------------------------------------------- #
#  LOD-симуляция (main §4.2)                                                   #
# --------------------------------------------------------------------------- #
TAU_HIGH: float = 0.7        # порог промоушна в L3 (с диалогом)
TAU_MID: float = 0.35        # порог L2
AOI_HOPS: int = 2            # окрестность интереса: переходы по графу локаций
MAX_L3_NPCS: int = 3         # кап дорогих когниций за тик (main §4.2)
DEMOTE_COOLDOWN_TICKS: int = 30  # гистерезис демоушна с L3

# Веса salience
W_DIST, W_ROLE, W_RECENT, W_ACTIVE = 0.4, 0.3, 0.2, 0.3

# Индекс важности места: накапливается при взаимодействии (визиты, осмотр интерьера).
# Достигнув порога, рядовое место (дом) повышается в ключевое и подписывается на карте.
PLACE_IMPORTANCE_KEY: int = 3

# Каталог сейвов (JSON). Загрузка = пре-ген из seed + реплей рантайм-хвоста.
SAVE_DIR: str = os.environ.get("AIDND_SAVE_DIR", os.path.expanduser("~/.aidnd/saves"))

# --------------------------------------------------------------------------- #
#  Время и окружение (док 08 §8)                                              #
# --------------------------------------------------------------------------- #
SIM_MINUTES_PER_TICK: int = 10
START_SEASON: str = os.environ.get("AIDND_SEASON", "autumn")  # стартовый сезон
DAYS_PER_SEASON: int = 28

# --------------------------------------------------------------------------- #
#  Память (main §5.2-5.3)                                                      #
# --------------------------------------------------------------------------- #
MEM_RECENCY_LAMBDA: float = 0.01   # спад recency
MEM_ALPHA, MEM_BETA, MEM_GAMMA = 1.0, 1.0, 1.0  # recency/importance/relevance
MEM_FORGET_TAU: float = 200.0
MEM_TOPK: int = 12

# Диффузия знаний: каждые DIFFUSE_EVERY тиков слух переходит к новым NPC (граф знаний)
DIFFUSE_EVERY: int = 6
DIFFUSE_MAX_PER_STEP: int = 3
