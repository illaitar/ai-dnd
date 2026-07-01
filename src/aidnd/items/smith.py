"""Ковка предмета: контекст (тип/источник/полоса качества/подсказка-имя) → фактшит с surface+hidden.
Табличный скелет качества/цены/DC + LLM-флейвор и ПРИРОДА скрытого («выглядит как X, на деле Y»).

LLMSmith — реальный путь (роль item_smith → deepseek); StubSmith — офлайн/тесты.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .model import normalize


@dataclass
class ItemCtx:
    kind: str = "misc"
    source: str = ""                   # откуда: «касса трактира», «пояс головореза», «полка»
    name_hint: str = ""                # исходная строка (contents/valuable)
    quality_band: str = "plain"        # crude|plain|fine|exquisite — ориентир
    region: str = "фронтир тёмного фэнтези (D&D)"


_ITEM_SYS = (
    "Ты — генератор ПРЕДМЕТОВ для тёмно-фэнтезийного фронтира (D&D). По подсказке верни ТОЛЬКО JSON-фактшит "
    "предмета в ДВА слоя. КОРОТКО, теги/энумы/фразы, БЕЗ прозы. Поля:\n"
    "kind (weapon|armor|tool|trinket|consumable|key|document|valuable|material|misc); name (как ВЫГЛЯДИТ); "
    "slot (main_hand|off_hand|body|head|worn|none); material; quality (crude|plain|fine|exquisite); "
    "weight (число); apparent_worth (видимая цена, целое, монеты); worth (ИСТИННАЯ цена, целое); tags[]; "
    "mods[] — ВИДИМЫЕ модификаторы {target, op(add|mul|set|grant|advantage|disadvantage), amount, "
    "when(passive|equipped|worn|on_use|conditional), cond}; targets: social:appearance | reaction:<роль> | "
    "special:opens|light|detect | worth | evidence | attack|defense|ability:<x> (боевые допустимы, но пусть спят); "
    "hidden[] — 0-2 СКРЫТЫХ свойства {prop(true_material|true_worth|forgery|provenance|poison|enchant|curse|"
    "flaw|compartment|function), value(ИСТИНА, короткой фразой), fact(что узнаёт осматривающий), "
    "gate{via(glance|handle|appraise|lore|craft_eye|tool|context|use|expert), dc(целое 8-20), "
    "req(для craft_eye/lore — компетенция metalwork|gems|herbs|poison|medicine|letters|lore|trade|faith|law; "
    "для tool — инструмент; для context — условие)}, mods[](включаются при вскрытии)}.\n"
    "ИГРА В ОБМАН: иногда surface ВРЁТ (подделка/скрытая ценность/яд/тайник) — тогда worth≠apparent_worth и/или "
    "hidden несёт истину под гейтом. Обычная бытовая мелочь — без hidden. Соблюдай подсказку типа и источника.\n"
    "ЯЗЫК: энум-поля (kind/slot/quality/op/when/prop/via) и target/req-компетенции — строго АНГЛ. ключи из "
    "списков. ВСЁ остальное (name, material, tags, value, fact, cond, инструмент/условие) — НА РУССКОМ, "
    "короткими фразами, без snake_case."
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


class Smith:
    def forge(self, ctx: ItemCtx) -> dict | None:
        raise NotImplementedError


class StubSmith(Smith):
    """Детерминированная заглушка (офлайн/тесты) — предмет со скрытым происхождением под гейтом."""

    def forge(self, ctx: ItemCtx) -> dict:
        n = ctx.name_hint or "невзрачная вещица"
        return normalize({
            "kind": ctx.kind, "name": n, "quality": ctx.quality_band, "material": "неясный сплав",
            "weight": 0.2, "apparent_worth": 2, "worth": 40, "tags": ["потёртое"],
            "hidden": [{"prop": "provenance", "value": "клеймо забытого дома",
                        "fact": "на предмете старое клеймо — за ним стоит имя",
                        "gate": {"via": "lore", "dc": 15, "req": "letters"},
                        "mods": [{"target": "worth", "op": "set", "amount": 40}]}],
        })


class LLMSmith(Smith):
    """Реальный путь: роль item_smith, JSON-фактшит (без прозы)."""

    def __init__(self, manager):
        self.manager = manager

    def forge(self, ctx: ItemCtx) -> dict | None:
        if not self.manager.available():
            return None
        user = (f"Предмет: тип «{ctx.kind}», подсказка-имя «{ctx.name_hint or '—'}», источник «{ctx.source or '—'}», "
                f"ориентир качества {ctx.quality_band}; мир: {ctx.region}. Выкуй фактшит.")
        resp = self.manager.call("item_smith", [{"role": "system", "content": _ITEM_SYS},
                                                {"role": "user", "content": user}], options={"temperature": 0.7})
        data = _parse_json(resp.get("content") if resp else None)
        return normalize(data) if data else None
