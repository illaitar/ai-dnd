"""Обстановка локаций: шаблон зон (данные content/zones.json) + LLM-наполнение предметами.

Зона — часть фактшита здания (docs/locations.md): kind/шум/приватность/вместимость/пост роли.
Объект зоны — ПОЛНОЦЕННЫЙ предмет (фактшит items.normalize) + роли зоны: afford {нужда: рейт},
fixed|loose. Никаких стопок: шесть кружек = шесть записей с живыми различиями.

Слой ПУЛА: furnish_building пишет data["zones"] (building_pool, офлайн-скрипт scripts/furnish.py).
Мир при создании материализует объекты в items/live.db (holder="zone:<bid>/<zid>") без LLM.
LLMFurnisher — единственный рантайм-путь (роль furnisher); заглушек нет (принцип 1).
"""

from __future__ import annotations

import json
import os
import re

from ..inference import LLMBadOutput
from ..items.model import KINDS as ITEM_KINDS
from ..items.model import normalize as item_normalize

NEEDS = ("fatigue", "hunger", "social", "purpose", "wealth", "comfort", "novelty")

_CATALOG: dict | None = None


def zone_catalog() -> dict:
    global _CATALOG
    if _CATALOG is None:
        p = os.path.join(os.path.dirname(__file__), "..", "content", "zones.json")
        with open(p, encoding="utf-8") as f:
            _CATALOG = json.load(f)
    return _CATALOG


def _defaults(kind: str) -> dict:
    return zone_catalog()["kinds"].get(kind, {"noise": 0.4, "privacy": 0.3, "cap": 4})


def zones_for(btype: str, data: dict, kind: str = "key") -> list[dict]:
    """Состав зон по типу здания (шаблон = данные). kind: key | res | street."""
    cat = zone_catalog()
    hay = f"{btype} {data.get('type', '')} {data.get('name', '')}".lower()
    tpl = None
    if kind == "res":
        tpl = cat["residential"]
    elif kind == "street":
        for t in cat["street"]:
            if any(m in hay for m in t["match"] if m) or t["match"] == [""]:
                tpl = t["zones"]
                break
    else:
        for t in cat["templates"]:
            if any(m in hay for m in t["match"]):
                tpl = t["zones"]
                break
        tpl = tpl or cat["generic_key"]
    out = []
    for i, z in enumerate(tpl):
        out.append({"id": f"z{i}", "kind": z["kind"], "name": z["name"],
                    "post": z.get("post"), **_defaults(z["kind"])})
    return out


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


_FURN_SYS = (
    "Ты — ОБСТАНОВЩИК помещений тёмно-фэнтезийного фронтира (D&D). Дана одна ЗОНА помещения и "
    "фактшит здания. Перечисли предметы обстановки этой зоны — КАЖДЫЙ отдельной записью "
    "(шесть кружек = шесть записей, с живыми различиями: щербатая, треснувшая, с вензелем…). "
    "5-10 предметов: крупная мебель зоны + утварь/мелочь на ней. Верни ТОЛЬКО JSON "
    '{"objects": [ ... ]}, каждый объект:\n'
    f"name (рус., 1-4 слова); kind (одно из: {'|'.join(ITEM_KINDS)}); material (ПО-РУССКИ: "
    "дуб, глина, чугун…); quality (crude|plain|fine|exquisite); weight (кг, число); "
    "apparent_worth (медяки, видимая цена); worth (истинная, ≥ apparent если есть скрытое); "
    "tags [0-3 слова];\n"
    "fixed (true = не унести: стойка, печь, верстак, кровать; false = переносимое);\n"
    "afford — какие НУЖДЫ предмет закрывает при использовании, {нужда: рейт 0.05-0.3 в час} "
    f"из списка: {', '.join(NEEDS)} (очаг→comfort, еда/питьё→hunger, постель→fatigue, "
    "игра→novelty+social, верстак/орудия→purpose); {} если никаких;\n"
    "hidden — МАКСИМУМ У ОДНОГО предмета НА ВСЮ зону (обычно ни у кого): "
    '[{"prop": "provenance|cache|history", "value": "...", "fact": "что откроется", '
    '"gate": {"via": "glance|handle|appraise|lore|craft_eye|tool|context|use|expert", '
    '"dc": 10-18}}].\n'
    "СОСТАВ ЗОНЫ ХАРАКТЕРЕН ЕЙ, а не зданию вообще: не больше 2-3 однотипных предметов "
    "(кружек/тарелок) на зону; посуда — там, где едят/пьют, в кабинетах и кладовых её почти "
    "нет — там своё (бумаги, ларцы, инструмент, припасы). "
    "Обстановка ЧЕСТНА достатку здания (tier/prosperity): бедному — щербатое и крашеное, "
    "богатому — ладное. Без прозы вне JSON."
)


class LLMFurnisher:
    """Единственный рантайм-путь: роль furnisher, один вызов на зону."""

    def __init__(self, manager):
        self.manager = manager

    def furnish_zone(self, zone: dict, data: dict, btype: str) -> list[dict]:
        b = (f"{data.get('name') or btype} — {btype}; достаток {data.get('tier')}/"
             f"{data.get('prosperity')}; состояние {data.get('condition')}; "
             f"черты: {', '.join(data.get('features') or []) or '—'}; "
             f"запахи: {', '.join(data.get('smells') or []) or '—'}")
        post = f", рабочий пост: {zone['post']}" if zone.get("post") else ""
        user = f"ЗДАНИЕ: {b}.\nЗОНА: «{zone['name']}» (тип {zone['kind']}{post}). Обставь её."
        resp = self.manager.call("furnisher",
                                 [{"role": "system", "content": _FURN_SYS},
                                  {"role": "user", "content": user}],
                                 options={"temperature": 0.7})
        d = _parse_json(resp.get("content"))
        if not d or not isinstance(d.get("objects"), list) or not d["objects"]:
            raise LLMBadOutput(f"furnisher: зона «{zone['name']}» не обставлена")
        out, hidden_used = [], False
        for o in d["objects"][:12]:
            if not isinstance(o, dict) or not o.get("name"):
                continue
            if o.get("hidden") and hidden_used:                 # ≤1 тайника на зону — клампим
                o = {**o, "hidden": []}
            it = item_normalize(o)
            if it["hidden"]:
                hidden_used = True
            it["fixed"] = bool(o.get("fixed"))
            aff = o.get("afford") if isinstance(o.get("afford"), dict) else {}
            it["afford"] = {k: round(max(0.02, min(0.5, float(v))), 2)
                            for k, v in aff.items()
                            if k in NEEDS and isinstance(v, (int, float))}
            out.append(it)
        if not out:
            raise LLMBadOutput(f"furnisher: зона «{zone['name']}» — ни одного валидного предмета")
        return out


def _zone_for_container(cont: dict, zones: list[dict]) -> str:
    """Ёмкость фактшита получает адрес-зону: по совпадению слов where/имени, иначе storage/первая."""
    hay = f"{cont.get('name', '')} {cont.get('where', '')}".lower()
    for z in zones:
        toks = [w for w in re.split(r"[^\wа-яё]+", z["name"].lower()) if len(w) > 3]
        if any((t[:5] if len(t) > 5 else t) in hay for t in toks):   # грубый стем: падежи русского
            return z["id"]
    for kind in ("storage", "private"):                  # кладовая прежде кабинета
        for z in zones:
            if z["kind"] == kind:
                return z["id"]
    return zones[0]["id"] if zones else "z0"


def furnish_building(data: dict, btype: str, manager, kind: str = "key") -> dict:
    """Полная обстановка здания: зоны из шаблона + LLM-предметы + адресация ёмкостей.
    Мутирует и возвращает data (пишется в building_pool офлайн-скриптом)."""
    zones = zones_for(btype, data, kind)
    furn = LLMFurnisher(manager)
    for z in zones:
        z["objects"] = furn.furnish_zone(z, data, btype)
    for c in data.get("containers") or []:
        c["zone"] = _zone_for_container(c, zones)
    data["zones"] = zones
    return data
