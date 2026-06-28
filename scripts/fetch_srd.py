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

API = "https://api.open5e.com/v1"
OUT = os.path.join(os.path.dirname(__file__), "..", "src", "aidnd", "content", "srd")


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "aidnd-srd-fetch/1.0"})  # open5e блокирует пустой UA
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 (доверенный CC-BY источник)
        return json.loads(r.read().decode("utf-8"))


def _pages(path: str, query: str = "") -> list:
    sep = "&" if query else ""
    out, url = [], f"{API}/{path}/?limit=500{sep}{query}"
    while url:
        d = _get(url)
        out += d.get("results", [])
        url = d.get("next")
    return out


def _slug(name: str, prefix: str) -> str:
    return f"{prefix}:" + (re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "x")


_ABBR = {"strength": "str", "dexterity": "dex", "constitution": "con",
         "intelligence": "int", "wisdom": "wis", "charisma": "cha"}

# имя атаки → ключ нашего WEAPONS; природные атаки (укус/коготь/удар) → unarmed (увязка с движком)
_WEAPON_BY_ATK = {
    "scimitar": "scimitar", "longsword": "longsword", "shortsword": "shortsword", "greatsword": "greataxe",
    "greataxe": "greataxe", "battleaxe": "longsword", "handaxe": "dagger", "mace": "mace", "club": "mace",
    "warhammer": "mace", "maul": "greataxe", "morningstar": "morningstar", "dagger": "dagger",
    "quarterstaff": "quarterstaff", "staff": "quarterstaff", "spear": "shortsword", "trident": "shortsword",
    "glaive": "longsword", "halberd": "longsword", "pike": "shortsword", "rapier": "shortsword",
    "shortbow": "shortbow", "longbow": "shortbow", "light crossbow": "light_crossbow",
    "heavy crossbow": "light_crossbow", "crossbow": "light_crossbow",
}


def _cr(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return {"1/8": 0.125, "1/4": 0.25, "1/2": 0.5}.get(str(v), 0.0)


def _weapon(actions) -> str:
    for a in actions or []:
        nm = (a.get("name") or "").lower()
        for kw, key in _WEAPON_BY_ATK.items():
            if kw in nm:
                return key
    return "unarmed"


def _attack(actions):
    for a in actions or []:                              # первая атака с уроном — основная (для боя позже)
        if a.get("damage_dice"):
            return {"name": a.get("name"), "dice": a.get("damage_dice"),
                    "bonus": a.get("damage_bonus") or 0, "hit": a.get("attack_bonus")}
    return None


def fetch_monsters() -> list:
    """Полный SRD-бестиарий: механика (StatBlock) + ЛОР для NPC (тип/размер/среда/чувства/языки/иммунитеты/атака)."""
    out = []
    for m in _pages("monsters", "document__slug=wotc-srd"):  # только SRD 5.1 (CC-BY)
        try:
            spd = m.get("speed", {}).get("walk", 30) if isinstance(m.get("speed"), dict) else 30
            acts = m.get("actions") or []
            out.append({
                "id": _slug(m["name"], "srd"), "name": m["name"],
                **{a: m.get(full, 10) for full, a in _ABBR.items()},
                "ac": m.get("armor_class", 10), "hp": m.get("hit_points", 4),
                "speed": spd, "cr": _cr(m.get("cr", m.get("challenge_rating"))),
                "weapon": _weapon(acts),
                "traits": [t.get("name") for t in (m.get("special_abilities") or []) if t.get("name")][:8],
                # --- ЛОР для справки NPC (бой не читает, но мир знает) ---
                "size": m.get("size"), "ctype": m.get("type"), "alignment": m.get("alignment"),
                "senses": m.get("senses") or "", "languages": m.get("languages") or "",
                "environments": m.get("environments") or [],
                "resist": m.get("damage_resistances") or "", "immune": m.get("damage_immunities") or "",
                "cond_immune": m.get("condition_immunities") or "",
                "attack": _attack(acts), "desc": (m.get("desc") or "")[:500],
            })
        except (KeyError, TypeError):
            continue
    out.sort(key=lambda r: (r["cr"], r["name"]))         # отсортировать по опасности, затем имени
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
