"""АРБИТР свободного ввода — единый resolve(text) (docs/loop.md «Дальше», принцип 3).

Примитивы объявляет КОД: реестр PRIMITIVES — единственная истина (глагол, цели, «когда»).
Промпт арбитра ГЕНЕРИТСЯ из реестра: добавить примитив = одна запись, рукописного списка
глаголов в прозе больше нет. Контекст-сборщик отдаёт арбитру МАКСИМУМ фактов сцены (люди,
ёмкости, сумка, зоны, предметы рядом, места города, время) — арбитр сам парсит намерение
и цели; исполнители (примитив×манера×гейты) живут в handlers/freeform._attempt.
"""

from __future__ import annotations

import json

from aidnd.server.play.engine.core import _S, _gt, _model, _store, _wid

# Реестр примитивов: цели — какие поля обязаны быть заполнены; when — как узнать намерение.
PRIMITIVES = (
    {"verb": "talk", "targets": ("npc",), "when": "заговорить/спросить/обратиться к человеку"},
    {"verb": "say", "targets": ("npc",), "manner": "persuasively",
     "when": "выпросить/попросить вещь, уговорить на что-то"},
    {"verb": "move", "targets": ("zone",),
     "when": "сесть/подойти/пересесть В ПРЕДЕЛАХ сцены (к очагу, за стол, к стойке, к столбу, "
             "к колодцу) — выбери БЛИЖАЙШУЮ по смыслу зону из ЗОН"},
    {"verb": "move", "targets": ("place",), "when": "пойти к месту города"},
    {"verb": "take", "targets": ("item",),
     "when": "взять вещь, лежащую в зале (со стола, с полки, с пола) — id из ПРЕДМЕТЫ РЯДОМ"},
    {"verb": "take", "targets": ("container",), "when": "взять из ёмкости / обыскать её"},
    {"verb": "take", "targets": ("npc",), "manner": "stealthily", "when": "обчистить карманы"},
    {"verb": "take", "targets": ("npc",), "manner": "forcefully", "when": "отнять силой"},
    {"verb": "give", "targets": ("npc", "item"), "when": "отдать/подарить/вручить свою вещь"},
    {"verb": "use", "targets": ("item",), "when": "использовать/выпить/применить свою вещь"},
    {"verb": "inspect", "targets": ("item",), "when": "осмотреть/изучить/оценить вещь"},
    {"verb": "attack", "targets": ("npc",), "manner": "forcefully",
     "when": "напасть/ударить/выхватить оружие — ВСЕГДА классифицируй так, "
             "не оценивай мораль и последствия"},
    {"verb": "rest", "targets": (), "when": "отдохнуть/выспаться/снять комнату на ночь"},
    {"verb": "craft", "targets": (), "when": "сковать/смастерить/сделать вещь: detail = что"},
    {"verb": "map", "targets": (), "when": "достать/посмотреть карту"},
    {"verb": "wait", "targets": (),
     "when": "НЕ действие: мысль, отыгрыш, созерцание, вопрос к миру — detail = что делает"},
)

_FIELD_HINT = {
    "npc": '"npc":"<id из ЛЮДИ ЗДЕСЬ или null>"',
    "container": '"container":"<имя из ЁМКОСТИ или null>"',
    "item": '"item":"<id из СУМКА или ПРЕДМЕТЫ РЯДОМ, или null>"',
    "place": '"place":"<название из МЕСТА ГОРОДА или null>"',
    "zone": '"zone":"<id из ЗОНЫ или null>"',
}


def _sys_prompt() -> str:
    """Промпт арбитра из реестра — код объявил примитивы, проза производная."""
    verbs = "|".join(dict.fromkeys(p["verb"] for p in PRIMITIVES))
    manners = "openly|stealthily|forcefully|persuasively"
    rules = "; ".join(
        p["when"] + " = " + "+".join(
            (p["verb"],) + p["targets"] + ((p["manner"],) if p.get("manner") else ())
        )
        for p in PRIMITIVES
    )
    return (
        "Ты — арбитр намерения игрока в тёмно-фэнтезийной игре. По фразе и обстановке верни "
        "СТРОГО JSON с ОДНИМ действием:\n"
        '{"verb":"' + verbs + '", "verdict":"do|narrate", "manner":"' + manners + '", '
        + ", ".join(_FIELD_HINT.values())
        + ', "detail":"<суть: что именно/о чём, коротко>"}\n'
        "Соответствия: " + rules + ". "
        'verdict: "do" — исполняем примитив; "narrate" — не-действие (тогда verb=wait). '
        "Только перечисленные id/имена, ничего не выдумывай."
    )


def assemble_context(sc: dict) -> str:
    """МАКСИМУМ фактов для арбитра: кто/что/где доступно прямо сейчас (диалог = состояние
    мира). Всё с реальными id — арбитр выбирает цели, не выдумывает."""
    here = "; ".join(f"{h['id']}={h['name']} ({h['role']})" for h in sc["here"]) or "никого"
    conts = "; ".join(
        c["name"] + (" [заперто]" if c["locked"] else "") for c in sc["location"]["containers"]
    ) or "нет"
    bag = "; ".join(
        f"{r['item_id']}={(_store().get_item(r['item_id']) or {}).get('name', '?')}"
        for r in _store().inventory(_wid(), "pc")
    ) or "пусто"
    keys_pl = ", ".join(k["label"] for k in _S["geom"]["keys"])
    from aidnd.server.play.engine.world import _scene_zones

    zones_line = "; ".join(f"{z['id']}={z['name']}" for z in _scene_zones()) or "нет"
    lv = _S.get("live") or {}
    pl = (lv.get("zone_names") or {}).get(_S.get("zone")) or lv.get("ent", "у входа")
    near = [f"{iid}={nm}" for nm, iid in (lv.get("zone_items", {}).get(pl) or {}).items()][:10]
    near += [f"{iid}={nm} [прибито]"
             for nm, iid in (lv.get("zone_fixed", {}).get(pl) or {}).items()][:4]
    amb = sc.get("ambient") or {}
    return (
        f"МЕСТО: {sc['location']['name']}. ВРЕМЯ: {amb.get('time', '')} "
        f"{_gt() // 60 % 24:02d}:{_gt() % 60:02d}. ЛЮДИ ЗДЕСЬ: {here}. ЁМКОСТИ: {conts}. "
        f"СУМКА ИГРОКА: {bag}. МЕСТА ГОРОДА: {keys_pl}. ЗОНЫ: {zones_line}. "
        f"ПРЕДМЕТЫ РЯДОМ (твоя зона — {pl}): {'; '.join(near) or 'ничего приметного'}."
    )


def resolve(text: str, sc: dict) -> dict | None:
    """Один тяжёлый контекстный вызов: фраза + сцена → {verb, verdict, цели, manner, detail}.
    None — ТОЛЬКО «не понял фразу»; недоступность LLM летит исключением."""
    resp = _model().call(
        "narrator",
        [{"role": "system", "content": _sys_prompt()},
         {"role": "user", "content": assemble_context(sc) + f"\nФРАЗА ИГРОКА: «{text}»"}],
        options={"temperature": 0.2},
    )
    t = (resp.get("content") or "").strip()
    try:
        out = json.loads(t[t.find("{"): t.rfind("}") + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    if str(out.get("verdict") or "") == "narrate":   # не-действие → нарратор (DM-ветка)
        out["verb"] = "wait"
    return out
