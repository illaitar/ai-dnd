"""LLM-генерация справочной базы материалов/ресурсов мира → content/srd/materials.json.

Чистого SRD нет, поэтому генерируем структурно (DeepSeek): по категориям, каждая запись —
{name, name_ru, mtype, source, value, uses}. NPC по домену (кузнец/травник/торговец/охотник)
подтягивают её; экономика/ремёсла берут как ресурсы. Запуск:  python scripts/gen_materials.py
"""

from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import enrich_bestiary  # noqa: E402  (_chat: DeepSeek)

OUT = os.path.join(os.path.dirname(__file__), "..", "src", "aidnd", "content", "srd", "materials.json")

CATEGORIES = [
    ("металлы и руды", "железо, медь, серебро, мифрил, адамантин и т.п."),
    ("древесина", "дуб, тис, железное дерево, теневой клён и т.п."),
    ("травы и растения", "лечебные/ядовитые/алхимические травы, грибы, корни"),
    ("шкуры и кожа", "шкуры зверей и тварей, чешуя, панцири"),
    ("ткани и волокно", "лён, шерсть, шёлк, паучий шёлк"),
    ("самоцветы и камень", "драгоценные камни, гранит, мрамор, обсидиан"),
    ("специи и снедь", "соль, пряности, сухие пайки, мёд, зерно"),
    ("части тварей", "клыки, когти, железы, кровь, кости магических существ"),
    ("алхимические реагенты", "сера, ртуть, эссенции стихий, фосфор"),
]


def _slug(name: str) -> str:
    return "mat:" + (re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "x")


def main() -> None:
    out, seen = [], set()
    for cat, hint in CATEGORIES:
        prompt = (
            f"Сгенерируй 20 разнообразных материалов/ресурсов фэнтези-мира D&D категории «{cat}» ({hint}). "
            "Для каждого — объект: {\"name\": англ.название, \"name_ru\": русское, \"mtype\": краткий подтип, "
            "\"source\": откуда добывают (регион/тварь/способ), \"value\": один из дёшево|средне|дорого|редко, "
            "\"uses\": для чего (ковка/алхимия/шитьё/торговля/еда)}. Реалистично, без повторов. "
            "Верни ТОЛЬКО JSON-массив, без markdown.")
        txt = enrich_bestiary._chat(prompt).strip().strip("`")
        if txt.lower().startswith("json"):
            txt = txt[4:].strip()
        try:
            arr = json.loads(txt)
        except Exception as e:  # noqa: BLE001
            print(f"  «{cat}»: парс не удался — {e}")
            continue
        n = 0
        for r in arr:
            nm = r.get("name") or r.get("name_ru")
            if not nm:
                continue
            rid = _slug(nm)
            if rid in seen:
                continue
            seen.add(rid)
            out.append({"id": rid, "name": nm, "name_ru": r.get("name_ru") or nm, "category": cat,
                        "mtype": r.get("mtype", ""), "source": r.get("source", ""),
                        "value": r.get("value", "средне"), "uses": r.get("uses", "")})
            n += 1
        print(f"  «{cat}»: +{n}")
    out.sort(key=lambda r: (r["category"], r["name_ru"]))
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print(f"материалов: {len(out)} → {OUT}")


if __name__ == "__main__":
    main()
