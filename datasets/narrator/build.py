"""Сборка narrator-датасета: examples.py → narrator.jsonl + валидация СТИЛЯ.

Запуск:  python build.py   (из datasets/narrator; нужен доступ к пакету aidnd)

user-промпт строится ТЕМ ЖЕ narrator_user(), что и рантайм (agents.py) → train==inference
без дрейфа шаблона. Вывод — проза, не JSON; валидируем стиль (длина, без пафоса/чисел,
имя не дублируется, у dialogue есть реплика в кавычках).
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from aidnd.inference.agents import MODE_HINTS, PROMPTS, narrator_user  # noqa: E402

# клише пафоса, сказовости и олицетворений — запрещены в эталонах
BANNED = [
    "сердце полно", "словно сам фатум", "добро пожаловать, странник", "первые лучи",
    "первых лучей", "о, путник", "судьба сама", "звонкой монетой", "сквозь века",
    "о, дивн", "в этот роковой", "уносясь мыслями", "трепещ", "доброго путника",
    "как посланник", "ночь, полная тайн", "первого солнца",
    # сказовость / архаика
    "молвил", "ступай с миром", "о, дивн", "доблестный воин", "славный герой",
    # генерик-вежливость (хотим речь ОТ ХАРАКТЕРА); одиночные «путник/странник» — ниже регэкспом
    "чем могу служить", "чем могу быть полезен", "чем могу помочь",
    "дорогой гость", "уважаемый гость", "рад приветствовать", "приветствую тебя",
    # олицетворения и пурпурная образность
    "дышит запуст", "клинок поёт", "тьма обнима", "туман шепч", "тонут в туман",
    "тишину рв", "ветер пел", "пляшут тени", "сама судьба",
]
MAXLEN = {"dialogue": 480, "greeting": 360, "outcome": 480, "combat": 360, "ambient": 560}

# нарратор НЕ советует игроку и НЕ описывает его мысли/чувства/решения — проверяем в
# ПОВЕСТВОВАНИИ (вне реплик NPC «...», где такие слова — это речь персонажа, и это ок)
ADVICE_PAT = [
    "лучше идти", "лучше не ", "лучше обойти", "лучше держ", "не суйся", "не суйс",
    "держись крепч", "держись ближе", "берегись", "будь начеку", "будь готов",
    "на твоём месте", "советую", "не то место, где хочется", "переждать или схорон",
    "придётся помок", "знай, что", "хочется задержаться",
]
THOUGHT_PAT = [
    "ты понимаешь", "понимаешь, что", "ты думаешь", "думаешь, что", "ты чувству",
    "тебе кажется", "ты решаешь", "ты осозна", "ты знаешь, что",
]


def _validate(mode: str, npc_name: str, gold: str) -> str | None:
    g = gold.strip()
    if not g:
        return "пустой эталон"
    if len(g) > MAXLEN.get(mode, 360):
        return f"слишком длинно ({len(g)} > {MAXLEN.get(mode, 360)})"
    if len(re.findall(r"[.!?…]+", g)) > 6:
        return "более 6 предложений"
    low = g.lower()
    for b in BANNED:
        if b in low:
            return f"пафосное клише: «{b}»"
    if re.search(r"(?<!\d)\d+(?!\d)", g) and mode in ("outcome", "combat", "ambient"):
        return "цифры в нарративе (механику печатать нельзя)"
    if mode in ("dialogue", "greeting") and "«" not in g:
        return "нет реплики NPC в кавычках «…»"
    if mode in ("dialogue", "greeting") and re.search(r"\b(путник|странник)\b", low):
        return "безличное обращение «путник/странник» — нужна речь ОТ ХАРАКТЕРА"
    if npc_name and g.lower().startswith(npc_name.split()[0].lower()):
        return "начинается с имени говорящего (его подписывает интерфейс)"
    narr = re.sub(r"«[^»]*»", " ", g).lower()      # повествование без реплик NPC
    for p in ADVICE_PAT:
        if p in narr:
            return f"совет/рекомендация игроку: «{p}»"
    for p in THOUGHT_PAT:
        if p in narr:
            return f"мысль/чувство за игрока: «{p}»"
    return None


def sample(mode: str, fields: dict, gold: str) -> dict:
    return {"messages": [
        {"role": "system", "content": PROMPTS["narrator"]},
        {"role": "user", "content": narrator_user(mode, **fields)},
        {"role": "assistant", "content": gold.strip()}]}


def main() -> None:
    from examples import EXAMPLES
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "narrator.jsonl")
    written, bad = 0, 0
    with open(out, "w", encoding="utf-8") as f:
        for ex in EXAMPLES:
            mode = ex["mode"]
            fields = {k: v for k, v in ex.items() if k not in ("mode", "gold")}
            err = _validate(mode, fields.get("name", ""), ex["gold"])
            if mode not in MODE_HINTS:
                err = err or f"неизвестный mode: {mode}"
            if err:
                bad += 1
                print(f"  ✗ [{mode}] «{ex['gold'][:40]}…»: {err}")
                continue
            f.write(json.dumps(sample(mode, fields, ex["gold"]), ensure_ascii=False) + "\n")
            written += 1
    print(f"\nwrote {written} → {os.path.relpath(out)}" + (f"  ({bad} invalid)" if bad else ""))
    print("по mode:", dict(Counter(e["mode"] for e in EXAMPLES)))


if __name__ == "__main__":
    main()
