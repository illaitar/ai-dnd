"""Модуль использования LLM для насыщения локаций — ОТДЕЛЬНЫЙ от скрипта генерации.

Два промпта (двухфазно):
  describe_building(ctx) — богатый JSON здания; суб-помещения объявляет СТАБАМИ (имя/тип/доступ,
    без описаний) → они уходят в очередь на отдельную генерацию;
  describe_subroom(parent, stub) — ДРУГОЙ промпт: описывает одно суб-помещение С КОНТЕКСТОМ здания.
    У суб-помещения своих суб-помещений нет.

`LLMEnricher` — реальный путь (роль location_writer, свободная проза в JSON-полях).
`StubEnricher` — детерминированная заглушка (офлайн / тесты / dry-run).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

SERVICES = ("eat", "drink", "lodging", "shop", "commission", "heal", "pray", "store")
ROOM_KINDS = ("cellar", "backroom", "attic", "quarters", "hidden")
ROOM_ACCESS = ("public", "staff", "locked", "hidden")


@dataclass
class BuildingCtx:
    """Что слой графа знает о здании-слоте; из этого LLM сочиняет облик/функцию/доп-помещения."""
    id: str
    name_hint: str
    role_hint: str
    landmarks: list[str] = field(default_factory=list)
    region: str = "фронтир Фэндалина"


_BUILD_SYS = (
    "Ты — генератор зданий для тёмно-фэнтезийного фронтирного городка (D&D, Фэндалин). "
    "По краткой подсказке придумай ЖИВОЕ, конкретное здание. Верни ТОЛЬКО JSON (без markdown), поля:\n"
    "name — собственное имя/вывеска;\n"
    "type — тип (таверна/кузница/лавка/храм/усадьба/склад/жилой дом…);\n"
    "services — массив из [eat, drink, lodging, shop, commission, heal, pray, store]: что тут можно делать;\n"
    "keeper — {name, role} хозяина (или null для пустого дома);\n"
    "notable — одна примечательная деталь (трофей, странность);\n"
    "secret — {hint, room} тайна места или null;\n"
    "description — 2-4 предложения живой прозой: облик, атмосфера, звуки-запахи;\n"
    "sub_rooms — массив доп-помещений ТОЛЬКО как заявки: [{name, kind:(cellar|backroom|attic|quarters|hidden), "
    "access:(public|staff|locked|hidden)}], БЕЗ описаний; 0-4 шт (у жилого дома обычно 0-1). "
    "Не выдумывай несуществующих фактов мира."
)

_ROOM_SYS = (
    "Ты описываешь ОДНО под-помещение ВНУТРИ заданного здания, в согласии с ним. "
    "Верни ТОЛЬКО JSON (без markdown): description — 1-2 предложения живой прозой; "
    "contents — что внутри (предметы/тайник/обитатель/«пусто»). "
    "У под-помещения НЕТ собственных под-помещений — не упоминай их."
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


class Enricher:
    """Интерфейс насыщения: здание (фаза 1) и суб-помещение (фаза 2)."""

    def describe_building(self, ctx: BuildingCtx) -> dict | None:
        raise NotImplementedError

    def describe_subroom(self, parent: dict, stub: dict) -> dict | None:
        raise NotImplementedError


class StubEnricher(Enricher):
    """Без LLM: детерминированный фейк. Для офлайна/тестов/dry-run."""

    def describe_building(self, ctx: BuildingCtx) -> dict:
        sig = "значим" in ctx.role_hint
        where = ", ".join(ctx.landmarks) if ctx.landmarks else "в глубине квартала"
        return {
            "name": ctx.name_hint, "type": ctx.name_hint.lower(),
            "services": (["eat", "drink"] if sig else []),
            "keeper": ({"name": "Хозяин", "role": ctx.name_hint.lower()} if sig else None),
            "notable": "примечательная деталь (заглушка)",
            "secret": ({"hint": "тайник под полом", "room": "Подвал"} if sig else None),
            "description": f"{ctx.name_hint}. {ctx.role_hint.capitalize()}, {where}. (заглушка)",
            "sub_rooms": ([{"name": "Подвал", "kind": "cellar", "access": "locked"}] if sig else []),
        }

    def describe_subroom(self, parent: dict, stub: dict) -> dict:
        return {"description": f"{stub.get('name', 'Помещение')} в «{parent.get('name', '')}». (заглушка)",
                "contents": "бочки, пыль"}


class LLMEnricher(Enricher):
    """Реальный путь: роль location_writer, свободная проза в JSON-полях."""

    def __init__(self, manager):
        self.manager = manager

    def _call(self, system: str, user: str) -> dict | None:
        if not self.manager.available():
            return None
        resp = self.manager.call("location_writer",
                                 [{"role": "system", "content": system},
                                  {"role": "user", "content": user}],
                                 options={"temperature": 0.7})
        return _parse_json(resp.get("content") if resp else None)

    def describe_building(self, ctx: BuildingCtx) -> dict | None:
        user = (f"Здание-слот: подсказка типа «{ctx.name_hint}», {ctx.role_hint}; "
                f"ориентиры: {', '.join(ctx.landmarks) or 'нет'}; мир: {ctx.region}.")
        data = self._call(_BUILD_SYS, user)
        return _norm_building(data) if data else None

    def describe_subroom(self, parent: dict, stub: dict) -> dict | None:
        user = (f"Здание «{parent.get('name', '')}» ({parent.get('type', '')}): "
                f"{parent.get('description', '')}\n"
                f"Опиши его под-помещение «{stub.get('name', '')}» "
                f"(тип {stub.get('kind', '')}, доступ {stub.get('access', '')}).")
        data = self._call(_ROOM_SYS, user)
        if not data:
            return None
        return {"description": str(data.get("description", "")), "contents": str(data.get("contents", ""))}


def _norm_building(d: dict) -> dict:
    """Привести вывод модели к ожидаемой форме (терпимо к пропускам/мусору)."""
    services = [s for s in (d.get("services") or []) if s in SERVICES]
    subs = []
    for s in (d.get("sub_rooms") or [])[:4]:
        if not isinstance(s, dict) or not s.get("name"):
            continue
        subs.append({"name": str(s["name"]).strip(),
                     "kind": s.get("kind") if s.get("kind") in ROOM_KINDS else "backroom",
                     "access": s.get("access") if s.get("access") in ROOM_ACCESS else "public"})
    keeper = d.get("keeper") if isinstance(d.get("keeper"), dict) and d["keeper"].get("name") else None
    secret = d.get("secret") if isinstance(d.get("secret"), dict) and d["secret"].get("hint") else None
    return {"name": str(d.get("name") or "").strip(), "type": str(d.get("type") or "").strip(),
            "services": services, "keeper": keeper, "notable": str(d.get("notable") or "").strip(),
            "secret": secret, "description": str(d.get("description") or "").strip(), "sub_rooms": subs}
