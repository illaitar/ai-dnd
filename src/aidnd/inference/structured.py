"""Надёжный structured output (main §6.3).

Все структурные выходы агентов идут через constrained decoding по JSON Schema. На
сервере это XGrammar в vLLM (guided_json). Для Ollama-фоллбэка извлекаем первый
JSON-объект из текста или из нативных tool_calls и приводим к схеме. Если ничего
валидного — возвращаем None, и вызывающий код берёт детерминированный фоллбэк.
"""

from __future__ import annotations

import json


def _find_json(text: str) -> dict | None:
    """Находит первый сбалансированный {...} в тексте."""
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


def extract(response: dict, tool_name: str | None = None) -> dict | None:
    """Извлекает структурированный результат из ответа модели.

    response — то, что вернул OllamaClient.chat ({"content", "tool_calls"}).
    """
    # 1) нативные tool_calls
    for tc in response.get("tool_calls", []):
        fn = tc.get("function", {})
        if tool_name and fn.get("name") not in (tool_name, None):
            continue
        args = fn.get("arguments")
        if isinstance(args, dict):
            return args
        if isinstance(args, str):
            try:
                return json.loads(args)
            except json.JSONDecodeError:
                pass
    # 2) JSON в тексте
    content = response.get("content", "") or ""
    obj = _find_json(content)
    if obj is not None:
        # развернуть {"name":..., "parameters":{...}} либо {"arguments":{...}}
        if "parameters" in obj and isinstance(obj["parameters"], dict):
            return obj["parameters"]
        if "arguments" in obj and isinstance(obj["arguments"], dict):
            return obj["arguments"]
        return obj
    return None


def coerce(obj: dict | None, required: list[str]) -> dict | None:
    """Минимальная проверка наличия обязательных полей схемы."""
    if obj is None:
        return None
    if all(k in obj for k in required):
        return obj
    return None


_ACTION_SYNONYMS = {
    "ignore": "withhold", "silent": "withhold", "evade": "withhold", "deflect": "withhold",
    "listen": "respond", "greet": "respond", "nod": "respond", "observe": "respond",
    "acknowledge": "respond", "wait": "respond",
    "tell": "share_info", "inform": "share_info", "share": "share_info", "reveal": "share_info",
    "run": "flee", "escape": "flee", "alarm": "call_guards", "guard": "call_guards",
    "lie": "deceive", "bluff": "deceive", "fight": "attack",
}


def _snap_enum(val, enum: list):
    """Снаппинг значения к ближайшему члену enum (downstream-валидация, main §6.3)."""
    s = str(val).lower()
    for e in enum:
        if e == s or e in s or s in e:
            return e
    for key, target in _ACTION_SYNONYMS.items():
        if key in s and target in enum:
            return target
    return enum[0]


def _stringify(val) -> str:
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        return "; ".join(_stringify(x) for x in val if x)[:400]
    if isinstance(val, dict):
        for k in ("text", "line", "narration", "description", "value", "tone"):
            if isinstance(val.get(k), str):
                return val[k]
        return ", ".join(f"{v}" for v in val.values() if isinstance(v, str | int | float))[:400]
    return str(val)


def conform_to_schema(obj: dict | None, params: dict) -> dict | None:
    """Приводит выход модели к схеме (enum-снаппинг + типы) — downstream-валидация.

    Constrained decoding на vLLM+XGrammar гарантировало бы формат на уровне токенов;
    `format` Ollama делает это нестрого, поэтому конформируем на нашей стороне
    (main §6.3: семантику и валидность обеспечивает downstream).
    """
    if obj is None:
        return None
    for key, spec in params.get("properties", {}).items():
        if key not in obj:
            continue
        val = obj[key]
        enum = spec.get("enum")
        if enum and val not in enum:
            obj[key] = _snap_enum(val, enum)
        typ = spec.get("type")
        if typ == "string" and not isinstance(obj[key], str):
            obj[key] = _stringify(obj[key])
        elif typ == "array" and not isinstance(obj[key], list):
            obj[key] = [obj[key]] if obj[key] is not None else []
    return obj


def sanitize_for_ollama(schema):
    """Готовит JSON Schema к structured output Ollama.

    Union-типы (`["string","null"]`) ломают грамматику Ollama → format
    игнорируется и enum не соблюдается. Сводим union к первому не-null типу
    (nullable выражается необязательностью поля). Рекурсивно по properties/items.
    """
    if isinstance(schema, dict):
        out = {}
        for k, v in schema.items():
            if k == "type" and isinstance(v, list):
                non_null = [t for t in v if t != "null"]
                out[k] = non_null[0] if non_null else "string"
            elif k in ("properties",) and isinstance(v, dict):
                out[k] = {pk: sanitize_for_ollama(pv) for pk, pv in v.items()}
            elif k == "items":
                out[k] = sanitize_for_ollama(v)
            else:
                out[k] = sanitize_for_ollama(v)
        return out
    if isinstance(schema, list):
        return [sanitize_for_ollama(x) for x in schema]
    return schema
