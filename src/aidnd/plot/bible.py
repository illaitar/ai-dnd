"""Библия сюжета: структура + ВАЛИДАТОР правил драматургии (код, не вкус LLM). См. docs/PLOT.md.

Несущая балка: иерархия ≠ важность. Валидатор ОБЯЗУЕТ разрыв осей, чеховские ружья, арки.
Игрок — регрессор: библия несёт «прошлый_цикл» (пролог книги) и «дельта» (где память врёт).

Key functions
-------------
validate_bible(b: dict) -> list : Validate plot structure; return list of errors or empty.
"""

from __future__ import annotations

CATEGORIES = ("враг", "союзник", "нейтрал")

ARCHETYPES = ("антагонист-в-тени", "фасадный лидер", "правая рука", "слабое звено", "фанатик",
              "наставник", "скрытый союзник", "предатель-среди-своих", "ложный след",
              "свидетель", "сердце истории", "разменная пешка", "торговец-обеим-сторонам")

# минимумы первого среза (каст 30+, решение С7)
MIN_CAST = 30
MIN_ENEMIES, MIN_ALLIES, MIN_NEUTRALS = 12, 8, 8
MIN_ENEMY_RANKS = 4                    # глубина иерархии врага
MIN_ARCS = 2
ENTRY_MIN, ENTRY_MAX = 4, 6            # точки контакта, раскиданные по миру


def validate_bible(b: dict) -> list:
    """Список нарушений правил драматургии (пусто = библия годна)."""
    errs: list = []
    for key in ("тема", "конфликт", "тайна", "правда", "прошлый_цикл", "память_регрессора",
                "дельта", "входы", "акты", "каст"):
        if not b.get(key):
            errs.append(f"нет поля «{key}»")
    # память регрессора — ТОЛЬКО ОБЩЕЕ (3-6 пунктов): что беда была и чем кончилась,
    # примерное расписание, пара смутных лиц. ПРАВДА (кто глава, кто предатель) в память не входит!
    mem = b.get("память_регрессора") or []
    if not (3 <= len(mem) <= 6):
        errs.append(f"память регрессора: {len(mem)} пунктов, нужно 3-6 (общих, без правды)")
    cast = b.get("каст") or []
    if len(cast) < MIN_CAST:
        errs.append(f"каст мал: {len(cast)} < {MIN_CAST}")
    by_cat = {c: [a for a in cast if a.get("категория") == c] for c in CATEGORIES}
    if len(by_cat["враг"]) < MIN_ENEMIES:
        errs.append(f"врагов {len(by_cat['враг'])} < {MIN_ENEMIES}")
    if len(by_cat["союзник"]) < MIN_ALLIES:
        errs.append(f"союзников {len(by_cat['союзник'])} < {MIN_ALLIES}")
    if len(by_cat["нейтрал"]) < MIN_NEUTRALS:
        errs.append(f"нейтралов {len(by_cat['нейтрал'])} < {MIN_NEUTRALS}")
    ranks = {a.get("иерархия", {}).get("ранг") for a in by_cat["враг"]
             if a.get("иерархия", {}).get("ранг")}
    if len(ranks) < MIN_ENEMY_RANKS:
        errs.append(f"иерархия врага мелкая: {len(ranks)} < {MIN_ENEMY_RANKS} уровней")
    # РАЗРЫВ ОСЕЙ: фасад (ранг высокий/важность низкая) и «правда внизу» (ранг низкий/важность ≥8)
    def rank(a):
        return a.get("иерархия", {}).get("ранг") or 99
    if not any(rank(a) <= 2 and (a.get("важность") or 0) <= 5 for a in by_cat["враг"]):
        errs.append("нет фасада: врага с рангом ≤2 и важностью ≤5")
    if not any(rank(a) >= 3 and (a.get("важность") or 0) >= 8 for a in by_cat["враг"]):
        errs.append("правда не внизу: нет врага с рангом ≥3 и важностью ≥8")
    # чеховские ружья и арки
    for a in cast:
        if (a.get("важность") or 0) >= 7 and not a.get("чехов"):
            errs.append(f"важный без чехова: {a.get('роль')} ({a.get('id')})")
        if a.get("категория") not in CATEGORIES:
            errs.append(f"категория неизвестна: {a.get('категория')}")
        if a.get("роль") not in ARCHETYPES:
            errs.append(f"архетип неизвестен: {a.get('роль')}")
    # смутные лица из прошлого: помнит НЕ всех — 2-6 актёров, и НЕ антагониста-в-тени (правда скрыта)
    remembered = [a for a in cast if a.get("память")]
    if not (2 <= len(remembered) <= 6):
        errs.append(f"смутных лиц из прошлого {len(remembered)}, нужно 2-6")
    if any(a.get("роль") == "антагонист-в-тени" for a in remembered):
        errs.append("регрессор НЕ должен помнить антагониста-в-тени — правда добывается")
    if sum(1 for a in cast if a.get("арка")) < MIN_ARCS:
        errs.append(f"арок меньше {MIN_ARCS}")
    entries = b.get("входы") or []
    if not (ENTRY_MIN <= len(entries) <= ENTRY_MAX):
        errs.append(f"входов {len(entries)}, нужно {ENTRY_MIN}-{ENTRY_MAX}")
    if len(b.get("акты") or []) != 3:
        errs.append("актов не 3")
    if not b.get("дельта"):
        errs.append("нет дельты (узлов, где память регрессора врёт)")
    return errs
