"""АЛЬТЕРНАТИВА механическому ядру: каждый NPC каждый тик задаёт модели ПОЛНЫЙ вопрос «что делаю
дальше», получая на вход ВЕСЬ контекст, а на выход — последовательность вызовов инструментов.

Сравнение с utility-ядром: тут ноль формул — весь выбор у LLM. В промпте: кто ты (черты/способности/
HP), твои нужды и эмоции (с адресатом), отношения, описание места и выходов, ВСЕ видимые NPC (здесь и
рядом) + их действие в прошлый тик, твои последние 10 действий, время. Инструменты включают и
само-регуляцию (менять свои эмоции/нужды) и заметку в память.

manager — aidnd.inference.ModelManager (профиль deepseek). Нет модели → NPC ждёт (явный фоллбэк).
"""

from __future__ import annotations

import json
import re

from .act import score
from .agenda import Agenda, Milestone
from .world import Item

NEED_RU = {"fatigue": "усталость", "hunger": "голод", "social": "тяга к общению",
           "purpose": "нужда в деле", "wealth": "жажда наживы", "comfort": "тяга к уюту",
           "novelty": "тяга к новизне"}
EMO_RU = {"anger": "гнев", "fear": "страх", "joy": "радость", "distress": "подавленность"}
TRAIT_RU = {"bravery": "храбрость", "greed": "жадность", "honesty": "честность",
            "curiosity": "любопытство", "pride": "гордость", "loyalty": "верность",
            "sociability": "общительность", "ambition": "амбиции", "lawful": "законопослушность",
            "irritability": "вспыльчивость", "malice": "злонравие"}

TOOLSPEC = """ДОСТУПНЫЕ ИНСТРУМЕНТЫ (верни последовательность — что делаешь ЭТОТ ход, по порядку):
  move   {"to": "<соседнее место>"}            — перейти в соседнее место (уйти по делам/подойти/убежать)
  use    {"item": "<ресурс здесь>"}             — воспользоваться (поесть/поработать/лечь — ЗАКРЫТЬ нужду)
  take   {"target": "<имя>"}  или {"item": "<предмет>"} — забрать добычу с тела/с земли
  attack {"target": "<имя>"}                    — напасть (ранить/убить)
  give   {"item": "<предмет>", "to": "<имя>"}   — отдать свой предмет
  say    {"to": "<имя>", "text": "<реплика>"}   — сказать вслух РАДИ ЦЕЛИ (узнать/сторговаться/запугать)
  feel   {"emotion": "anger|fear|joy|distress", "value": 0.0-1.0} — изменить свою эмоцию
  need   {"need": "hunger|fatigue|social|purpose|wealth|comfort|novelty", "value": 0.0-1.0} — свою нужду
  note   {"text": "<мысль/намерение>"}          — записать замысел в память (увидишь в след. ходы)
  wait   {}                                     — наблюдать (только если правда нечего делать)
Отвечай ОДНИМ JSON: {"think": "<короткая мысль>", "actions": [ {"tool": "...", ...}, ... ]}
Только реально доступное: двигайся лишь в перечисленные выходы; атакуй/бери лишь тех, кто РЯДОМ (здесь же)."""

_SYS = (
    "Ты — разум ОДНОГО жителя тёмно-фэнтезийного городка (D&D, фронтир). По полному контексту реши, что "
    "персонаж делает ДАЛЬШЕ — от первого лица, до конца В ХАРАКТЕРЕ. Жадность, злонравие, трусость — это "
    "его натура в мрачном фэнтези, отыгрывай без стеснения. Не отыгрывай других, не выдумывай лишнего. "
    "Верни строго JSON.\n"
    "ГЛАВНОЕ — ДЕЙСТВУЙ, а не болтай впустую:\n"
    "• Тобой движут НУЖДЫ и ЭМОЦИИ. Высокая нужда → пойди и закрой её: use ресурса в нужном месте, а нет "
    "его здесь — move туда. Голодный ест, усталый идёт домой спать, мастеровой работает у горна/в поле.\n"
    "• Речь (say) — ради ЦЕЛИ (узнать, сторговаться, запугать, отвлечь), не пустой трёп. НЕ повторяй "
    "один и тот же вопрос — твои прошлые действия перечислены, ПРОДВИГАЙСЯ дальше.\n"
    "• Последствия реальны: удар ранит и убивает; кражу и нападение выдают СВИДЕТЕЛИ рядом. Преступление "
    "при толпе — глупость: выследи и жди, пока мишень останется ОДНА.\n"
    "• Хищник не только схемит, но и ДЕЙСТВУЕТ: если ты жаден/злонравен, а рядом уязвимая, богато одетая "
    "или отбившаяся цель и НЕТ свидетелей — не медли, лови момент. Это твоя роль в этой истории.\n"
    "• Боишься того, кто рядом — беги (move прочь) или бей, а не разговаривай.\n"
    "• Не топчись в толпе без дела. Выбери 1–3 инструмента, которые РЕАЛЬНО продвинут тебя этот ход.")


def _lvl(x: float) -> str:
    return "оч.высок." if x >= .8 else "высок." if x >= .55 else "средн." if x >= .35 else \
        "низк." if x >= .15 else "нет"


def _traits_line(tr: dict) -> str:
    return ", ".join(f"{TRAIT_RU.get(k, k)} {v:.1f}" for k, v in tr.items())


def _needs_line(needs: dict) -> str:
    hot = [f"{NEED_RU[k]} {_lvl(v)}" for k, v in needs.items() if v >= .35]
    return ", ".join(hot) or "всё в норме"


def _emo_line(emo: dict, tgt: dict) -> str:
    hot = []
    for k, v in emo.items():
        if v >= .15:
            who = f" (на {tgt[k]})" if tgt.get(k) else ""
            hot.append(f"{EMO_RU[k]} {_lvl(v)}{who}")
    return ", ".join(hot) or "спокоен"


def _rel_line(state, entity: str) -> str:
    r = state.relationships.get(entity)
    if not r:
        return "незнаком"
    parts = []
    if r.get("affinity"):
        parts.append(("симпатия" if r["affinity"] > 0 else "неприязнь") + f" {abs(r['affinity']):.1f}")
    if r.get("fear"):
        parts.append(f"боишься {r['fear']:.1f}")
    if r.get("trust"):
        parts.append(f"доверие {r['trust']:.1f}")
    return ", ".join(parts) or "нейтрально"


def build_prompt(state, world, percept, ctx: dict, prefs=None):
    me = percept.me
    cfg = state.config
    roles = ctx.get("roles", {})
    last = ctx.get("last_actions", {})
    place_desc = ctx.get("place_desc", {})

    lines = [f"ВРЕМЯ: ход {ctx.get('clock', 0)}.", ""]
    lines.append(f"ТЫ — {cfg.name}, {roles.get(cfg.id, cfg.role)}. HP {me.hp}/{me.max_hp}.")
    lines.append(f"Черты: {_traits_line(cfg.traits)}.")
    lines.append(f"Нужды: {_needs_line(state.needs)}.")
    lines.append(f"Эмоции: {_emo_line(state.emotion, state.emotion_target)}.")

    lines.append("")
    lines.append(f"МЕСТО: {me.place}. {place_desc.get(me.place, '')}")
    res = world.ground.get(me.place, [])
    if res:
        lines.append("  Здесь можно воспользоваться: " + ", ".join(
            f"«{i.name}»" + (f" (закрывает: {NEED_RU.get(i.satisfies, i.satisfies)})" if i.satisfies else "")
            for i in res) + ".")
    lines.append("  Выходы: " + (", ".join(percept.exits) or "нет") + ".")

    if percept.present:
        lines.append("")
        lines.append("РЯДОМ С ТОБОЙ (здесь же):")
        for b in percept.present:
            wealth = "богато одет" if b.appearance >= .6 else "прилично" if b.appearance >= .4 else "простак"
            st = "повержен" if b.down() else f"HP {b.hp}"
            act = last.get(b.id, "—")
            lines.append(f"  • {b.id} ({roles.get(b.id, '?')}, {wealth}, {st}). "
                         f"Прошлый ход: {act}. Твоё отношение: {_rel_line(state, b.id)}.")
    if percept.nearby:
        lines.append("")
        lines.append("ВИДишь ПОБЛИЗОСТИ (соседние места):")
        for b in percept.nearby:
            lines.append(f"  • {b.id} ({roles.get(b.id, '?')}) — в «{b.place}». "
                         f"Прошлый ход: {last.get(b.id, '—')}.")

    hist = ctx.get("history", {}).get(cfg.id, [])
    if hist:
        lines.append("")
        lines.append("ТВОИ ПОСЛЕДНИЕ ДЕЙСТВИЯ: " + " → ".join(hist[-10:]) + ".")
    notes = [m.text for m in state.memory.items if m.kind == "note"][-5:]
    if notes:
        lines.append("ТВОИ МЫСЛИ (память): " + "; ".join(notes) + ".")

    lines.append("")
    lines.append(TOOLSPEC)
    if prefs:
        lines.append("")
        lines.append("ТВОИ ПОБУЖДЕНИЯ СЕЙЧАС (влечения просчитаны по твоей натуре и обстановке — по силе тяги):")
        for i, (lbl, goal, u) in enumerate(prefs, 1):
            lines.append(f"  {i}. {lbl}   [{goal}]   тяга {u:+.2f}")
        lines.append("СЛЕДУЙ сильнейшему побуждению (возьми 1–2 из ВЕРХНИХ; можешь добавить реплику say). "
                     "Не действуй вопреки списку — это твоя натура тянет тебя. Оформи выбор В ХАРАКТЕРЕ.")
        lines.append('Формат ответа: {"think":"<мысль от первого лица>", "does":"<что делаешь, короткой '
                     'прозой>", "actions":[ {"tool":"...", ...}, ... ]}')
    return [{"role": "system", "content": _SYS}, {"role": "user", "content": "\n".join(lines)}]


def _parse(text: str | None) -> dict | None:
    if not text:
        return None
    t = re.sub(r"```$", "", re.sub(r"^```(?:json)?", "", text.strip()).strip()).strip()
    for cand in (t, t[t.find("{"):t.rfind("}") + 1] if "{" in t else t):
        try:
            return json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _action_to_tool(a) -> dict:
    """Механический Action → вызов инструмента (для фоллбэка, когда модели нет)."""
    if a.kind == "move":
        return {"tool": "move", "to": a.to}
    if a.kind == "attack":
        return {"tool": "attack", "target": a.target}
    if a.kind == "take":
        return {"tool": "take", "target": a.target} if a.target else \
            {"tool": "take", "item": getattr(a.item, "name", None)}
    if a.kind == "say":
        return {"tool": "say", "to": a.target, "text": ""}          # слова допишет LLM; в фоллбэке — молча
    if a.kind == "use":
        return {"tool": "use", "item": getattr(a.item, "name", None)}
    return {"tool": "wait"}


def decide_hybrid(state, world, percept, manager, ctx: dict) -> dict:
    """ГИБРИД: механическое ядро даёт ранжированные ПОБУЖДЕНИЯ (решительность/консеквентность), LLM
    выбирает из верхних В ХАРАКТЕРЕ, добавляет реплику и ОПИСЫВАЕТ, что делает/думает. Нет модели →
    исполняем механический топ (гибрид деградирует в чистую механику)."""
    ranked = score(state, world, percept)
    prefs = [(a.label(), (g.kind if g else "idle"), u) for a, g, u in ranked[:5]]
    top = ranked[0][0]
    if manager is None or not manager.available():
        return {"think": "", "does": "", "actions": [_action_to_tool(top)], "prefs": prefs, "src": "механика"}
    resp = manager.call("npc_mind", build_prompt(state, world, percept, ctx, prefs=prefs),
                        schema=True, options={"temperature": 0.55})
    data = _parse(resp.get("content") if resp else None)
    if not isinstance(data, dict) or not isinstance(data.get("actions"), list) or not data["actions"]:
        return {"think": "(фоллбэк)", "does": "", "actions": [_action_to_tool(top)],
                "prefs": prefs, "src": "фоллбэк"}
    return {"think": str(data.get("think", ""))[:160], "does": str(data.get("does", ""))[:160],
            "actions": data["actions"][:3], "prefs": prefs, "src": "llm"}


def decide_llm(state, world, percept, manager, ctx: dict) -> dict:
    """Полный вопрос модели. Возвращает {'think', 'actions':[...]} (или пустой при недоступности)."""
    if manager is None or not manager.available():
        return {"think": "(нет модели)", "actions": [{"tool": "wait"}]}
    resp = manager.call("npc_mind", build_prompt(state, world, percept, ctx),
                        schema=True, options={"temperature": 0.7})
    data = _parse(resp.get("content") if resp else None)
    if not isinstance(data, dict) or not isinstance(data.get("actions"), list):
        return {"think": "(не разобрал ответ)", "actions": [{"tool": "wait"}]}
    return {"think": str(data.get("think", ""))[:160], "actions": data["actions"][:3]}


_PLAN_SYS = (
    "Ты — планировщик ДОЛГОСРОЧНОЙ цели для одного жителя тёмно-фэнтезийного городка. По его натуре, "
    "памяти, связям и положению придумай ОДНУ жизненную агенду, которую он будет вынашивать не один день "
    "— мирную ИЛИ тёмную, что честнее его натуре (скопить на дело, завоевать чьё-то сердце, подняться в "
    "гильдии — или отомстить, обчистить богача, устранить соперника). Разбей на вехи. Каждая веха "
    "ложится на МЕХАНИЧЕСКУЮ цель, которую движок тянет сам:\n"
    "  goal=need (target=нужда, meta.source=место) — работать/копить/добывать;\n"
    "  goal=affiliate (target=имя) — расположить к себе (дары/лесть);\n"
    "  goal=trade (target=имя) — сторговаться;\n"
    "  goal=acquire (target=имя) — завладеть добром (кража/грабёж);\n"
    "  goal=harm (target=имя) — устранить.\n"
    "Условие завершения вехи done — один из: {\"type\":\"wealth\",\"value\":N} | {\"type\":\"dead\",\"id\":имя} | "
    "{\"type\":\"affinity\",\"id\":имя,\"value\":0..1} | {\"type\":\"have\",\"item\":название} | "
    "{\"type\":\"at\",\"place\":место}. Верни строго JSON.")


def plan_agenda(state, world, ctx: dict, manager) -> Agenda | None:
    """Рефлексивный вызов (НЕ каждый тик): натура+память+ситуация → одна долгосрочная агенда. Нет модели
    → None (вызвать StubPlanner). Механическое ядро потом тянет текущую веху реактивно."""
    if manager is None or not manager.available():
        return None
    cfg = state.config
    who = [f"{b.id} ({ctx.get('roles', {}).get(b.id, '?')}, "
           f"{'богат' if b.appearance >= .6 else 'простой'})"
           for b in world.bodies.values() if b.id != cfg.id]
    mems = [m.text for m in state.memory.items][-8:]
    user = (
        f"ПЕРСОНАЖ: {cfg.name}, {ctx.get('roles', {}).get(cfg.id, cfg.role)}.\n"
        f"Черты: {_traits_line(cfg.traits)}.\n"
        f"Нужды: {_needs_line(state.needs)}. Эмоции: {_emo_line(state.emotion, state.emotion_target)}.\n"
        f"Люди вокруг: {', '.join(who) or '—'}.\n"
        f"Память: {'; '.join(mems) or '—'}.\n"
        'Придумай агенду. Формат: {"summary":"...", "kind":"wealth|courtship|ambition|revenge|predation", '
        '"importance":0.0-1.0, "milestones":[{"desc":"...", "goal":"need|affiliate|trade|acquire|harm", '
        '"target":"<имя/нужда/место>", "meta":{"source":"<место>"}, "done":{...}}]}')
    resp = manager.call("npc_mind", [{"role": "system", "content": _PLAN_SYS},
                                     {"role": "user", "content": user}],
                        schema=True, options={"temperature": 0.8})
    data = _parse(resp.get("content") if resp else None)
    if not isinstance(data, dict) or not isinstance(data.get("milestones"), list) or not data["milestones"]:
        return None
    ms = []
    for m in data["milestones"][:5]:
        if not isinstance(m, dict) or not m.get("goal"):
            continue
        ms.append(Milestone(str(m.get("desc", ""))[:80], str(m["goal"]),
                            m.get("target"), dict(m.get("meta") or {}),
                            dict(m.get("done") or {"type": "never"})))
    if not ms:
        return None
    imp = data.get("importance", 0.75)
    return Agenda(str(data.get("summary", "цель"))[:80], str(data.get("kind", "ambition")),
                  float(imp) if isinstance(imp, (int, float)) else 0.75, ms)


# ── исполнение последовательности инструментов над миром ──
def _find_body(world, name):
    if not name:
        return None
    low = str(name).strip().lower()
    for b in world.bodies.values():
        if b.id.lower() == low:
            return b
    return None


def _find_item(items, name):
    if not name:
        return None
    low = str(name).strip().lower()
    return next((i for i in items if low in i.name.lower() or i.name.lower() in low), None)


def apply_actions(actions, state, world, clock: int) -> list:
    """Исполнить последовательность инструментов. Возвращает список строк-событий (для лога)."""
    me = world.bodies[state.config.id]
    log = []
    for a in actions:
        if not isinstance(a, dict):
            continue
        tool = a.get("tool")
        if me.down():
            break
        if tool == "move":
            dst = a.get("to")
            if dst in world.neighbors(me.place):
                me.place = dst
                log.append(f"→{dst}")
            else:
                log.append(f"move✗{dst}")
        elif tool == "attack":
            tb = _find_body(world, a.get("target"))
            if tb and tb.place == me.place and not tb.down():
                tb.hp -= 6
                if tb.hp <= 0:
                    tb.alive = False
                vs = world.npc_minds.get(tb.id) if hasattr(world, "npc_minds") else None
                if vs is not None:
                    r = vs.rel(me.id)
                    r["fear"] = max(r["fear"], 0.85)
                    r["affinity"] = min(r["affinity"], -0.3)
                    vs.emotion["fear"] = min(1.0, vs.emotion.get("fear", 0.0) + 0.6)
                    vs.emotion_target["fear"] = me.id
                    vs.memory.add(f"{me.id} напал на меня", clock, importance=0.9, kind="event", about=[me.id])
                log.append(f"⚔{tb.id}" + ("☠" if tb.down() else f"→hp{tb.hp}"))
            else:
                log.append("attack✗")
        elif tool == "take":
            tb = _find_body(world, a.get("target"))
            if tb and tb.place == me.place and tb.loot:
                got = tb.loot.pop(0)
                me.loot.append(got)
                log.append(f"💰{got.name}")
            else:
                it = _find_item(world.ground.get(me.place, []), a.get("item"))
                if it and it.value > 0.1:
                    world.ground[me.place].remove(it)
                    me.loot.append(it)
                    log.append(f"💰{it.name}")
                else:
                    log.append("take✗")
        elif tool == "give":
            tb = _find_body(world, a.get("to"))
            it = _find_item(me.carrying, a.get("item"))
            if tb and it and tb.place == me.place:
                me.carrying.remove(it)
                tb.carrying.append(it)
                log.append(f"🎁{it.name}→{tb.id}")
            else:
                log.append("give✗")
        elif tool == "say":
            tb = _find_body(world, a.get("to"))
            txt = str(a.get("text", ""))[:120]
            if tb is not None:
                vs = world.npc_minds.get(tb.id) if hasattr(world, "npc_minds") else None
                if vs is not None:
                    vs.memory.add(f"{me.id} сказал мне: «{txt}»", clock, importance=0.4,
                                  kind="heard", about=[me.id])
                log.append(f"💬{tb.id}:«{txt[:40]}»")
            else:
                log.append(f"💬:«{txt[:40]}»")
        elif tool == "use":
            it = _find_item(world.ground.get(me.place, []) + me.carrying, a.get("item"))
            if it and it.satisfies and it.satisfies in state.needs:
                state.needs[it.satisfies] = max(0.0, state.needs[it.satisfies] - 0.6)
                log.append(f"✳{it.name}")
            else:
                log.append("use✗")
        elif tool == "feel":
            e, v = a.get("emotion"), a.get("value")
            if e in state.emotion and isinstance(v, (int, float)):
                state.emotion[e] = max(0.0, min(1.0, float(v)))
                log.append(f"~{EMO_RU.get(e, e)}={v}")
        elif tool == "need":
            n, v = a.get("need"), a.get("value")
            if n in state.needs and isinstance(v, (int, float)):
                state.needs[n] = max(0.0, min(1.0, float(v)))
                log.append(f"~{NEED_RU.get(n, n)}={v}")
        elif tool == "note":
            state.memory.add(str(a.get("text", ""))[:120], clock, importance=0.5, kind="note")
            log.append("✎")
        elif tool == "wait":
            log.append("·")
    return log or ["·"]
