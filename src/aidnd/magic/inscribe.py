"""Инскрипция: LLM «проявляет» чистый круг в ЗАКОН мира (роль А) и разыгрывает ДИКУЮ магию (роль Б).

Роль А — законописец: получает РИСУНОК круга (глифы × размер × положение × кольца) и правила
геометрии; выдаёт закон ЦЕЛИКОМ — суть (kind, свободная!), силу, цель, механику. Freeform: полёт,
иллюзия, туман, свет — что угодно, что честно следует из рисунка. Сервер КЛАМПИТ закон по бюджету
силы (power_budget) — LLM свободен в сути, но не в мощности. Кэш в гримуаре-на-мир по хэшу рисунка.
Роль Б — сорванный круг: исход из ОГРАНИЧЕННОГО меню (мир не сломать). См. docs/MAGIC.md.

LLMInscriber — реальный путь (роли spell_scribe/wild_magic → deepseek); StubInscriber — офлайн/тесты.
"""

from __future__ import annotations

import json
import re

from .grammar import RULES_RU, anchor, describe, fallback_law, load, power_budget

# исходы дикой магии — механически безопасное меню (маг. хаос ограничен этим списком) --------
WILD_EFFECTS = ("backfire", "nothing", "scorch", "warp", "boon")

# свободные виды законов — подсказка законописцу (список открыт: kind может быть и иным словом)
LAW_KINDS = ("damage", "heal", "status", "ward", "light", "reveal", "unlock", "illusion",
             "movement", "environment", "communication", "conjure", "other")


def _parse_json(text: str | None) -> dict | None:
    if not text:
        return None
    t = re.sub(r"```$", "", re.sub(r"^```(?:json)?", "", text.strip()).strip()).strip()
    try:
        return json.loads(t)
    except (json.JSONDecodeError, ValueError):
        i, j = t.find("{"), t.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(t[i:j + 1])
            except (json.JSONDecodeError, ValueError):
                return None
    return None


_SCRIBE_SYS = (
    "Ты — ЗАКОНОПИСЕЦ магии тёмно-фэнтезийного фронтира (D&D в духе Witch Hat Atelier). Маг начертил "
    "ЧИСТЫЙ круг; тебе дан его РИСУНОК и правила геометрии. ПРОЯВИ круг в закон мира: что он ДЕЛАЕТ — "
    "выведи ЧЕСТНО из состава, размеров, положений и колец. Суть свободна (полёт, туман, свет, иллюзия, "
    "оковы — что следует из рисунка), но СИЛА строго в бюджете. Верни ТОЛЬКО JSON:\n"
    "name (звучное имя, рус., 1-3 слова); flavor (одна фраза — школа/суть); sensory (одна фраза — как "
    f"выглядит сотворение); kind (одно слово, напр. {', '.join(LAW_KINDS)}); power (целое 1..бюджет); "
    "target (self|touch|single|area|zone); range (клетки, 1..12); duration (раунды/минуты, 1..20); "
    "law (одна фраза: ЧТО делает круг — как закон, без «может»); taboo (true если закон тёмный/вредящий); "
    "mech — БОЕВАЯ механика, если применимо (иначе {}): {dice ('NdM', N≤power), dmg_type "
    "(fire|cold|poison|radiant|necrotic|bludgeoning), heal (целое ≤ 2×power), status {kind "
    "(bound|asleep|afraid), turns ≤ duration}, aoe {shape (burst|cloud|cone|wall), radius ≤ 1+power/3}, "
    "light|reveal|unlock (true)}. КОРОТКО, без прозы вне JSON. Магнитуды — ПРОПОРЦИОНАЛЬНЫ рисунку: "
    "крупный глиф — весомее, внутреннее кольцо — оттенок, обращение круга задаёт цель (на себя/вовне/вокруг)."
)

_WILD_SYS = (
    "Ты — ДИКАЯ МАГИЯ тёмно-фэнтезийного фронтира (D&D). Круг сорвался (противоречие в рисунке или "
    "свеча погасла на середине). Исход НЕПРЕДСКАЗУЕМ, но должен уложиться в меню. Верни ТОЛЬКО JSON: "
    "effect (строго одно из: backfire — отдача калечит мага; nothing — круг гаснет впустую; scorch — "
    "выброс стихии по округе; warp — искажает мага/место странным образом; boon — нежданная удача); "
    "magnitude (целое 1-3, сила исхода); element (стихия выброса из: огонь|лёд|яд|свет|тьма|камень — "
    "или пустая строка); text (одна-две фразы на русском: ярко, зловеще-иронично, КАК это выглядит). "
    "БЕЗ пояснений вне JSON."
)


def clamp_law(d: dict, comp) -> dict:
    """Закон LLM → в рамки бюджета рисунка (LLM свободен в сути, но не в мощности)."""
    budget = max(1, round(power_budget(comp)))
    law = dict(fallback_law(comp))                          # скелет: недостающее — из фоллбэка
    law["name"] = str(d.get("name") or law["name"])[:40]
    for k in ("flavor", "sensory", "law", "kind", "target"):
        if d.get(k):
            law[k] = str(d[k])[:160]
    law["taboo"] = bool(d.get("taboo", law.get("taboo")))
    try:
        law["power"] = max(1, min(budget, int(d.get("power", law["power"]))))
    except (TypeError, ValueError):
        law["power"] = min(budget, law["power"])
    try:
        law["range"] = max(1, min(12, int(d.get("range", law["range"]))))
        law["duration"] = max(1, min(20, int(d.get("duration", law["duration"]))))
    except (TypeError, ValueError):
        pass
    m = d.get("mech") if isinstance(d.get("mech"), dict) else {}
    mech: dict = {}
    dice = str(m.get("dice") or "")
    if re.fullmatch(r"\d{1,2}d\d{1,2}", dice):
        n, faces = dice.split("d")
        mech["damage"] = {"dice": f"{max(1, min(law['power'], int(n)))}d{max(2, min(8, int(faces)))}",
                          "type": m.get("dmg_type") if m.get("dmg_type") in
                          ("fire", "cold", "poison", "radiant", "necrotic", "bludgeoning") else "fire"}
    if m.get("heal"):
        try:
            mech["heal"] = max(1, min(2 * law["power"], int(m["heal"])))
        except (TypeError, ValueError):
            pass
    st = m.get("status") if isinstance(m.get("status"), dict) else None
    if st and st.get("kind") in ("bound", "asleep", "afraid"):
        try:
            mech["status"] = {"kind": st["kind"], "turns": max(1, min(law["duration"], int(st.get("turns", 1))))}
        except (TypeError, ValueError):
            mech["status"] = {"kind": st["kind"], "turns": 1}
    ao = m.get("aoe") if isinstance(m.get("aoe"), dict) else None
    if ao and ao.get("shape") in ("burst", "cloud", "cone", "wall"):
        try:
            mech["aoe"] = {"shape": ao["shape"], "radius": max(1, min(1 + law["power"] // 3, int(ao.get("radius", 1))))}
        except (TypeError, ValueError):
            mech["aoe"] = {"shape": ao["shape"], "radius": 1}
    for flag in ("light", "reveal", "unlock"):
        if m.get(flag):
            mech[flag] = True
    if mech or "mech" in d:                                 # LLM дал механику (пусть и пустую) — верим ей
        law["mech"] = mech
    return law


class Inscriber:
    def scribe_law(self, comp, cls: dict) -> dict | None:        # роль А: рисунок → закон
        raise NotImplementedError

    def wild(self, comp, reason: str, in_combat: bool) -> dict | None:  # роль Б
        raise NotImplementedError


class StubInscriber(Inscriber):
    """Детерминированная заглушка (офлайн/тесты) — закон из fallback_law, отдача по-умолчанию."""

    def scribe_law(self, comp, cls: dict) -> dict:
        return fallback_law(comp)

    def wild(self, comp, reason: str, in_combat: bool) -> dict:
        n = 1 + (len(list(comp)) % 3)
        return {"effect": "backfire", "magnitude": n, "element": "",
                "text": f"Круг рвётся вразнос — {reason}. Отдача бьёт по чертящему."}


class LLMInscriber(Inscriber):
    """Реальный путь: роль spell_scribe проявляет закон, wild_magic разыгрывает хаос."""

    def __init__(self, manager):
        self.manager = manager

    def scribe_law(self, comp, cls: dict) -> dict | None:
        if not self.manager.available():
            return None
        g = load()
        gloss = "; ".join(f"{e['ru']} — {e.get('flavor') or e.get('verb') or e.get('shape') or e.get('mod')}"
                          for e in g["all"].values())
        user = (f"{RULES_RU}\nСЛОВАРЬ ГЛИФОВ: {gloss}.\nРИСУНОК КРУГА: {describe(comp)}\n"
                f"Обращение: {anchor(comp)}. Проявь закон этого круга.")
        resp = self.manager.call("spell_scribe", [{"role": "system", "content": _SCRIBE_SYS},
                                                  {"role": "user", "content": user}],
                                 options={"temperature": 0.8})
        d = _parse_json(resp.get("content") if resp else None)
        if not d or not d.get("name"):
            return None
        return clamp_law(d, comp)

    def wild(self, comp, reason: str, in_combat: bool) -> dict | None:
        if not self.manager.available():
            return None
        user = (f"Рисунок сорванного круга: {describe(comp)}. Причина срыва: {reason}. "
                f"{'Маг в бою.' if in_combat else 'Боя нет.'} Разыграй дикий исход.")
        resp = self.manager.call("wild_magic", [{"role": "system", "content": _WILD_SYS},
                                                {"role": "user", "content": user}],
                                 options={"temperature": 1.0})
        d = _parse_json(resp.get("content") if resp else None)
        if not d:
            return None
        eff = d.get("effect")
        if eff not in WILD_EFFECTS:
            eff = "backfire"
        elem = str(d.get("element") or "")
        if elem not in load()["elements"]:
            elem = ""
        try:
            mag = max(1, min(3, int(d.get("magnitude", 1))))
        except (TypeError, ValueError):
            mag = 1
        return {"effect": eff, "magnitude": mag, "element": elem,
                "text": str(d.get("text", ""))[:200] or f"Круг идёт вразнос — {reason}."}
