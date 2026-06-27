"""Клиент к серверу модели (Ollama HTTP API).

ЕДИНСТВЕННЫЙ компонент, переиспользованный из проекта ai-dnd: механизм запроса
модели с сервера (стриминг /api/chat, tool-calls, think, keep_alive, preload,
list_models). Сервер обычно проброшен SSH-туннелем на localhost:11434.

Доступа к серверу сейчас нет — поэтому весь движок работает на детерминированных
фоллбэках. Когда сервер появится, ModelManager.available() станет True и те же
вызовы пойдут к модели (multi-LoRA маршрутизация по ролям, main §6.2-6.4).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from time import perf_counter as _perf_counter

from .. import config

try:                                # httpx нужен только при наличии сервера
    import httpx
    _HAS_HTTPX = True
except ModuleNotFoundError:         # офлайн-режим: весь движок на фоллбэках
    httpx = None                    # type: ignore
    _HAS_HTTPX = False


class OllamaError(Exception):
    """Любая проблема при общении с сервером Ollama (или httpx не установлен)."""


def is_offline(manager) -> bool:
    """True, если модель-менеджер отсутствует или сервер недоступен → берём детерминированный
    фоллбэк. Единый guard для всех агентов/оркестратора (вместо повтора проверки на местах)."""
    return manager is None or not manager.available()


class OllamaClient:
    def __init__(self, host: str | None = None, timeout: float | None = None,
                 keep_alive: str | None = None) -> None:
        self.host = (host or config.OLLAMA_HOST).rstrip("/")
        self._timeout = timeout or config.HTTP_TIMEOUT
        self.keep_alive = keep_alive or config.KEEP_ALIVE

    def preload(self, model: str) -> float:
        """Загружает модель в VRAM заранее. Возвращает время загрузки (сек)."""
        import time
        t0 = time.monotonic()
        try:
            resp = httpx.post(
                f"{self.host}/api/generate",
                json={"model": model, "keep_alive": self.keep_alive},
                timeout=self._timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaError(str(exc)) from exc
        return time.monotonic() - t0

    def list_models(self) -> list[str]:
        """Список установленных моделей (GET /api/tags)."""
        try:
            resp = httpx.get(f"{self.host}/api/tags", timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise OllamaError(str(exc)) from exc
        return [m["name"] for m in data.get("models", [])]

    def chat_stream(
        self, model: str, messages: list[dict], on_token: Callable[[str], None],
        think: bool = False, on_think: Callable[[str], None] | None = None,
        tools: list[dict] | None = None, fmt: dict | None = None,
        options: dict | None = None,
    ) -> dict:
        """Стримит ответ модели; вызывает on_token(piece).

        Возвращает {"content": str, "tool_calls": list}. Если think=True, токены
        размышления идут в on_think. tools — нативные function-calls. fmt — JSON
        Schema для structured output (грамматико-ограниченный декодинг Ollama,
        аналог guided_json/XGrammar, main §6.3): гарантирует валидный JSON и enum.
        """
        payload: dict = {
            "model": model, "messages": messages, "stream": True,
            "keep_alive": self.keep_alive, "think": think,
        }
        if tools:
            payload["tools"] = tools
        if fmt:
            payload["format"] = fmt
        if options:
            payload["options"] = options    # напр. {"temperature": 0} для классификации
        full: list[str] = []
        tool_calls: list[dict] = []
        try:
            with httpx.Client(timeout=self._timeout) as client:
                with client.stream("POST", f"{self.host}/api/chat", json=payload) as r:
                    r.raise_for_status()
                    for line in r.iter_lines():
                        if not line.strip():
                            continue
                        chunk = json.loads(line)
                        if chunk.get("error"):
                            raise OllamaError(chunk["error"])
                        msg = chunk.get("message", {})
                        thinking = msg.get("thinking")
                        if thinking and on_think:
                            on_think(thinking)
                        for tc in msg.get("tool_calls") or []:
                            tool_calls.append(tc)
                        piece = msg.get("content", "")
                        if piece:
                            full.append(piece)
                            on_token(piece)
                        if chunk.get("done"):
                            break
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise OllamaError(str(exc)) from exc
        return {"content": "".join(full), "tool_calls": tool_calls}

    def chat(self, model: str, messages: list[dict], tools: list[dict] | None = None,
             think: bool = False, fmt: dict | None = None, options: dict | None = None) -> dict:
        """Не-стриминговая обёртка: собирает полный ответ."""
        return self.chat_stream(model, messages, on_token=lambda _p: None,
                                think=think, tools=tools, fmt=fmt, options=options)


class ModelManager:
    """Маршрутизатор вызовов по ролям и менеджер режимов памяти (main §6.2-6.4).

    Один резидентный base + горячая подмена LoRA-адаптеров на роль (концептуально;
    в Ollama — выбор модели/адаптера по имени). Держит флаг доступности сервера:
    если сервер недоступен, агенты используют детерминированные фоллбэки.
    """

    # роль -> (модель, опциональный LoRA-адаптер) — main §12
    ROLE_MODELS = {
        "intent": (config.BASE_MODEL, None),    # legacy verb-классификатор (офлайн-путь)
        "router": (config.ROUTER_MODEL, "router"),  # дообученный роутер намерений (см. training/)
        "arbiter": (config.ARBITER_MODEL, "arbiter"),  # дообученный арбитр freeform (decide_resolution)
        "consequence": (config.CONSEQUENCE_MODEL, "consequence"),  # дообученный агент последствий
        "narrator": (config.NARRATOR_MODEL, "narrator-persona"),  # дообученный нарратор (см. training/)
        "location_writer": (config.LOCATION_MODEL, "location"),  # отдельный адаптер описаний мест на 14B (aidnd-location)
        "cognition": (config.BASE_MODEL, "lore"),
        "lore_keeper": (config.BASE_MODEL, "lore"),
        "character_gen": (config.BASE_MODEL, "lore"),
        "persona_gen": (config.BASE_MODEL, "lore"),  # генератор богатых персон (datasets/persona)
        "tactician": (config.BASE_MODEL, "combat"),
        "reflection": (config.BASE_MODEL, "reflect"),
        "director": (config.BASE_MODEL, None),
        "quest_writer": (config.QUEST_MODEL, "quest"),   # дообученная модель (см. training/)
        "plausibility": (config.BASE_MODEL, "validator"),
        "merchant": (config.BASE_MODEL, "lore"),         # торговец: социальный исход торга (числа — движок)
        "street_event": (config.BASE_MODEL, "lore"),     # случайное уличное событие в пути (контент)
        "event_batch": (config.BASE_MODEL, "lore"),      # пред-генерация пула событий пачками (контент)
        "quest_merge": (config.BASE_MODEL, "lore"),       # судья слияния близких объявлений
        "event_quest": (config.BASE_MODEL, "lore"),       # уличная сценка → зацепка-объявление
        "map_features": (config.BASE_MODEL, "lore"),      # описание локации → фичи боевой карты
        "faction_gen": (config.BASE_MODEL, "lore"),
        "npc_ref": (config.INTENT_MODEL, None),           # лёгкая резолюция ссылки на присутствующего NPC
        "agenda": (config.BASE_MODEL, "lore"),            # тайный замысел/план важного деятельного NPC
    }

    def __init__(self, client: OllamaClient | None = None) -> None:
        from . import profiles
        self.routing = profiles.routing_for(config.LLM_PROFILE, self.ROLE_MODELS)  # role→(backend,model)
        self.backends = profiles.make_backends(self.routing, client)
        ob = self.backends.get("ollama")
        self.client = ob.client if ob else None          # compat (тесты/стрим могут дернуть)
        self._available: bool | None = None
        self._trace: list[dict] = []        # дебаг-трейс роутинга: какие роли→модели дёргались за ход
        self.on_call = None                 # колбэк(role, model) на каждый LLM-вызов (для ползунка генерации)

    def available(self, recheck: bool = False) -> bool:
        """Доступен ли хоть один бэкенд активного профиля (кешируется). Иначе — фоллбэки.
        ВАЖНО: чек всех бэкендов (не short-circuit) — иначе Ollama не наполнит список моделей."""
        if not _HAS_HTTPX or not self.backends:
            return False
        if self._available is None or recheck:
            self._available = any([b.available() for b in self.backends.values()])
        return self._available

    def _route(self, role: str):
        backend_name, model = self.routing.get(role) or self.routing["default"]
        backend = self.backends.get(backend_name)
        return backend, (backend.resolve(model) if backend else model)

    def model_for(self, role: str) -> str:
        """Имя модели для роли в активном профиле (compat-хелпер; трейс/on_call — в call())."""
        return self._route(role)[1]

    def backend_name(self, role: str) -> str | None:
        """Имя бэкенда роли в активном профиле (для выбора бэкенд-специфичного промпта)."""
        b = self._route(role)[0]
        return b.name if b else None

    def enrich_concurrency(self) -> int:
        """Сколько ген-вызовов enrich гнать параллельно. Облако (network-bound) — параллелим;
        локальная Ollama (своп моделей на 1 GPU) — последовательно. Берём минимум по бэкендам
        ключевых ген-ролей (чтобы не зашлюзовать локальный путь)."""
        roles = ("persona_gen", "location_writer", "faction_gen", "item_smith")
        caps = [getattr(b, "parallel_enrich", 1)
                for b in (self._route(r)[0] for r in roles) if b is not None]
        return max(1, min(caps)) if caps else 1

    def call(self, role: str, messages: list, *, schema=None, options=None,
             on_token=None, think: bool = False) -> dict | None:
        """ЕДИНАЯ точка вызова модели по роли: профиль → (backend, model) → backend.chat.
        Возвращает {'content', 'tool_calls'} или None (бэкенд недоступен/ошибся → фоллбэк)."""
        backend, model = self._route(role)
        if backend is None:
            return None
        self._trace.append({"role": role, "model": model, "t": _perf_counter()})
        if len(self._trace) > 200:
            self._trace = self._trace[-100:]
        if self.on_call is not None:                     # двигаем ползунок генерации на каждый вызов
            try:
                self.on_call(role, model)
            except Exception:
                pass
        try:
            return backend.chat(model, messages, schema=schema, options=options,
                                 on_token=on_token, think=think)
        except Exception:                                # сеть/сервер/таймаут → фоллбэк
            return None

    def trace_take(self) -> list[dict]:
        """Снять накопленный трейс роутинга (роль→модель + прибл. длительность мс) и очистить.
        Длительность шага ≈ интервал до следующего вызова model_for (для дебага «куда ушёл ввод»)."""
        tr, self._trace = self._trace, []
        now = _perf_counter()
        out = []
        for i, e in enumerate(tr):
            end = tr[i + 1]["t"] if i + 1 < len(tr) else now
            out.append({"role": e["role"], "model": e["model"], "ms": round((end - e["t"]) * 1000)})
        return out[-40:]
