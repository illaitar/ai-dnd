"""Левел-ап: какие выборы нужны на уровне и сборка готового payload для level_up.

Чистые функции над таблицами rules/progression. Сессия валидирует выбор игрока и
коммитит событие level_up (его применяет world._h_level_up — детерминированно).
"""

from __future__ import annotations

from ..combat.spells import SPELLS
from ..rules.progression import (
    ABIL_RU,
    CLASSES,
    FEATS,
    FIGHTING_STYLES,
    PROF_BY_LEVEL,
    SKILL_RU,
    SUBCLASSES,
    available_spells,
    hp_gain,
    slots_for,
    spells_to_learn,
)
from ..rules.srd import ability_modifier

ABILS = ["str", "dex", "con", "int", "wis", "cha"]


def choices_for(class_id: str, level: int, st, prog) -> list[dict]:
    """Незакрытые выборы для повышения до `level` (для UI)."""
    cls = CLASSES.get(class_id)
    if not cls:
        return []
    out = []
    for _fid, kind in cls["features"].get(level, []):
        if not kind:
            continue
        if kind == "fighting_style":
            out.append({"id": "fighting_style", "label": "Боевой стиль", "pick": 1,
                        "options": [{"id": k, "name": v["name"], "desc": v["desc"]}
                                    for k, v in FIGHTING_STYLES.items()]})
        elif kind == "subclass":
            out.append({"id": "subclass", "label": "Архетип / подкласс", "pick": 1,
                        "options": [{"id": k, "name": v["name"], "desc": v["desc"]}
                                    for k, v in SUBCLASSES.get(class_id, {}).items()]})
        elif kind == "expertise":
            out.append({"id": "expertise", "label": "Компетентность (×2 мастерство), выбрать 2",
                        "pick": 2, "options": [{"id": s, "name": SKILL_RU.get(s, s)}
                                               for s in st.proficient_skills]})
        elif kind == "asi":
            opts = [{"id": f"asi:{a}", "name": f"+2 к {ABIL_RU[a]}", "desc": ""} for a in ABILS]
            opts += [{"id": f"feat:{k}", "name": "Черта: " + v["name"], "desc": v["desc"]}
                     for k, v in FEATS.items()]
            out.append({"id": "asi", "label": "Рост характеристик или черта", "pick": 1, "options": opts})
        elif kind == "spells":
            n = spells_to_learn(class_id, level)
            known = set(prog.spells_known)
            avail = [s for s in available_spells(class_id, level) if s not in known]
            pick = min(n, len(avail))
            if pick > 0:
                out.append({"id": "spells", "label": f"Изучить заклинания (выбрать {pick})",
                            "pick": pick, "options": [{"id": s, "name": SPELLS[s].name,
                                                       "desc": f"{SPELLS[s].level} круг"} for s in avail]})
    return out


LIST_CHOICES = {"spells", "expertise"}            # выбираются списком (чекбоксы), даже если 1


def validate(needed: list[dict], sel: dict) -> str | None:
    """Вернуть текст ошибки, если выбор неполный/некорректный, иначе None."""
    for ch in needed:
        got = sel.get(ch["id"])
        if ch["id"] in LIST_CHOICES or ch["pick"] > 1:
            if not isinstance(got, list) or len(got) != ch["pick"]:
                return f"Нужно выбрать {ch['pick']}: {ch['label']}"
        elif not isinstance(got, str) or not got:
            return f"Не выбрано: {ch['label']}"
    return None


def build_payload(class_id: str, level: int, st, prog, sel: dict) -> dict:
    """Собрать готовый (разрешённый) payload для события level_up."""
    cls = CLASSES[class_id]
    con_mod = ability_modifier(st.con)
    payload = {"new_level": level, "proficiency": PROF_BY_LEVEL.get(level, st.proficiency),
               "hp_gain": hp_gain(cls["hit_die"], con_mod)}
    # автоматические фичи этого уровня (без выбора)
    payload["add_features"] = [fid for fid, kind in cls["features"].get(level, []) if not kind]
    if sel.get("fighting_style"):
        payload["fighting_style"] = sel["fighting_style"]
        payload["add_features"].append("fighting_style")
    if sel.get("subclass"):
        payload["subclass"] = sel["subclass"]
    if sel.get("expertise"):
        payload["expertise"] = list(sel["expertise"])
    if sel.get("asi"):
        choice = sel["asi"]
        if choice.startswith("asi:"):
            payload["asi"] = {choice.split(":", 1)[1]: 2}
        elif choice.startswith("feat:"):
            ft = choice.split(":", 1)[1]
            payload["feats"] = [ft]
            if ft == "tough":
                payload["hp_gain"] += 2 * level
            elif ft == "athlete":
                payload["asi"] = {"str": 1}
    if sel.get("spells"):
        payload["add_spells"] = list(sel["spells"])
    if cls.get("caster"):
        payload["slots"] = slots_for(class_id, level)
        payload["spell_ability"] = cls["caster"]
    return payload
