"""Справочная база мира + механизм «NPC подтягивает знание», завязанный на память.

Знание = ДОМЕННОЕ (профессия→категория→тир, данные в knowledge.KNOWLEDGE_DOMAINS) ИЛИ ЛИЧНОЕ
(выучено опытом/рассказом/диффузией, world.lore_learned). База = истина-грунт; память решает, кто что знает.

Реестр РАСШИРЯЕМ: новая база (spells/items/materials) = register(категория, dict) + ветка в tier()/facts()
+ правила домена в knowledge.KNOWLEDGE_DOMAINS. Всё остальное (lookup/knows/learn/диффузия) — общее."""

from __future__ import annotations

from ..world.components import Persona

CATALOGS: dict[str, dict] = {}                            # категория → {ref: entry}; заполняют загрузчики баз
_RARITY = {"common": 1, "uncommon": 2, "rare": 3, "very rare": 4, "legendary": 5, "artifact": 6}


def register(category: str, db: dict) -> None:
    CATALOGS[category] = db


def _firstword(s: str) -> str:
    return (s or "").lower().split()[0] if s else ""


def lookup(query: str):
    """Найти мировую сущность по упоминанию в тексте. → (category, ref, entry) | None (предпочесть длинное совпадение)."""
    low = " " + (query or "").lower() + " "
    best, best_score = None, 0
    for cat, db in CATALOGS.items():
        for ref, e in db.items():
            for nm in (e.get("name_ru") or "", e.get("name") or ""):
                cores = [w.rstrip("ьъ")[:6] for w in nm.lower().split()]   # корни слов: терпят склонения
                cores = [c for c in cores if len(c) >= 3]
                matched = [c for c in cores if (" " + c) in low]
                if not matched:
                    continue
                score = len(matched) * 10 + sum(len(c) for c in matched)   # больше совпавших слов → точнее (огн. шар > огн. элементаль)
                if score > best_score:
                    best, best_score = (cat, ref, e), score
    return best


def tier(category: str, entry: dict) -> float:
    """Обобщённая известность/опасность сущности для гейта домена (CR / уровень / ранг редкости)."""
    if category == "bestiary":
        return float(entry.get("cr", 0) or 0)
    if category == "spells":
        return float(entry.get("level", 0) or 0)
    if category in ("magicitems", "items"):
        return float(_RARITY.get((entry.get("rarity") or "").lower(), 2))
    return 0.0


def _etype(category: str, entry: dict):
    return (entry.get("ctype") or "").lower() if category == "bestiary" else None


def domain_knows(persona, category: str, entry: dict) -> bool:
    """Знает ли NPC по ДОМЕНУ профессии (данные KNOWLEDGE_DOMAINS): тип в домене и тир ≤ потолка."""
    from .knowledge import KNOWLEDGE_DOMAINS
    t, typ = tier(category, entry), _etype(category, entry)
    keys = ["_everyone"]
    if persona:
        prof = ((persona.profession or "") + " " + (persona.archetype or "")).lower()
        keys += [k for k in KNOWLEDGE_DOMAINS if k != "_everyone" and k in prof]
    for k in keys:
        rule = KNOWLEDGE_DOMAINS.get(k, {}).get(category)
        if not rule:
            continue
        if rule.get("types") and typ and typ not in rule["types"]:
            continue
        if t <= rule.get("max_tier", 0):
            return True
    return False


# --- ЛИЧНОЕ знание (выучено опытом/рассказом/диффузией) — world.lore_learned[npc] = {"cat:ref"} --- #
def _learned(world) -> dict:
    if not hasattr(world, "lore_learned") or world.lore_learned is None:
        world.lore_learned = {}
    return world.lore_learned


def learn(world, npc: str, category: str, ref: str) -> None:
    _learned(world).setdefault(npc, set()).add(f"{category}:{ref}")


def has_learned(world, npc: str, category: str, ref: str) -> bool:
    return f"{category}:{ref}" in _learned(world).get(npc, set())


def knows(world, npc: str, category: str, ref: str, entry: dict) -> bool:
    """Знает = в ДОМЕНЕ профессии ИЛИ ВЫУЧИЛ лично (опыт/рассказ/диффузия)."""
    persona = world.ecs.get(npc, Persona)
    return domain_knows(persona, category, entry) or has_learned(world, npc, category, ref)


def facts(category: str, entry: dict) -> str:
    """Сжатые факты сущности для заземления ответа NPC (LLM озвучивает поверх)."""
    if category == "bestiary":
        e = entry
        nm = e.get("name_ru") or e.get("name")
        parts = [f"{nm} — {e.get('size', '')} {e.get('ctype', '')}, опасность CR {e.get('cr')}"]
        if e.get("environments"):
            parts.append("обитает: " + ", ".join(e["environments"][:4]))
        if e.get("immune"):
            parts.append("неуязвим к: " + str(e["immune"])[:60])
        if e.get("traits"):
            parts.append("особенности: " + ", ".join(t for t in e["traits"][:3] if t))
        if e.get("attack"):
            parts.append(f"атака: {e['attack'].get('name')} ({e['attack'].get('dice')})")
        if e.get("desc"):
            parts.append(str(e["desc"])[:220])
        return ". ".join(p for p in parts if p)
    if category == "spells":
        e = entry
        nm = e.get("name_ru") or e.get("name")
        sch = {"Evocation": "воплощение", "Conjuration": "вызов", "Abjuration": "ограждение",
               "Transmutation": "преобразование", "Divination": "прорицание", "Enchantment": "очарование",
               "Illusion": "иллюзия", "Necromancy": "некромантия"}.get(e.get("school", ""), e.get("school", ""))
        lv = e.get("level", 0)
        parts = [f"{nm} — {'заговор' if lv == 0 else str(lv) + '-го круга'}, школа {sch}"]
        if e.get("classes"):
            parts.append("у классов: " + str(e["classes"]))
        if e.get("range"):
            parts.append("дистанция " + str(e["range"]))
        if e.get("duration"):
            parts.append("длительность " + str(e["duration"]))
        if e.get("desc"):
            parts.append(str(e["desc"])[:220])
        return ". ".join(p for p in parts if p)
    return ""
