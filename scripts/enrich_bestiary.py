"""LLM-обогащение бестиария: добавить name_ru каждому монстру в content/srd/monsters.json (DeepSeek, батчами).

Запуск (нужны сеть и .secrets/deepseek.key):  python scripts/enrich_bestiary.py
Имена переводятся каноничными/устоявшимися формами D&D 5e; при сбое чанка остаётся английское имя.
"""

from __future__ import annotations

import json
import os
import urllib.request

ROOT = os.path.join(os.path.dirname(__file__), "..")
KEY = open(os.path.join(ROOT, ".secrets", "deepseek.key")).read().strip()
MONS = os.path.join(ROOT, "src", "aidnd", "content", "srd", "monsters.json")


def _chat(prompt: str) -> str:
    body = json.dumps({"model": "deepseek-chat", "temperature": 0.1,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=body,
                                 headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:  # noqa: S310
        return json.loads(r.read())["choices"][0]["message"]["content"]


def main() -> None:
    mons = json.load(open(MONS, encoding="utf-8"))
    names = sorted({m["name"] for m in mons})
    ru: dict[str, str] = {}
    for i in range(0, len(names), 60):
        chunk = names[i:i + 60]
        prompt = ("Переведи названия монстров D&D 5e на русский каноничными/устоявшимися формами "
                  "(Goblin→Гоблин, Owlbear→Совомедведь, Tarrasque→Тарраск, Beholder→Бихолдер). "
                  "Верни ТОЛЬКО JSON-массив объектов {\"en\":..., \"ru\":...}, без пояснений и без markdown.\n"
                  + json.dumps(chunk, ensure_ascii=False))
        txt = _chat(prompt).strip().strip("`")
        if txt.lower().startswith("json"):
            txt = txt[4:].strip()
        try:
            for o in json.loads(txt):
                if o.get("en") and o.get("ru"):
                    ru[o["en"]] = o["ru"]
            print(f"  чанк {i}-{i + len(chunk)}: ок ({len(ru)} всего)")
        except Exception as e:  # noqa: BLE001
            print(f"  чанк {i}: парс не удался — {e}")
    for m in mons:
        m["name_ru"] = ru.get(m["name"], m["name"])
    json.dump(mons, open(MONS, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    done = sum(1 for m in mons if m.get("name_ru") != m["name"])
    print(f"name_ru добавлено: {done}/{len(mons)}")


if __name__ == "__main__":
    main()
