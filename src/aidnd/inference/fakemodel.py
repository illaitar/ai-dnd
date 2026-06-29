"""Детерминированная МОК-модель для тестов (Фаза 2 диалогового проекта).

Прод всегда онлайн (DeepSeek); офлайн = только тесты. Чтобы вырезать офлайн-фоллбэки, движку нужна
модель и в тестах — но без сети/API и детерминированно. FakeModel выдаёт:
  • для нарратора (свободный текст, schema=None) — короткую правдоподобную реплику из промпта;
  • для структурных ролей — объект, ВАЛИДНЫЙ по переданной JSON-схеме (заполняет required по типам).
Так движок идёт по LLM-пути, а тесты проверяют структуру/заземление, а не точные слова LLM.
"""

from __future__ import annotations

import json


def _num_for(name: str) -> float | int:
    n = name.lower()
    if "index" in n:
        return -1                      # npc_ref/match_entity: «никто/ничего» — безопасный дефолт
    if "plausib" in n or "prob" in n or "confidence" in n:
        return 0.5
    if "level" in n or "tier" in n or "cr" in n or "rank" in n:
        return 1
    return 0


def _str_for(name: str, messages: list) -> str:
    n = name.lower()
    if n in ("name", "name_ru", "title", "label"):
        return "Некто"
    if n in ("narration", "text", "line", "reply", "summary", "fact", "rationale", "note", "desc", "say"):
        return "…"
    if "verb" in n or "action" in n or "intent" in n:
        return ""                      # обычно enum — подставится первый вариант на уровне _field
    return "—"


def _field(name: str, spec: dict, messages: list):
    if "enum" in spec and spec["enum"]:
        return spec["enum"][0]
    t = spec.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "string")
    if t == "string":
        return _str_for(name, messages)
    if t in ("integer", "number"):
        return _num_for(name)
    if t == "boolean":
        return False
    if t == "array":
        return []
    if t == "object":
        return _obj(spec, messages)
    return ""


def _obj(params: dict, messages: list) -> dict:
    out = {}
    for key, spec in (params.get("properties") or {}).items():
        out[key] = _field(key, spec, messages)
    for key in params.get("required", []):                 # required без описания — пустая строка
        out.setdefault(key, "")
    return out


def _narration(messages: list) -> str:
    """Свободный текст нарратора: детерминированная заглушка из последней строки промпта."""
    user = ""
    for m in reversed(messages or []):
        if m.get("role") == "user":
            user = m.get("content") or ""
            break
    tail = user.strip().splitlines()[-1][:90] if user.strip() else ""
    return f"[mock] {tail}".strip() or "[mock]"


class FakeModel:
    """Мок ModelManager: available()=True, call() детерминированно и schema-валидно. Для тестов."""

    on_call = None

    def available(self) -> bool:
        return True

    def backend_name(self, role: str) -> str:
        return "ollama"                                     # базовые промпты ролей (без бэкенд-тюнинга)

    def call(self, role: str, messages: list, *, schema=None, options=None,
             on_token=None, think: bool = False):
        if self.on_call is not None:
            try:
                self.on_call(role, "fake")
            except Exception:
                pass
        if schema is None:                                  # нарратор и пр. свободный текст
            return {"content": _narration(messages), "tool_calls": []}
        data = _obj(schema.get("parameters", {}), messages)
        return {"content": json.dumps(data, ensure_ascii=False), "tool_calls": []}

    def trace_take(self) -> list:
        return []
