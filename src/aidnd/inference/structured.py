"""Reliable structured output (main §6.3).

All agent structured outputs go through constrained decoding by JSON Schema. On the
server this is XGrammar in vLLM (guided_json). For Ollama fallback we extract the first
JSON object from text or from native tool_calls and conform it to the schema. If nothing
valid is found, return None and the calling code takes a deterministic fallback.

Key functions
--------------
extract(response: dict, tool_name: str | None) -> dict | None : Extract structured result from LLM response.
coerce(obj: dict | None, required: list[str]) -> dict | None : Validate required schema fields present.
conform_to_schema(obj: dict | None, params: dict) -> dict | None : Normalize model output to match schema.
sanitize_for_ollama(schema) : Prepare JSON Schema for Ollama structured output grammar.
"""

from __future__ import annotations

import json


def _find_json(text: str) -> dict | None:
    """Find the first balanced {...} in text."""
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
    """Extract structured result from model response.

    response — what OllamaClient.chat returned ({"content", "tool_calls"}).
    """
    # 1) native tool_calls
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
    # 2) JSON in text
    content = response.get("content", "") or ""
    obj = _find_json(content)
    if obj is not None:
        # unwrap {"name":..., "parameters":{...}} or {"arguments":{...}}
        if "parameters" in obj and isinstance(obj["parameters"], dict):
            return obj["parameters"]
        if "arguments" in obj and isinstance(obj["arguments"], dict):
            return obj["arguments"]
        return obj
    return None


def coerce(obj: dict | None, required: list[str]) -> dict | None:
    """Minimal check that required schema fields are present."""
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
    """Snap value to nearest enum member (downstream validation, main §6.3)."""
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


# field synonyms: small models often rename keys to their own preference
_FIELD_SYNONYMS = {
    "verb": ["action", "command", "intent", "intent_verb"],
    "target": ["target_entity", "target_id", "object", "entity", "who", "npc"],
    "actor": ["subject", "who_acts"],
    "needs_clarification": ["ambiguous", "unclear", "needs_clarify", "clarify"],
    "narration": ["text", "output", "result"],
}


def _unwrap_payload(obj: dict, params: dict) -> dict:
    """Extract payload from small model wrappers: unwrap nested dict
    (e.g. {"intent": {...}}) and pull synonym field names toward schema.
    Ollama grammar is loose, so we normalize the shape on our side (main §6.3)."""
    if not isinstance(obj, dict):
        return obj
    props = set(params.get("properties", {}))
    # 1) if top level has no schema fields, dive into the first nested dict
    #    that contains the schema (wrappers like {"intent": {...}}/{"result": {...}})
    if props and not (props & set(obj)):
        for v in obj.values():
            if isinstance(v, dict) and (props & set(v)):
                obj = dict(v)
                break
    # 2) pull synonym keys to canonical schema names
    for canon, alts in _FIELD_SYNONYMS.items():
        if canon in props and canon not in obj:
            for a in alts:
                if a in obj and obj[a] is not None:
                    obj[canon] = obj[a]
                    break
    return obj


def conform_to_schema(obj: dict | None, params: dict) -> dict | None:
    """Conform model output to schema (unwrap wrappers + synonyms + enum snapping + types).

    Constrained decoding on vLLM+XGrammar would guarantee format at token level;
    Ollama's `format` does this loosely, so we conform on our side
    (main §6.3: downstream provides semantics and validity).
    """
    if obj is None:
        return None
    obj = _unwrap_payload(obj, params)
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
    """Prepare JSON Schema for Ollama structured output.

    Union types (`["string","null"]`) break Ollama grammar → format
    is ignored and enum is not respected. Reduce union to first non-null type
    (nullable expressed via field optionality). Recurse over properties/items.
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
