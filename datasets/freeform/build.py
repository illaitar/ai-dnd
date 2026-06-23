"""Сборка дообучающего датасета freeform-пайплайна: examples.py → freeform.jsonl + валидация.

Запуск:  python build.py   (из datasets/freeform; нужен доступ к пакету aidnd)

Один корпус, три под-задачи (router/arbiter/consequence). system-промпты и схемы берутся
из aidnd.inference.agents, user-сообщения строятся ровно как на инференсе. Невалидное не пишется.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from aidnd.inference.agents import PROMPTS  # noqa: E402

QUERY_TYPES = {"look", "items", "who", "exits", "inventory", "status", "map"}
VERBS = {"move", "talk", "attack", "inspect", "search", "loot", "buy", "sell",
         "inventory", "wait", "persuade", "intimidate", "drink"}
TONES = {"neutral", "friendly", "hostile", "deceptive", "fearful"}
KINDS = {"place", "npc", "item", "self"}
RESOLUTIONS = {"auto_success", "auto_fail", "roll"}
BAD_KEYS = {"entity", "target_kind", "target_type", "target_name", "type", "value", "change_kind"}


# --- user-сообщения: те же шаблоны, что в agents.py (обучение == инференс) --- #
def _router_user(s: dict) -> str:
    hist = f"Recent turns:\n{s['history']}\n" if s.get("history") else ""
    return (f"{hist}Scene: {s['scene']}\nPresent NPCs: {s.get('npcs', [])}\n"
            f"Player input: «{s['input']}»\n"
            'Return the JSON object {"kind":…, "query_type":…, "verb":…, "target":…, "tone":…}.')


def _arbiter_user(s: dict) -> str:
    return (f"PLAYER action: «{s['action']}»\nScene: {s['scene']}\n"
            f"Estimated plausibility 0..1: {s['p']:.2f}\n"
            f"Decide how to resolve it. If a check is warranted, give ability, skill and dc "
            f"(lower dc the more plausible). Call decide_resolution.")


def _consequence_user(s: dict) -> str:
    hist = f"Recent turns:\n{s['history']}\n" if s.get("history") else ""
    return (f"{hist}Location: {s['location']}\nPresent NPCs: {s.get('npcs', [])}\n"
            f"Carried items: {s.get('items', [])}\n"
            f"Player action: «{s['action']}»\nOutcome: {s['outcome']}.\n"
            'List durable world effects (empty if none). Return {"effects":[...]}.')


# --- валидация выходов ------------------------------------------------------ #
def _no_bad_keys(obj) -> str | None:
    if isinstance(obj, dict):
        bad = BAD_KEYS & set(obj)
        if bad:
            return f"чужие ключи: {sorted(bad)}"
        for v in obj.values():
            if (e := _no_bad_keys(v)):
                return e
    elif isinstance(obj, list):
        for v in obj:
            if (e := _no_bad_keys(v)):
                return e
    return None


def _v_router(o: dict, s: dict) -> str | None:
    if o.get("kind") not in ("query", "dialogue", "command", "freeform"):
        return f"kind: {o.get('kind')}"
    if o["kind"] == "query" and o.get("query_type") not in QUERY_TYPES:
        return f"query_type: {o.get('query_type')}"
    if o["kind"] == "command" and o.get("verb") not in VERBS:
        return f"verb: {o.get('verb')}"
    if o.get("tone") not in TONES:
        return f"tone: {o.get('tone')}"
    return None


def _v_arbiter(o: dict, s: dict) -> str | None:
    if o.get("resolution") not in RESOLUTIONS:
        return f"resolution: {o.get('resolution')}"
    if o["resolution"] == "roll" and not o.get("skill"):
        return "roll без skill"
    if o["resolution"] == "roll" and not isinstance(o.get("dc"), int):
        return "roll без dc:int"
    return None


def _v_consequence(o: dict, s: dict) -> str | None:
    if not isinstance(o.get("effects"), list):
        return "effects не список"
    npcs = {n.lower() for n in s.get("npcs", [])}
    items = {i.lower() for i in s.get("items", [])}
    for e in o["effects"]:
        if e.get("kind") not in KINDS:
            return f"effect.kind: {e.get('kind')}"
        nm = (e.get("name") or "").lower()
        if e["kind"] == "npc" and nm and not any(nm in n or n in nm for n in npcs):
            return f"npc не в касте: {e.get('name')}"
        if e["kind"] == "item" and nm and not any(nm in i or i in nm for i in items):
            return f"item не в касте: {e.get('name')}"
        for d in ("trust", "fear", "affinity"):
            if e.get(d) is not None and not (-0.25 <= float(e[d]) <= 0.25):
                return f"дельта {d} вне [-0.25,0.25]: {e[d]}"
    return None


ROLES = {
    "router": ("router", _router_user, _v_router),
    "arbiter": ("arbiter", _arbiter_user, _v_arbiter),
    "consequence": ("consequence", _consequence_user, _v_consequence),
}


def sample(role: str, user: str, out: dict) -> dict:
    return {"messages": [
        {"role": "system", "content": PROMPTS[role]},
        {"role": "user", "content": user},
        {"role": "assistant", "content": json.dumps(out, ensure_ascii=False)}]}


def main() -> None:
    from examples import ARBITER, CONSEQUENCE, ROUTER
    groups = {"router": ROUTER, "arbiter": ARBITER, "consequence": CONSEQUENCE}
    here = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(here, "freeform.jsonl")
    written, bad = 0, 0
    with open(out_path, "w", encoding="utf-8") as f:
        for task, rows in groups.items():
            role, user_fn, validate = ROLES[task]
            for s in rows:
                out = s["out"]
                err = _no_bad_keys(out) or validate(out, s)
                if err:
                    bad += 1
                    print(f"  ✗ [{task}] «{s.get('input') or s.get('action')}»: {err}")
                    continue
                f.write(json.dumps(sample(role, user_fn(s), out), ensure_ascii=False) + "\n")
                written += 1
    print(f"\nwrote {written} samples → {os.path.relpath(out_path)}" + (f"  ({bad} invalid)" if bad else ""))
    print("per task:", {t: len(g) for t, g in groups.items()})
    cons = [e for s in CONSEQUENCE for e in s["out"]["effects"]]
    print("consequence effect kinds:", dict(Counter(e["kind"] for e in cons)),
          "| пустых (trivial):", sum(1 for s in CONSEQUENCE if not s["out"]["effects"]))


if __name__ == "__main__":
    main()
