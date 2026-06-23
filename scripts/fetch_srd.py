"""Скачать ПОЛНЫЙ каталог SRD 5.1 из open5e (CC-BY-4.0) в content/srd/{monsters,items}.json.

Запуск (нужна сеть):  python scripts/fetch_srd.py
После — движок при старте подхватит все стат-блоки/предметы (см. content/srd_pack.py).
Курируемые LMoP-id при загрузке не перезаписываются; item_gen продолжает выдумывать.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request

API = "https://api.open5e.com"
OUT = os.path.join(os.path.dirname(__file__), "..", "src", "aidnd", "content", "srd")


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 (доверенный CC-BY источник)
        return json.loads(r.read().decode("utf-8"))


def _pages(path: str) -> list:
    out, url = [], f"{API}/{path}/?limit=500"
    while url:
        d = _get(url)
        out += d.get("results", [])
        url = d.get("next")
    return out


def _slug(name: str, prefix: str) -> str:
    return f"{prefix}:" + (re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "x")


_ABBR = {"strength": "str", "dexterity": "dex", "constitution": "con",
         "intelligence": "int", "wisdom": "wis", "charisma": "cha"}


def _cr(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return {"1/8": 0.125, "1/4": 0.25, "1/2": 0.5}.get(str(v), 0.0)


def fetch_monsters() -> list:
    out = []
    for m in _pages("monsters"):
        try:
            spd = m.get("speed", {}).get("walk", 30) if isinstance(m.get("speed"), dict) else 30
            out.append({"id": _slug(m["name"], "srd"), "name": m["name"],
                        **{a: m.get(full, 10) for full, a in _ABBR.items()},
                        "ac": m.get("armor_class", 10), "hp": m.get("hit_points", 4),
                        "speed": spd, "cr": _cr(m.get("challenge_rating"))})
        except (KeyError, TypeError):
            continue
    return out


def fetch_items() -> list:
    out = []
    for it in _pages("magicitems"):
        out.append({"id": _slug(it["name"], "tmpl"), "name": it["name"],
                    "category": "magic", "rarity": (it.get("rarity") or "uncommon").lower(),
                    "value": 0})
    return out


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    mons = fetch_monsters()
    with open(os.path.join(OUT, "monsters.json"), "w", encoding="utf-8") as f:
        json.dump(mons, f, ensure_ascii=False, indent=0)
    items = fetch_items()
    with open(os.path.join(OUT, "items.json"), "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=0)
    print(f"wrote {len(mons)} monsters, {len(items)} magic items → content/srd/")


if __name__ == "__main__":
    main()
