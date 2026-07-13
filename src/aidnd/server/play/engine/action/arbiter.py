"""Arbiter of free-form input — single resolve(text) (docs/loop.md "Further", principle 3).

Code declares primitives: the PRIMITIVES registry — sole source of truth (verb, goals, "when").
Arbiter prompt is GENERATED from the registry: add primitive = one entry, no more hand-written
verb lists in prose. Context assembler feeds arbiter MAXIMUM scene facts (people, containers, bag,
zones, nearby items, city locations, time) — arbiter parses intent and goals itself; executors
(primitive×manner×gates) live in handlers/freeform._attempt.

Key functions
-------------
resolve(text: str, sc: dict) -> dict | None : Parse player input to verb-target-manner plan via LLM arbiter.
assemble_context(sc: dict) -> str : Gather scene facts (NPCs, items, zones) for arbiter.
normalize_plan(out: dict, cap: int = 3) -> dict : Validate and clean arbiter response into executable plan.
"""

from __future__ import annotations

import json

from ..core import _model
from ..session.persist import _store
from ..session.state import _S, _wid
from ..session.time import _gt

# Registry of primitives: targets — which fields must be filled; when — how to recognize intent.
PRIMITIVES = (
    {"verb": "talk", "targets": ("npc",), "when": "заговорить/спросить/обратиться к человеку"},
    {"verb": "say", "targets": ("npc",), "manner": "persuasively",
     "when": "выпросить/попросить вещь, уговорить на что-то БЕЗ платы"},
    {"verb": "say", "targets": ("npc", "deal"),
     "when": "предложить СДЕЛКУ со ставкой золота (заплачу/найму/дам N зм если…): deal.kind — "
             "dead=убить, bring=принести/добыть, visit=прийти куда-то, befriend=подружиться; "
             "шёпотом/на ухо/отведя в сторону = manner stealthily (никто не услышит)"},
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
    {"verb": "listen", "targets": ("zone",),
     "when": "подслушать/прислушаться к чужому разговору или зоне (навострить уши, ловить "
             "слова) — zone цели, если названа"},
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
    "deal": '"deal":{"kind":"dead|bring|visit|befriend", "target":"<id человека-цели или '
            'null>", "want":"<вещь/место, если цель не человек>", "stake_gold":<целое зм>} '
            'или null',
}


def _sys_prompt() -> str:
    """Arbiter prompt generated from registry — code declared primitives, prose is derived."""
    verbs = "|".join(dict.fromkeys(p["verb"] for p in PRIMITIVES))
    manners = "openly|stealthily|forcefully|persuasively"
    rules = "; ".join(
        p["when"] + " = " + "+".join(
            (p["verb"],) + p["targets"] + ((p["manner"],) if p.get("manner") else ())
        )
        for p in PRIMITIVES
    )
    step = ('{"verb":"' + verbs + '", "manner":"' + manners + '", '
            + ", ".join(_FIELD_HINT.values())
            + ', "detail":"<суть: что именно/о чём, коротко>"}')
    return (
        "Ты — арбитр намерения игрока в тёмно-фэнтезийной игре. По фразе и обстановке верни "
        "СТРОГО JSON — ПЛАН из 1-3 звеньев в порядке исполнения:\n"
        '{"verdict":"do|narrate", "plan":[' + step + ', ...]}\n'
        "Каждое звено — ОДИН инструмент. Фраза с несколькими действиями («беру кружку и сажусь "
        "к очагу») = несколько звеньев по порядку. Вещь/человек в ДРУГОЙ зоне — сначала "
        "move+zone туда, потом дело. Соответствия: " + rules + ". "
        'verdict: "do" — исполняем; "narrate" — не-действие (план из одного wait). '
        "Только перечисленные id/имена, ничего не выдумывай. "
        "Игрок называет конкретную вещь, которой нет среди перечисленных (ПРЕДМЕТЫ РЯДОМ/СУМКА/ЁМКОСТИ) — "
        'верни "item":null, НЕ подставляй другую вещь вместо неё.'
    )


def assemble_context(sc: dict) -> str:
    """Maximum facts for arbiter: who/what/where available right now (dialogue = world state).
    All with real ids — arbiter chooses targets, not inventing."""
    here = "; ".join(f"{h['id']}={h['name']} ({h['role']})" for h in sc["here"]) or "никого"
    conts = "; ".join(
        c["name"] + (" [заперто]" if c["locked"] else "") for c in sc["location"]["containers"]
    ) or "нет"
    bag = "; ".join(
        f"{r['item_id']}={(_store().get_item(r['item_id']) or {}).get('name', '?')}"
        for r in _store().inventory(_wid(), "pc")
    ) or "пусто"
    keys_pl = ", ".join(k["label"] for k in _S["geom"]["keys"])
    from aidnd.server.play.engine.pc.hero import _seen

    from ..core import _binfo
    _lm_bids = {k.get("bid") for k in _S["geom"]["keys"]}
    seen_names = [
        _binfo(b)["name"] for b in _seen()
        if b not in _lm_bids and b != "board:plaza"
    ]
    if seen_names:  # revealed non-landmark buildings the player can walk to (F4)
        keys_pl = (keys_pl + ", " if keys_pl else "") + ", ".join(seen_names)
    from aidnd.server.play.engine.world import _scene_zones

    zones_line = "; ".join(f"{z['id']}={z['name']}" for z in _scene_zones()) or "нет"
    lv = _S.get("live") or {}
    pl = (lv.get("zone_names") or {}).get(_S.get("zone")) or lv.get("ent", "у входа")
    near = [f"{iid}={nm}" for nm, iid in (lv.get("zone_items", {}).get(pl) or {}).items()][:10]
    near += [f"{iid}={nm} [прибито]"
             for nm, iid in (lv.get("zone_fixed", {}).get(pl) or {}).items()][:4]
    zid_of = {v: k for k, v in (lv.get("zone_names") or {}).items()}
    afar, total = [], 0
    for zpl, imap in (lv.get("zone_items") or {}).items():   # visible BY EYE across other zones
        if zpl == pl or total >= 18:
            continue
        row = [f"{iid}={nm}" for nm, iid in list(imap.items())[:3]]
        total += len(row)
        if row:
            afar.append(f"{zid_of.get(zpl, '?')} ({zpl}): " + ", ".join(row))
    amb = sc.get("ambient") or {}
    return (
        f"МЕСТО: {sc['location']['name']}. ВРЕМЯ: {amb.get('time', '')} "
        f"{_gt() // 60 % 24:02d}:{_gt() % 60:02d}. ЛЮДИ ЗДЕСЬ: {here}. ЁМКОСТИ: {conts}. "
        f"СУМКА ИГРОКА: {bag}. МЕСТА ГОРОДА: {keys_pl}. ЗОНЫ: {zones_line}. "
        f"ПРЕДМЕТЫ РЯДОМ (твоя зона — {pl}): {'; '.join(near) or 'ничего приметного'}. "
        f"ВИДНО В ДРУГИХ ЗОНАХ: {'; '.join(afar) or '—'}."
    )


def resolve(text: str, sc: dict) -> dict | None:
    """Single heavy contextual call: phrase + scene → {verb, verdict, targets, manner, detail}.
    None — only "didn't understand phrase"; LLM unavailability throws exception."""
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
    return normalize_plan(out)


def normalize_plan(out: dict, cap: int = 3) -> dict:
    """Arbiter response → honest plan: list of step-dicts, capped length, wait-ballast dropped
    from chains (wait meaningful only solo — as non-action for narrator)."""
    steps = out.get("plan") if isinstance(out.get("plan"), list) else None
    if steps is None:
        steps = [out]                                # backward compatibility: single step
    steps = [s for s in steps if isinstance(s, dict)]
    if str(out.get("verdict") or "") == "narrate":
        d = next((s.get("detail") for s in steps if s.get("detail")), out.get("detail"))
        steps = [{"verb": "wait", "detail": d or ""}]
    if len(steps) > 1:
        steps = [s for s in steps if (s.get("verb") or "wait") != "wait"] or steps[:1]
    return {"verdict": out.get("verdict") or "do", "plan": steps[:cap]}
