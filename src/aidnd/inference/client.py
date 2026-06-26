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
        "cognition": (config.BASE_MODEL, "lore"),
        "lore_keeper": (config.BASE_MODEL, "lore"),
        "character_gen": (config.BASE_MODEL, "lore"),
        "tactician": (config.BASE_MODEL, "combat"),
        "reflection": (config.BASE_MODEL, "reflect"),
        "director": (config.BASE_MODEL, None),
        "quest_writer": (config.QUEST_MODEL, "quest"),   # дообученная модель (см. training/)
        "plausibility": (config.BASE_MODEL, "validator"),
        "faction_gen": (config.BASE_MODEL, "lore"),
    }

    def __init__(self, client: OllamaClient | None = None) -> None:
        self.client = client or OllamaClient()
        self._available: bool | None = None
        self._models: set[str] = set()
        self._trace: list[dict] = []        # дебаг-трейс роутинга: какие роли→модели дёргались за ход

    def available(self, recheck: bool = False) -> bool:
        """Проверяет доступность сервера (кешируется). False, если httpx не
        установлен либо сервер недоступен — тогда движок идёт по фоллбэкам."""
        if not _HAS_HTTPX:
            return False
        if self._available is None or recheck:
            try:
                self._models = set(self.client.list_models())
                self._available = True
            except OllamaError:
                self._available = False
        return self._available

    def model_for(self, role: str) -> str:
        base = self.ROLE_MODELS.get(role, (config.BASE_MODEL, None))[0]
        # self._models заполняется в available(); если ещё не проверяли — отдаём как есть.
        if not self._models or base in self._models:
            resolved = base
        elif f"{base}:latest" in self._models:           # Ollama хранит имена с тегом — матчим терпимо
            resolved = f"{base}:latest"
        else:                                            # дообученной модели нет на сервере — откат на базовую
            resolved = config.BASE_MODEL
        self._trace.append({"role": role, "model": resolved, "t": _perf_counter()})
        if len(self._trace) > 200:                       # safety: ограничить, если слив не зовут
            self._trace = self._trace[-100:]
        return resolved

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
