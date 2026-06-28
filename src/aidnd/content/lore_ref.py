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


def candidates(query: str, k: int = 12):
    """Дешёвый префильтр по корням слов (4 буквы — терпит склонения) → топ-K кандидатов для LLM-резолюции."""
    low = " " + (query or "").lower() + " "
    scored = []
    for cat, db in CATALOGS.items():
        for ref, e in db.items():
            best_e = 0.0
            for nm in (e.get("name_ru") or "", e.get("name") or ""):
                cores = [c for c in (w.rstrip("ьъ")[:4] for w in nm.lower().split()) if len(c) >= 3]
                matched = [c for c in cores if (" " + c) in low]
                if matched and cores:                     # покрытие имени важнее: полное «Адамантин» > частичное «…доспехи»
                    best_e = max(best_e, (len(matched) / len(cores)) * 100 + len(matched) * 10 + sum(len(c) for c in matched))
            if best_e > 0:
                scored.append((best_e, cat, ref, e))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [(cat, ref, e) for _s, cat, ref, e in scored[:k]]


def lookup(query: str, model=None):
    """Найти мировую сущность по упоминанию. Стем-префильтр → LLM выбирает точную (терпит склонения/синонимы/
    частичные имена); офлайн / один кандидат / сбой LLM → лучший по скорингу. → (category, ref, entry) | None."""
    cands = candidates(query)
    if not cands:
        return None
    if model is not None and len(cands) > 1:
        from ..inference import agents
        idx = agents.match_entity(model, query, [(e.get("name_ru") or e.get("name")) for _c, _r, e in cands])
        if idx == -1:                                     # ИИ осознанно: ни одна — это не вопрос о сущности
            return None
        if 0 <= idx < len(cands):                         # ИИ выбрал кандидата
            return cands[idx]
        # idx == -2: ИИ недоступен/сбой → фоллбэк на скоринг ниже
    return cands[0]                                       # офлайн / один кандидат / сбой → лучший по скорингу


def tier(category: str, entry: dict) -> float:
    """Обобщённая известность/опасность сущности для гейта домена (CR / уровень / ранг редкости)."""
    if category == "bestiary":
        return float(entry.get("cr", 0) or 0)
    if category == "spells":
        return float(entry.get("level", 0) or 0)
    if category in ("magicitems", "items"):
        return float(_RARITY.get((entry.get("rarity") or "").lower(), 2))
    if category == "materials":
        return float({"дёшево": 0, "средне": 1, "дорого": 2, "редко": 3}.get((entry.get("value") or "").lower(), 1))
    return 0.0


def _etype(category: str, entry: dict):
    if category == "bestiary":
        return (entry.get("ctype") or "").lower()
    if category == "materials":
        return (entry.get("category") or "").lower()     # подкатегория материала (металлы/травы/…) для домена
    return None


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
    if category == "magicitems":
        e = entry
        nm = e.get("name_ru") or e.get("name")
        rar = {"common": "обычный", "uncommon": "необычный", "rare": "редкий", "very rare": "очень редкий",
               "legendary": "легендарный", "artifact": "артефакт"}.get((e.get("rarity") or "").lower(),
                                                                        e.get("rarity", ""))
        att = ", требует настройки" if e.get("attunement") else ""
        parts = [f"{nm} — магический предмет ({rar}{att})"]
        if e.get("itype"):
            parts.append("тип: " + str(e["itype"]))
        if e.get("desc"):
            parts.append(str(e["desc"])[:220])
        return ". ".join(p for p in parts if p)
    if category == "equipment":
        e = entry
        nm = e.get("name_ru") or e.get("name")
        if e.get("kind") == "weapon":
            parts = [f"{nm} — оружие ({e.get('category', '')})", f"урон {e.get('damage', '')} {e.get('damage_type', '')}"]
            if e.get("properties"):
                parts.append("свойства: " + ", ".join(str(p) for p in e["properties"][:4]))
        else:
            parts = [f"{nm} — броня ({e.get('category', '')})", f"КД {e.get('ac', '')}"]
        if e.get("cost"):
            parts.append("цена " + str(e["cost"]))
        return ". ".join(p for p in parts if p)
    if category == "materials":
        e = entry
        nm = e.get("name_ru") or e.get("name")
        parts = [f"{nm} — {e.get('category', 'материал')} ({e.get('mtype', '')}, ценность: {e.get('value', '')})"]
        if e.get("source"):
            parts.append("добыча: " + str(e["source"]))
        if e.get("uses"):
            parts.append("применение: " + str(e["uses"]))
        return ". ".join(p for p in parts if p)
    if category == "flora":
        e = entry
        nm = e.get("name_ru") or e.get("name")
        parts = [f"{nm} — {e.get('ftype', 'растение')}"]
        if e.get("habitat"):
            parts.append("растёт: " + str(e["habitat"]))
        if e.get("uses"):
            parts.append("применение: " + str(e["uses"]))
        if e.get("danger") and str(e["danger"]).lower() not in ("", "нет", "none", "безопасно"):
            parts.append("опасность: " + str(e["danger"]))
        return ". ".join(p for p in parts if p)
    # обобщённый запас для простых баз (состояния/классы/планы и т.п.): имя + описание
    nm = entry.get("name_ru") or entry.get("name")
    d = entry.get("desc") or entry.get("uses") or ""
    return f"{nm} — {str(d)[:260]}" if d else (nm or "")
