"""Сборка location-датасета: examples.py → location.jsonl + валидация стиля.

Запуск:  python build.py   (из datasets/location; нужен доступ к пакету aidnd)

user-промпт строится ТЕМ ЖЕ location_user(), что и рантайм forge_location (agents.py)
→ train==inference. Вывод — проза описания места (не JSON, не диалог)."""

from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from aidnd.inference.agents import PROMPTS, location_user  # noqa: E402

# пафос/архаика/олицетворения — запрещены в эталонах (как у нарратора)
BANNED = [
    "сердце полно", "словно сам фатум", "первые лучи", "первых лучей", "сквозь века",
    "молвил", "доблестный", "славный герой", "дышит запуст", "клинок поёт",
    "тьма обнима", "туман шепч", "тонут в туман", "тишину рв", "ветер пел",
    "пляшут тени", "сама судьба", "о, дивн",
]
# описание места НЕ советует игроку и НЕ лезет ему в голову
ADVICE_PAT = ["лучше идти", "лучше не ", "лучше обойти", "лучше держ", "не суйся", "не суйс",
              "держись крепч", "держись ближе", "берегись", "будь начеку", "будь готов",
              "на твоём месте", "советую", "придётся помок"]
THOUGHT_PAT = ["ты понимаешь", "понимаешь, что", "ты думаешь", "думаешь, что", "ты чувству",
               "тебе кажется", "ты решаешь", "ты осозна", "ты знаешь, что"]
MAXLEN = 620


def _validate(gold: str) -> str | None:
    g = gold.strip()
    if not g:
        return "пустой эталон"
    if len(g) > MAXLEN:
        return f"слишком длинно ({len(g)} > {MAXLEN})"
    if len(re.findall(r"[.!?…]+", g)) > 6:
        return "более 6 предложений"
    low = g.lower()
    for b in BANNED:
        if b in low:
            return f"пафосное клише: «{b}»"
    if re.search(r"(?<!\d)\d+(?!\d)", g):
        return "цифры в описании (механику печатать нельзя)"
    if "«" in g or '"' in g:
        return "реплика в кавычках — описание места без диалогов"
    for p in ADVICE_PAT:
        if p in low:
            return f"совет/рекомендация игроку: «{p}»"
    for p in THOUGHT_PAT:
        if p in low:
            return f"мысль/чувство за игрока: «{p}»"
    return None


def sample(fields: dict, gold: str) -> dict:
    return {"messages": [
        {"role": "system", "content": PROMPTS["location_writer"]},
        {"role": "user", "content": location_user(**fields)},
        {"role": "assistant", "content": gold.strip()}]}


def _flatten(trees: list) -> list[tuple[dict, str]]:
    """Дерево локаций → плоские узлы (node, within). Родитель — within='', суб-локации
    получают within = имя родителя; у суб-локаций своих детей нет (дерево глубины 1)."""
    nodes = []
    for tree in trees:
        nodes.append((tree, ""))
        for sub in tree.get("sublocations") or []:
            nodes.append((sub, tree.get("name", "")))
    return nodes


def main() -> None:
    from examples import LOCATION_EXAMPLES
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "location.jsonl")
    nodes = _flatten(LOCATION_EXAMPLES)
    parents = sum(1 for _, w in nodes if not w)
    written, bad = 0, 0
    with open(out, "w", encoding="utf-8") as f:
        for node, within in nodes:
            fields = {k: v for k, v in node.items() if k not in ("gold", "sublocations")}
            if within and not fields.get("within"):
                fields["within"] = within
            err = _validate(node.get("gold", ""))
            if err:
                bad += 1
                print(f"  ✗ «{str(node.get('gold', ''))[:42]}…»: {err}")
                continue
            f.write(json.dumps(sample(fields, node["gold"]), ensure_ascii=False) + "\n")
            written += 1
    print(f"\nwrote {written} узлов ({parents} локаций + {len(nodes) - parents} суб-локаций) → "
          f"{os.path.relpath(out)}" + (f"  ({bad} invalid)" if bad else ""))


if __name__ == "__main__":
    main()
