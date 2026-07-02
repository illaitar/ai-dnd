"""Инскрипция: LLM вписывает круг в ЗАКОНЫ мира (роль А) и разыгрывает ДИКУЮ магию (роль Б).

Роль А — чистый круг уже механически определён грамматикой (build_spec); LLM лишь ИМЕНУЕТ его и даёт
флейвор. Результат кэшируется в гримуаре-на-мир по хэшу состава: первое творение вписывает закон, дальше
имя стабильно. Роль Б — противоречивый/сорванный круг: LLM выбирает исход из ОГРАНИЧЕННОГО меню эффектов
(нельзя сломать мир) и пишет, как это выглядит. См. docs/MAGIC.md.

LLMInscriber — реальный путь (роли spell_scribe/wild_magic → deepseek); StubInscriber — офлайн/тесты.
"""

from __future__ import annotations

import hashlib
import json
import re

from .grammar import load

# исходы дикой магии — механически безопасное меню (маг. хаос ограничен этим списком) --------
WILD_EFFECTS = ("backfire", "nothing", "scorch", "warp", "boon")


def circle_hash(comp) -> str:
    """Стабильный ключ круга по составу (порядок черчения не важен)."""
    key = "|".join(sorted(str(c) for c in comp))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _ru_names(comp) -> str:
    g = load()
    return ", ".join(g["all"].get(c, {}).get("ru", c) for c in comp)


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
    "Ты — ЗАКОНОПИСЕЦ магии тёмно-фэнтезийного фронтира (D&D в духе Witch Hat Atelier). Игрок начертил "
    "ЧИСТЫЙ круг из глифов; его механика уже определена. Твоя задача — ВПИСАТЬ его в законы мира: дать имя и "
    "флейвор. Верни ТОЛЬКО JSON: name (краткое звучное имя заклинания, на русском, 1-3 слова, без кавычек); "
    "flavor (одна фраза — суть/школа, на русском); sensory (одна фраза — КАК это выглядит при сотворении, "
    "на русском). КОРОТКО, без прозы и списков. Опирайся на состав глифов и эффект, не противоречь механике."
)

_WILD_SYS = (
    "Ты — ДИКАЯ МАГИЯ тёмно-фэнтезийного фронтира (D&D). Круг сорвался (противоречие стихий/форм или дрогнула "
    "рука). Исход НЕПРЕДСКАЗУЕМ, но должен уложиться в меню. Верни ТОЛЬКО JSON: effect (строго одно из: "
    "backfire — отдача калечит мага; nothing — круг гаснет впустую; scorch — выброс стихии по округе; "
    "warp — искажает мага/место странным образом; boon — нежданная удача); magnitude (целое 1-3, сила исхода); "
    "element (стихия выброса из: огонь|лёд|яд|свет|тьма|камень — или пустая строка); text (одна-две фразы "
    "на русском: ярко, зловеще-иронично, КАК это выглядит). БЕЗ пояснений вне JSON."
)


class Inscriber:
    def name_circle(self, comp, spec: dict) -> dict | None:      # роль А
        raise NotImplementedError

    def wild(self, comp, reason: str, in_combat: bool) -> dict | None:  # роль Б
        raise NotImplementedError


class StubInscriber(Inscriber):
    """Детерминированная заглушка (офлайн/тесты) — имя из глифов, отдача по-умолчанию."""

    def name_circle(self, comp, spec: dict) -> dict:
        names = _ru_names(comp)
        return {"name": names.split(",")[0].strip().capitalize() or "Безымянный круг",
                "flavor": f"круг из глифов: {names}", "sensory": "линии вспыхивают и складываются в фигуру"}

    def wild(self, comp, reason: str, in_combat: bool) -> dict:
        n = 1 + (len(comp) % 3)
        return {"effect": "backfire", "magnitude": n, "element": "",
                "text": f"Круг рвётся вразнос — {reason}. Отдача бьёт по чертящему."}


class LLMInscriber(Inscriber):
    """Реальный путь: роль spell_scribe именует закон, wild_magic разыгрывает хаос."""

    def __init__(self, manager):
        self.manager = manager

    def name_circle(self, comp, spec: dict) -> dict | None:
        if not self.manager.available():
            return None
        eff = {k: spec.get(k) for k in ("damage", "area", "heal", "status", "reveal", "unlock", "range")
               if spec.get(k)}
        user = (f"Глифы круга: {_ru_names(comp)}. Механика (для опоры, не пересказывай дословно): "
                f"{json.dumps(eff, ensure_ascii=False)}. Впиши закон — дай имя и флейвор.")
        resp = self.manager.call("spell_scribe", [{"role": "system", "content": _SCRIBE_SYS},
                                                  {"role": "user", "content": user}],
                                 options={"temperature": 0.8})
        d = _parse_json(resp.get("content") if resp else None)
        if not d or not d.get("name"):
            return None
        return {"name": str(d["name"])[:40], "flavor": str(d.get("flavor", ""))[:120],
                "sensory": str(d.get("sensory", ""))[:120]}

    def wild(self, comp, reason: str, in_combat: bool) -> dict | None:
        if not self.manager.available():
            return None
        user = (f"Глифы сорванного круга: {_ru_names(comp)}. Причина срыва: {reason}. "
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
