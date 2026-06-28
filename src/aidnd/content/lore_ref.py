"""Справочная база мира + механизм «NPC подтягивает знание».

Любой NPC при вопросе о существе (а дальше — предмете/заклинании/материале) отвечает из реестра баз,
ГЕЙТЯ по своему домену знания (простолюдин — общее, следопыт — звери, жрец — нежить, мудрец — всё).
Здесь: поиск сущности + гейт знания + сжатые факты для заземления. Озвучивает ответ LLM (или шаблон офлайн).

Реестр расширяемый: каждая новая база (spells/items/…) добавляет свою ветку в lookup/facts/knows."""

from __future__ import annotations


def _firstword(s: str) -> str:
    return (s or "").lower().split()[0] if s else ""


def lookup(query: str):
    """Найти мировую сущность по упоминанию в тексте игрока. → (category, ref, entry) | None."""
    from .srd_pack import BESTIARY
    low = " " + (query or "").lower() + " "
    best = None
    for ref, e in BESTIARY.items():                       # bestiary: матч по корню русского/англ имени
        for nm in (e.get("name_ru") or "", e.get("name") or ""):
            w = _firstword(nm)
            if len(w) >= 4 and (w in low or (len(w) > 6 and w[:6] in low)):
                if best is None or len(w) > len(_firstword(best[2].get("name_ru") or best[2].get("name") or "")):
                    best = ("bestiary", ref, e)            # предпочесть более длинное совпадение
    return best


def knows(persona, category: str, entry: dict) -> bool:
    """Знает ли NPC этой профессии о сущности (домен + редкость/опасность)."""
    prof = (((persona.profession or "") + " " + (persona.archetype or "")).lower()) if persona else ""
    if category == "bestiary":
        cr = float(entry.get("cr", 0) or 0)
        ctype = (entry.get("ctype") or "").lower()
        if cr <= 1:                                       # общеизвестные слабые твари — знает каждый
            return True
        if any(k in prof for k in ("следопыт", "охотник", "ranger", "друид", "егер", "зверолов")) \
                and ctype in ("beast", "monstrosity", "plant"):
            return True
        if any(k in prof for k in ("жрец", "priest", "cleric", "служка", "паладин", "монах")) \
                and ctype in ("undead", "fiend", "celestial", "aberration"):
            return True
        if any(k in prof for k in ("страж", "guard", "soldier", "knight", "рыцар", "капитан",
                                   "ветеран", "солдат", "наёмник", "thug", "громила")) and cr <= 6:
            return True
        if any(k in prof for k in ("маг", "mage", "wizard", "мудрец", "sage", "учён", "guildmaster",
                                   "гильдмастер", "писарь", "scribe", "жрец", "priest")):
            return True                                   # учёные/маги/жрецы знают и легендарных тварей
        return cr <= 2                                    # прочие — только до CR 2
    return True


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
    return ""
