"""Модуль использования LLM для насыщения локаций — ОТДЕЛЬНЫЙ от скрипта генерации.

Описание здания = ФАКТШИТ ХАРАКТЕРИСТИК (теги/энумы/короткие фразы), НЕ проза: прозу нарратор
соберёт в рантайме из этих фактов. Один вызов на здание (суб-помещения инлайн). Обезличенно —
людей не выдумываем (NPC отдельным пассом), роли — в occupants_kind.

LLMEnricher — реальный путь; StubEnricher — детерминированная заглушка (офлайн/тесты).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

SERVICES = ("eat", "drink", "lodging", "shop", "commission", "heal", "pray", "store")
TIERS = ("poor", "modest", "comfortable", "wealthy")
SIZES = ("small", "medium", "large")
AGES = ("new", "established", "old", "ancient")
CONDITIONS = ("pristine", "sound", "worn", "dilapidated")
LIGHTING = ("dark", "dim", "firelit", "bright")
TRAFFIC = ("quiet", "moderate", "busy")
PROSPERITY = ("struggling", "stable", "thriving")
REPUTATION = ("respected", "neutral", "dubious", "shady")
ROOM_KINDS = ("cellar", "backroom", "attic", "quarters", "hidden")
ROOM_ACCESS = ("public", "staff", "locked", "hidden")
CONTAINER_KINDS = ("chest", "cupboard", "crate", "barrel", "strongbox", "lockbox",
                   "cabinet", "cache", "shelf", "sack")
CONTAINER_ACCESS = ("public", "locked")


@dataclass
class BuildingCtx:
    id: str
    name_hint: str
    role_hint: str
    landmarks: list[str] = field(default_factory=list)
    region: str = "фронтир Фэндалина"


_BUILD_SYS = (
    "Ты — генератор ХАРАКТЕРИСТИК зданий для тёмно-фэнтезийного фронтирного городка (D&D, Фэндалин). "
    "По краткой подсказке верни ТОЛЬКО JSON-фактшит — КОРОТКО, теги/энумы/короткие фразы, БЕЗ прозы и "
    "абзацев-описаний (прозу соберёт нарратор). ОБЕЗЛИЧЕННО: не выдумывай и не называй людей (NPC отдельно), "
    "роли — в occupants_kind. Поля:\n"
    "type — тип; tier (poor|modest|comfortable|wealthy); size (small|medium|large); floors (число 1-3); "
    "age (new|established|old|ancient); condition (pristine|sound|worn|dilapidated); "
    "materials {walls, roof}; features (массив коротких факт-тегов: дверь/очаг/балки/ставни…); "
    "smells (массив); sounds (массив); lighting (dark|dim|firelit|bright); "
    "services (массив из [eat,drink,lodging,shop,commission,heal,pray,store]; ПУСТО для жилого дома); "
    "wares (массив товаров — для лавок); hours (короткая фраза); foot_traffic (quiet|moderate|busy); "
    "occupants_kind (роли без имён); prosperity (struggling|stable|thriving); "
    "reputation (respected|neutral|dubious|shady); notable (одна короткая деталь места); "
    "secret ({what, where, gate} или null); valuables (массив — что украсть); rumors (массив коротких зацепок); "
    "sub_rooms (массив {name, kind:(cellar|backroom|attic|quarters|hidden), access:(public|staff|locked|hidden), "
    "features:[...], contents:[...]}; 0-4, у жилого дома 0-1); "
    "containers (массив ЁМКОСТЕЙ 0-5: {name, kind:(chest|cupboard|crate|barrel|strongbox|lockbox|cabinet|cache|"
    "shelf|sack), where:(где стоит), access:(public|locked), contents:[что внутри], key:{name, note}}; "
    "PUBLIC открыты всем; LOCKED ОБЯЗАТЕЛЬНО с key — предметом-открывашкой (именной ключ/замо́к хозяина), "
    "в locked держат ценное/личное).\n"
    "ВАЖНО ПРО ЯЗЫК: энум-поля (tier/size/age/condition/lighting/foot_traffic/prosperity/reputation/services, "
    "kind/access у помещений и ёмкостей) — строго АНГЛ. ключи из списков выше. ВСЁ остальное (type, features, "
    "smells, sounds, wares, occupants_kind, notable, secret, valuables, rumors, имена помещений/ёмкостей/ключей, "
    "where, contents) — НА РУССКОМ, короткими естественными фразами, БЕЗ snake_case и англицизмов."
)


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


def _enum(v, allowed, default):
    return v if v in allowed else default


def _list(v):
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    return []


def _container(c) -> dict | None:
    """Ёмкость здания. Для LOCKED гарантируем key — предмет-открывашку (иначе синтезируем именной ключ)."""
    if not isinstance(c, dict) or not str(c.get("name") or "").strip():
        return None
    name = str(c["name"]).strip()
    access = _enum(c.get("access"), CONTAINER_ACCESS, "public")
    key = None
    if access == "locked":
        k = c.get("key") if isinstance(c.get("key"), dict) else {}
        key = {"name": str(k.get("name") or "").strip() or f"ключ от «{name}»",
               "note": str(k.get("note") or "").strip()}
    return {"name": name, "kind": _enum(c.get("kind"), CONTAINER_KINDS, "chest"),
            "where": str(c.get("where") or "").strip(), "access": access,
            "contents": _list(c.get("contents")), "key": key}


def _norm_building(d: dict) -> dict:
    subs = []
    for s in (d.get("sub_rooms") or [])[:4]:
        if not isinstance(s, dict) or not s.get("name"):
            continue
        subs.append({"name": str(s["name"]).strip(),
                     "kind": _enum(s.get("kind"), ROOM_KINDS, "backroom"),
                     "access": _enum(s.get("access"), ROOM_ACCESS, "public"),
                     "features": _list(s.get("features")), "contents": _list(s.get("contents"))})
    mat = d.get("materials") if isinstance(d.get("materials"), dict) else {}
    secret = d.get("secret") if isinstance(d.get("secret"), dict) and d["secret"].get("what") else None
    try:
        floors = max(1, min(4, int(d.get("floors", 1))))
    except (TypeError, ValueError):
        floors = 1
    return {
        "type": str(d.get("type") or "").strip(),
        "tier": _enum(d.get("tier"), TIERS, "modest"), "size": _enum(d.get("size"), SIZES, "small"),
        "floors": floors, "age": _enum(d.get("age"), AGES, "established"),
        "condition": _enum(d.get("condition"), CONDITIONS, "sound"),
        "materials": {"walls": str(mat.get("walls", "") or ""), "roof": str(mat.get("roof", "") or "")},
        "features": _list(d.get("features")), "smells": _list(d.get("smells")), "sounds": _list(d.get("sounds")),
        "lighting": _enum(d.get("lighting"), LIGHTING, "dim"),
        "services": [s for s in _list(d.get("services")) if s in SERVICES],
        "wares": _list(d.get("wares")), "hours": str(d.get("hours") or "").strip(),
        "foot_traffic": _enum(d.get("foot_traffic"), TRAFFIC, "moderate"),
        "occupants_kind": (", ".join(str(x) for x in d["occupants_kind"])
                           if isinstance(d.get("occupants_kind"), list)
                           else str(d.get("occupants_kind") or "")).strip(),
        "prosperity": _enum(d.get("prosperity"), PROSPERITY, "stable"),
        "reputation": _enum(d.get("reputation"), REPUTATION, "neutral"),
        "notable": str(d.get("notable") or "").strip(),
        "secret": ({"what": str(secret.get("what", "")), "where": str(secret.get("where", "")),
                    "gate": str(secret.get("gate", ""))} if secret else None),
        "valuables": _list(d.get("valuables")), "rumors": _list(d.get("rumors")), "sub_rooms": subs,
        "containers": [x for x in (_container(c) for c in (d.get("containers") or [])[:6]) if x],
    }


class Enricher:
    def describe_building(self, ctx: BuildingCtx) -> dict | None:
        raise NotImplementedError


class StubEnricher(Enricher):
    """Без LLM: детерминированный фактшит. Для офлайна/тестов/dry-run."""

    def describe_building(self, ctx: BuildingCtx) -> dict:
        sig = "значим" in ctx.role_hint
        return _norm_building({
            "type": ctx.name_hint.lower(), "tier": "modest", "size": "small",
            "condition": "sound", "materials": {"walls": "брёвна", "roof": "солома"},
            "features": ["низкая дверь", "ставни"], "smells": ["дым"], "sounds": ["тишина"],
            "services": (["eat", "drink"] if sig else []),
            "occupants_kind": ("хозяин и слуга" if sig else "семья горожан"),
            "notable": "примечательная деталь (заглушка)",
            "secret": ({"what": "тайник под полом", "where": "подвал", "gate": "доверие"} if sig else None),
            "sub_rooms": ([{"name": "Подвал", "kind": "cellar", "access": "locked",
                            "features": ["бочки"], "contents": ["припасы"]}] if sig else []),
            "containers": ([{"name": "Сундук у стойки", "kind": "chest", "where": "за стойкой",
                             "access": "locked", "contents": ["выручка", "долговая книга"],
                             "key": {"name": "латунный ключ на шнурке", "note": "носит хозяин"}},
                            {"name": "Полка с кружками", "kind": "shelf", "where": "у очага",
                             "access": "public", "contents": ["кружки", "миски"]}] if sig
                           else [{"name": "Сундук в углу", "kind": "chest", "where": "у лежанки",
                                  "access": "public", "contents": ["одежда", "мелочь"]}]),
        })


class LLMEnricher(Enricher):
    """Реальный путь: роль location_writer, фактшит-JSON (без прозы)."""

    def __init__(self, manager):
        self.manager = manager

    def describe_building(self, ctx: BuildingCtx) -> dict | None:
        if not self.manager.available():
            return None
        user = (f"Здание-слот: подсказка типа «{ctx.name_hint}», {ctx.role_hint}; "
                f"ориентиры: {', '.join(ctx.landmarks) or 'нет'}; мир: {ctx.region}.")
        resp = self.manager.call("location_writer",
                                 [{"role": "system", "content": _BUILD_SYS},
                                  {"role": "user", "content": user}], options={"temperature": 0.6})
        data = _parse_json(resp.get("content") if resp else None)
        return _norm_building(data) if data else None
