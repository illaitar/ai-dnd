"""Сборка persona-датасета: gen/*.json (факты + gold) → persona.jsonl + валидация.

Весь датасет генерится (воркфлоу), хранится в gen/*.json как [{role,archetype,race,gender,age,
settlement,faction,standing,story_role, gold}]. user-промпт строится тем же persona_user(), что и
рантайм emit_persona → train==inference. gold — field-формат персоны (Имя/Голос/…/Секреты/Знания).
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from aidnd.inference.agents import PROMPTS, parse_persona, persona_user  # noqa: E402

_FACT_KEYS = ("role", "archetype", "race", "gender", "age", "settlement", "faction", "standing", "story_role")
# обязательные поля персоны (личность должна быть наполнена, а не пустые слоты)
_REQUIRED = ("name", "voice", "ideal", "bond", "flaw")
# лёгкий анти-анахронизм (фронтир, не современность)
BANNED = ["мэр", "бюджет", "полиц", "паспорт", "телефон", "газет", "процент", "доллар"]


def _validate(gold: str) -> str | None:
    g = (gold or "").strip()
    if not g:
        return "пусто"
    p = parse_persona(g)
    for f in _REQUIRED:
        if not p.get(f):
            return f"нет поля «{f}»"
    if not p.get("traits"):
        return "нет черт"
    if not p.get("secrets"):
        return "нет секретов"
    if not p.get("knowledge"):
        return "нет знаний"
    low = g.lower()
    for b in BANNED:
        if b in low:
            return f"анахронизм «{b}»"
    return None


def sample(ex: dict) -> dict:
    facts = {k: ex[k] for k in _FACT_KEYS if ex.get(k)}
    return {"messages": [
        {"role": "system", "content": PROMPTS["persona_gen"]},
        {"role": "user", "content": persona_user(**facts)},
        {"role": "assistant", "content": ex["gold"].strip()}]}


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    gendir = os.path.join(here, "gen")
    out = os.path.join(here, "persona.jsonl")
    seen, written, bad, arch = set(), 0, 0, Counter()
    with open(out, "w", encoding="utf-8") as f:
        for fn in sorted(os.listdir(gendir)):
            if not fn.endswith(".json"):
                continue
            try:
                data = json.load(open(os.path.join(gendir, fn), encoding="utf-8"))
            except Exception:
                continue
            for ex in (data if isinstance(data, list) else []):
                p = parse_persona(ex.get("gold", ""))
                nm = (p.get("name") or "").lower().strip()
                if nm and nm in seen:                      # дедуп по имени
                    continue
                err = _validate(ex.get("gold", ""))
                if err:
                    bad += 1
                    continue
                if nm:
                    seen.add(nm)
                f.write(json.dumps(sample(ex), ensure_ascii=False) + "\n")
                written += 1
                arch[ex.get("archetype", "?")] += 1
    print(f"\nwrote {written} персон → {os.path.relpath(out)}" + (f"  ({bad} invalid)" if bad else ""))
    print("по архетипам:", dict(arch.most_common(12)))


if __name__ == "__main__":
    main()
