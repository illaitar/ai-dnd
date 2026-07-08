"""Casting: string cast members onto EXISTING placed NPCs (solution C3: ~80%).
Match by role/persona: archetype → preferred city roles; greedy scoring.
Not found — actor remains NEW (significant NPC will be added in next slice).

Key functions
-------------
match_cast(cast: list, people: dict) -> dict : Greedily match cast members to
  NPCs by role; returns {cast_id: pid|None}.
"""

from __future__ import annotations

# archetype → preferred city citizen roles (order = priority)
_PREF = {
    "антагонист-в-тени": ("знахарка", "жрец", "маг", "писец"),
    "фасадный лидер": ("жрец", "трактирщик", "лавочник"),
    "правая рука": ("стражник", "наёмник", "кузнец"),
    "слабое звено": ("лавочник", "писец", "мельник"),
    "фанатик": ("горожанин", "жрец"),
    "наставник": ("маг", "кузнец", "жрец", "знахарка"),
    "скрытый союзник": ("трактирщик", "лавочник", "стражник"),
    "предатель-среди-своих": ("стражник", "головорез"),
    "ложный след": ("головорез", "бродяга", "дубильщик"),
    "свидетель": ("горожанин", "трактирщик", "мельник"),
    "сердце истории": ("горожанин",),
    "разменная пешка": ("бродяга", "головорез", "горожанин"),
    "торговец-обеим-сторонам": ("лавочник", "оружейник", "трактирщик"),
}


def match_cast(cast: list, people: dict) -> dict:
    """Actor → pid. Greedily: important first, role from preferences, each NPC — once.
    Returns {cast_id: pid|None}; mutates cast (field 'actor')."""
    used: set = set()
    by_role: dict = {}
    for pid, p in people.items():
        by_role.setdefault(p.role, []).append(pid)
    out = {}
    for a in sorted(cast, key=lambda x: -(x.get("важность") or 0)):
        pid = None
        for role in _PREF.get(a.get("роль"), ()) + ("горожанин",):
            pool = [i for i in by_role.get(role, []) if i not in used]
            if pool:
                pid = sorted(pool)[0]                       # determinism
                break
        if pid:
            used.add(pid)
            a["актёр"] = pid
        else:
            a["актёр"] = "NEW"
        out[a["id"]] = pid
    return out
