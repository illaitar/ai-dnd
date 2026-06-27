"""Сборка location-датасета: examples.py (деревья) → location.jsonl.

НОВЫЙ формат: на ВХОД — только краткие факты места (тип/функции/состояние/округа), что мир
знает в рантайме; модель САМА придумывает облик/материалы/запахи и ПРЕДЛАГАЕТ комнаты. Выход —
«<описание>\\n\\nКОМНАТЫ:\\n— Имя: краткое описание …» (комнаты собираем из sublocations дерева,
по 1-2 предложения). user-промпт строится тем же location_user(), что и рантайм → train==inference.
"""

from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from aidnd.inference.agents import PROMPTS, location_user  # noqa: E402

# поля факт-входа (то, что мир знает); остальное модель придумывает
_FACTS = ("type", "affordances", "condition", "region")

BANNED = [
    "сердце полно", "словно сам фатум", "первые лучи", "первых лучей", "сквозь века",
    "молвил", "доблестный", "славный герой", "дышит запуст", "клинок поёт",
    "тьма обнима", "туман шепч", "тонут в туман", "тишину рв", "ветер пел",
    "пляшут тени", "сама судьба", "о, дивн",
]
ADVICE_PAT = ["лучше идти", "лучше не ", "лучше обойти", "лучше держ", "не суйся", "не суйс",
              "держись крепч", "держись ближе", "берегись", "будь начеку", "будь готов",
              "на твоём месте", "советую", "придётся помок"]
THOUGHT_PAT = ["ты понимаешь", "понимаешь, что", "ты думаешь", "думаешь, что", "ты чувству",
               "тебе кажется", "ты решаешь", "ты осозна", "ты знаешь, что"]
MAXLEN_DESC, MAXLEN_ROOM = 620, 320


def _room_brief(gold: str, n: int = 2) -> str:
    """Первые n предложений суб-локации — краткое описание комнаты для списка КОМНАТЫ."""
    sents = re.split(r"(?<=[.!?…])\s+", (gold or "").strip())
    return " ".join(sents[:n]).strip()


def compose_gold(tree: dict) -> str:
    """Дерево → эталонный выход: описание родителя + список комнат (из sublocations, кратко)."""
    desc = (tree.get("gold") or "").strip()
    subs = [s for s in (tree.get("sublocations") or []) if s.get("gold")]
    if not subs:
        return desc
    lines = "\n".join(f"— {s['name']}: {_room_brief(s['gold'])}" for s in subs)
    return f"{desc}\n\nКОМНАТЫ:\n{lines}"


def _validate_prose(g: str, maxlen: int, max_sent: int = 6) -> str | None:
    g = (g or "").strip()
    if not g:
        return "пусто"
    if len(g) > maxlen:
        return f"длинно ({len(g)} > {maxlen})"
    if len(re.findall(r"[.!?…]+", g)) > max_sent:
        return f"более {max_sent} предложений"
    low = g.lower()
    for b in BANNED:
        if b in low:
            return f"клише «{b}»"
    if re.search(r"(?<!\d)\d+(?!\d)", g):
        return "цифры (механику печатать нельзя)"
    if "«" in g or '"' in g:
        return "кавычки/диалог"
    for p in ADVICE_PAT:
        if p in low:
            return f"совет «{p}»"
    for p in THOUGHT_PAT:
        if p in low:
            return f"мысль за игрока «{p}»"
    return None


def _validate(tree: dict) -> str | None:
    err = _validate_prose(tree.get("gold", ""), MAXLEN_DESC)
    if err:
        return f"описание: {err}"
    for s in tree.get("sublocations") or []:
        brief = _room_brief(s.get("gold", ""))
        if not brief:
            return f"комната «{s.get('name', '?')}»: пусто"
        err = _validate_prose(brief, MAXLEN_ROOM, max_sent=3)
        if err:
            return f"комната «{s.get('name', '?')}»: {err}"
    return None


def sample(tree: dict) -> dict:
    facts = {k: tree[k] for k in _FACTS if tree.get(k)}
    return {"messages": [
        {"role": "system", "content": PROMPTS["location_writer"]},
        {"role": "user", "content": location_user(tree["name"], **facts)},
        {"role": "assistant", "content": compose_gold(tree)}]}


def main() -> None:
    from examples import LOCATION_EXAMPLES
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "location.jsonl")
    written, bad, rooms = 0, 0, 0
    with open(out, "w", encoding="utf-8") as f:
        for tree in LOCATION_EXAMPLES:
            err = _validate(tree)
            if err:
                bad += 1
                print(f"  ✗ «{tree.get('name', '?')}»: {err}")
                continue
            f.write(json.dumps(sample(tree), ensure_ascii=False) + "\n")
            written += 1
            rooms += len(tree.get("sublocations") or [])
    print(f"\nwrote {written} локаций ({rooms} комнат) → {os.path.relpath(out)}"
          + (f"  ({bad} invalid)" if bad else ""))


if __name__ == "__main__":
    main()
