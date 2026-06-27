"""Слой LLM-бэкендов: провайдер моделей — чёрный ящик за единым интерфейсом.

Агенты зовут ModelManager.call(role, …); тот по активному профилю выбирает (backend, model)
и дёргает backend.chat(…). Добавить провайдера = новый класс здесь + строчка в profiles.py.
Каждый бэкенд САМ переводит провайдер-агностичную JSON-схему в своё (Ollama format /
OpenAI response_format)."""

from __future__ import annotations

from .. import config
from .client import OllamaClient, OllamaError
from .structured import sanitize_for_ollama

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:                                  # pragma: no cover
    _HAS_HTTPX = False


class OllamaBackend:
    """Локальная Ollama (наш текущий путь): тюненые адаптеры, грамматико-строгий JSON."""
    name = "ollama"
    parallel_enrich = 1          # своп LoRA/моделей на одной GPU → параллель вредна (последовательно)

    def __init__(self, client: OllamaClient | None = None) -> None:
        self.client = client or OllamaClient()
        self._models: set[str] = set()

    def available(self) -> bool:
        try:
            self._models = set(self.client.list_models())
            return True
        except OllamaError:
            return False

    def resolve(self, model: str) -> str:
        """Имя модели Ollama: терпимо к тегу :latest; нет дообученной → откат на базовую."""
        ms = self._models
        if not ms or model in ms:
            return model
        if f"{model}:latest" in ms:
            return f"{model}:latest"
        return config.BASE_MODEL

    def chat(self, model, messages, *, schema=None, options=None, on_token=None, think=False) -> dict:
        tools = fmt = None
        if schema:                                   # схема → нативный tool ИЛИ guided-JSON (как было)
            if config.USE_NATIVE_TOOLS:
                tools = [{"type": "function", "function": schema}]
            else:
                fmt = sanitize_for_ollama(schema["parameters"])
        if on_token is not None:
            return self.client.chat_stream(model, messages, on_token=on_token, tools=tools,
                                           fmt=fmt, options=options, think=think)
        return self.client.chat(model, messages, tools=tools, fmt=fmt, options=options, think=think)


class OpenAICompatBackend:
    """Любой OpenAI-совместимый провайдер (DeepSeek, vLLM, llama.cpp-server, …).
    schema → response_format=json_object (мягче грамматики Ollama, но модель следует промпту)."""

    def __init__(self, name: str, base: str, key: str, default_model: str) -> None:
        self.name = name
        self.base = base.rstrip("/")
        self.key = key
        self.default_model = default_model
        self.parallel_enrich = max(1, config.DEEPSEEK_CONCURRENCY)   # облако: network-bound → параллелим enrich

    def available(self) -> bool:
        return bool(self.key) and _HAS_HTTPX

    def resolve(self, model: str) -> str:
        return model or self.default_model

    def chat(self, model, messages, *, schema=None, options=None, on_token=None, think=False) -> dict:
        body: dict = {"model": model or self.default_model, "messages": messages,
                      "temperature": (options or {}).get("temperature", 0.0)}
        if schema:
            body["response_format"] = {"type": "json_object"}
            if not any("json" in (m.get("content") or "").lower() for m in messages):
                body["messages"] = messages + [{"role": "system",   # json_object требует «json» в промпте
                    "content": "Ответь ОДНИМ валидным JSON-объектом по полям из инструкции, без иного текста."}]
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        r = httpx.post(f"{self.base}/chat/completions", json=body, headers=headers,
                       timeout=config.HTTP_TIMEOUT)
        if r.status_code != 200:
            raise OllamaError(f"{self.name} {r.status_code}: {r.text[:200]}")
        content = (r.json()["choices"][0]["message"].get("content") or "")
        if on_token and content:                     # стрим не разбиваем (v1): один колбэк целиком
            on_token(content)
        return {"content": content, "tool_calls": []}
