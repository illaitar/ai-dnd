"""Обстановка локаций: шаблон зон (данные content/zones.json) + LLM-наполнение предметами.

Зона — часть фактшита здания (docs/locations.md): kind/шум/приватность/вместимость/пост роли.
Объект зоны — ПОЛНОЦЕННЫЙ предмет (фактшит items.normalize) + роли зоны: afford {нужда: рейт},
fixed|loose. Никаких стопок: шесть кружек = шесть записей с живыми различиями.

Слой ПУЛА: furnish_building пишет data["zones"] (building_pool, офлайн-скрипт scripts/furnish.py).
Мир при создании материализует объекты в items/live.db (holder="zone:<bid>/<zid>") без LLM.
LLMFurnisher — единственный рантайм-путь (роль furnisher); заглушек нет (принцип 1).
"""

from __future__ import annotations

import hashlib
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


def _count_for(entry: dict, data: dict, salt: str) -> int:
    """Число инстансов групповой зоны: размер здания задаёт точку в [lo, hi], хэш — дрожь ±1."""
    lo, hi = entry["count"]
    size_ix = {"small": 0.0, "medium": 0.5, "large": 1.0}.get(str(data.get("size")), 0.5)
    base = lo + (hi - lo) * size_ix
    jit = (int(hashlib.md5(salt.encode()).hexdigest(), 16) % 3) - 1
    return max(lo, min(hi, round(base) + jit))


def zones_for(btype: str, data: dict, kind: str = "key") -> list[dict]:
    """Состав зон по типу здания (шаблон = данные). kind: key | res | street.
    Групповые якоря (столы, комнаты постоя) разворачиваются в ИНСТАНСЫ: каждый стол —
    своя зона (атом разговора/приватности), положение (spot) двигает шум/приватность."""
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
    out, i = [], 0

    def _mk(entry, name, noise_d=0.0, priv_d=0.0, group=None):
        nonlocal i
        d = _defaults(entry["kind"])
        z = {"id": f"z{i}", "kind": entry["kind"], "name": name, "post": entry.get("post"),
             "noise": round(max(0.0, min(1.0, d["noise"] + noise_d)), 2),
             "privacy": round(max(0.0, min(1.0, d["privacy"] + priv_d)), 2),
             "cap": entry.get("cap", d["cap"])}
        if entry.get("objects"):                     # уличные зоны: объекты из ДАННЫХ шаблона
            z["objects"] = [dict(o) for o in entry["objects"]]
        if entry.get("lockable"):
            z["lockable"] = True
        if group:
            z["group"] = group                       # инстансы одного якоря (для батч-обстановки)
        out.append(z)
        i += 1

    for entry in tpl:
        if "count" not in entry:
            _mk(entry, entry["name"])
            continue
        n = _count_for(entry, data, f"{btype}|{data.get('name', '')}|{entry['name']}")
        spots = cat["spots"].get(entry.get("spots", ""), [])
        for j in range(n):
            sp = spots[j % len(spots)] if spots else None
            name = f"{entry['name']} {sp['name']}" if sp else f"{entry['name']} {j + 1}"
            _mk(entry, name, sp["noise"] if sp else 0.0, sp["privacy"] if sp else 0.0,
                group=entry["name"])
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


_OBJ_SPEC = (
    "Каждый предмет — ОТДЕЛЬНАЯ запись (шесть кружек = шесть записей, с живыми различиями: "
    "щербатая, треснувшая, с вензелем…). НИКОГДА не объединяй («четыре кружки» — нельзя). "
    "Поля:\n"
    f"name (рус., 1-4 слова); kind (одно из: {'|'.join(ITEM_KINDS)}); material (ПО-РУССКИ: "
    "дуб, глина, чугун…); quality (crude|plain|fine|exquisite); weight (кг, число); "
    "apparent_worth (медяки, видимая цена); worth (истинная, ≥ apparent если есть скрытое); "
    "tags [0-3 слова];\n"
    "fixed (true = не унести: стойка, печь, верстак, кровать, стол; false = переносимое);\n"
    "afford — какие НУЖДЫ предмет закрывает при использовании, {нужда: рейт 0.05-0.3 в час} "
    f"из списка: {', '.join(NEEDS)} (очаг→comfort, еда/питьё→hunger, постель→fatigue, "
    "игра→novelty+social, верстак/орудия→purpose); {} если никаких;\n"
    'hidden — [{"prop": "provenance|cache|history", "value": "...", "fact": "что откроется", '
    '"gate": {"via": "glance|handle|appraise|lore|craft_eye|tool|context|use|expert", '
    '"dc": 10-18}}].\n'
    "Обстановка ЧЕСТНА достатку здания (tier/prosperity): бедному — щербатое и крашеное, "
    "богатому — ладное. Без прозы вне JSON."
)

_FURN_SYS = (
    "Ты — ОБСТАНОВЩИК помещений тёмно-фэнтезийного фронтира (D&D). Дана одна ЗОНА помещения и "
    "фактшит здания. Перечисли предметы обстановки этой зоны: 5-10, крупная мебель + "
    'утварь/мелочь на ней. Верни ТОЛЬКО JSON {"objects": [ ... ]}.\n'
    "СОСТАВ ЗОНЫ ХАРАКТЕРЕН ЕЙ, а не зданию вообще: не больше 2-3 однотипных предметов "
    "(кружек/тарелок) на зону; посуда — там, где едят/пьют, в кабинетах и кладовых её почти "
    "нет — там своё (бумаги, ларцы, инструмент, припасы). "
    "hidden — максимум у ОДНОГО предмета на зону (обычно ни у кого).\n" + _OBJ_SPEC
)

_GROUP_SYS = (
    "Ты — ОБСТАНОВЩИК помещений тёмно-фэнтезийного фронтира (D&D). Даны N ОДНОТИПНЫХ МЕСТ "
    "одной группы (столы зала, игровые столы, комнаты постоя) — каждое место потом живёт "
    "СВОЕЙ группой людей. Верни ТОЛЬКО JSON {\"groups\": [[…], […], …]} — РОВНО N списков "
    "по 2-6 предметов: якорная мебель места (fixed) + утварь на ней.\n"
    "У каждого места СВОЙ характер — по его положению (у окна, в тёмном углу, у очага…) и "
    "следам постояльцев: где-то забытая вещица, где-то заляпанные карты, где-то чисто. "
    "НЕ копируй состав между местами. hidden — максимум у ОДНОГО предмета на ВСЮ группу "
    "(обычно ни у кого).\n" + _OBJ_SPEC
)


def _norm_objects(raw: list, where: str, hidden_budget: int = 1,
                  allow_empty: bool = False) -> list[dict]:
    """Сырые объекты LLM → чистые фактшиты + роли зоны (afford/fixed), кламп тайников."""
    out = []
    for o in raw[:12]:
        if not isinstance(o, dict) or not o.get("name"):
            continue
        if o.get("hidden") and hidden_budget <= 0:
            o = {**o, "hidden": []}
        it = item_normalize(o)
        if it["hidden"]:
            hidden_budget -= 1
        it["fixed"] = bool(o.get("fixed"))
        aff = o.get("afford") if isinstance(o.get("afford"), dict) else {}
        it["afford"] = {k: round(max(0.02, min(0.5, float(v))), 2)
                        for k, v in aff.items()
                        if k in NEEDS and isinstance(v, (int, float))}
        out.append(it)
    if not out and not allow_empty:
        raise LLMBadOutput(f"furnisher: «{where}» — ни одного валидного предмета")
    return out


class LLMFurnisher:
    """Единственный рантайм-путь: роль furnisher — вызов на зону, батч-вызов на группу инстансов."""

    def __init__(self, manager):
        self.manager = manager

    def _bsum(self, data: dict, btype: str) -> str:
        return (f"{data.get('name') or btype} — {btype}; достаток {data.get('tier')}/"
                f"{data.get('prosperity')}; состояние {data.get('condition')}; "
                f"черты: {', '.join(data.get('features') or []) or '—'}; "
                f"запахи: {', '.join(data.get('smells') or []) or '—'}")

    def furnish_zone(self, zone: dict, data: dict, btype: str) -> list[dict]:
        post = f", рабочий пост: {zone['post']}" if zone.get("post") else ""
        user = (f"ЗДАНИЕ: {self._bsum(data, btype)}.\n"
                f"ЗОНА: «{zone['name']}» (тип {zone['kind']}{post}). Обставь её.")
        resp = self.manager.call("furnisher",
                                 [{"role": "system", "content": _FURN_SYS},
                                  {"role": "user", "content": user}],
                                 options={"temperature": 0.7})
        d = _parse_json(resp.get("content"))
        if not d or not isinstance(d.get("objects"), list) or not d["objects"]:
            raise LLMBadOutput(f"furnisher: зона «{zone['name']}» не обставлена")
        return _norm_objects(d["objects"], zone["name"], hidden_budget=1)

    def furnish_group(self, members: list[dict], data: dict, btype: str) -> list[list[dict]]:
        """Инстансы одного якоря (столы/комнаты) — ОДИН батч-вызов на всю группу."""
        names = "; ".join(f"{j + 1}) {m['name']}" for j, m in enumerate(members))
        user = (f"ЗДАНИЕ: {self._bsum(data, btype)}.\n"
                f"МЕСТА ГРУППЫ «{members[0].get('group')}», N={len(members)}: {names}.\n"
                f"Обставь каждое место — ровно {len(members)} списков.")
        resp = self.manager.call("furnisher",
                                 [{"role": "system", "content": _GROUP_SYS},
                                  {"role": "user", "content": user}],
                                 options={"temperature": 0.8})
        d = _parse_json(resp.get("content"))
        gs = d.get("groups") if d else None
        if not isinstance(gs, list) or not gs:
            raise LLMBadOutput(f"furnisher: группа «{members[0].get('group')}» не обставлена")
        gs = (gs + [[] for _ in members])[: len(members)]        # выравниваем к N
        budget = 1                                               # ≤1 тайника на ВСЮ группу
        out = []
        for m, raw in zip(members, gs):
            objs = _norm_objects(raw if isinstance(raw, list) else [], m["name"],
                                 hidden_budget=budget, allow_empty=True)
            budget -= sum(1 for o in objs if o["hidden"])
            out.append(objs)
        if not any(out):
            raise LLMBadOutput(f"furnisher: группа «{members[0].get('group')}» пуста целиком")
        return out


def _zone_for_container(cont: dict, zones: list[dict]) -> str:
    """Ёмкость фактшита получает адрес-зону: по совпадению слов where/имени, иначе storage/первая."""
    hay = f"{cont.get('name', '')} {cont.get('where', '')}".lower()
    for z in zones:
        if z.get("group"):                       # ёмкости — в функциональные зоны, не в инстансы столов
            continue
        toks = [w for w in re.split(r"[^\wа-яё]+", z["name"].lower()) if len(w) > 3]
        if any((t[:5] if len(t) > 5 else t) in hay for t in toks):   # грубый стем: падежи русского
            return z["id"]
    for kind in ("storage", "private"):                  # кладовая прежде кабинета
        for z in zones:
            if z["kind"] == kind:
                return z["id"]
    return zones[0]["id"] if zones else "z0"


_LAYOUT_SYS = (
    "Ты — архитектор планировки одного помещения тёмно-фэнтезийного фронтира. По фактшиту "
    "здания выбери дух планировки. Верни ТОЛЬКО JSON: "
    '{"windows": "left|right|both|none", "bar_wall": "left|right", '
    '"tables": "rows|perimeter|mixed", "density": "airy|normal|packed"}. '
    "Бедное/тесное — packed и мало окон; просторное/богатое — airy; постоялые дворы чаще "
    "rows, злачные места — perimeter (центр свободен). Без прозы вне JSON."
)


def layout_params(data: dict, btype: str, manager) -> dict:
    """Архитектурный пресет здания [LLM] → кламп enum'ами (геометрию всё равно строит код)."""
    from .floorplan import clamp_layout
    resp = manager.call("layout_architect",
                        [{"role": "system", "content": _LAYOUT_SYS},
                         {"role": "user", "content":
                          f"ЗДАНИЕ: {data.get('name') or btype} — {btype}; "
                          f"достаток {data.get('tier')}/{data.get('prosperity')}; "
                          f"размер {data.get('size')}; свет {data.get('lighting')}."}],
                        options={"temperature": 0.6})
    return clamp_layout(_parse_json(resp.get("content")))


def furnish_building(data: dict, btype: str, manager, kind: str = "key") -> dict:
    """Полная обстановка здания: зоны из шаблона + LLM-предметы + адресация ёмкостей.
    Инстансы одной группы (столы) обставляются ОДНИМ батч-вызовом — дёшево и разнообразно.
    Мутирует и возвращает data (пишется в building_pool офлайн-скриптом)."""
    zones = zones_for(btype, data, kind)
    data["layout"] = layout_params(data, btype, manager)
    furn = LLMFurnisher(manager)
    done: set[str] = set()
    for z in zones:
        grp = z.get("group")
        if not grp:
            z["objects"] = furn.furnish_zone(z, data, btype)
        elif grp not in done:
            members = [x for x in zones if x.get("group") == grp]
            packs = furn.furnish_group(members, data, btype)
            for m, objs in zip(members, packs):
                m["objects"] = objs
            done.add(grp)
    for c in data.get("containers") or []:
        c["zone"] = _zone_for_container(c, zones)
    data["zones"] = zones
    return data
