"""ALTERNATIVE to mechanical core: each NPC each tick poses the model a FULL question 'what do I do
next', taking ALL context as input and receiving a sequence of tool calls as output.

Comparison with utility core: zero formulas here — all choice in LLM. In prompt: who are you (traits/abilities/
HP), your needs and emotions (with target), relationships, place description and exits, ALL visible NPCs (here and
nearby) + their action last tick, your last 10 actions, time. Tools include both
self-regulation (change your emotions/needs) and a memory note.

manager — aidnd.inference.ModelManager. No model → LLMUnavailable, failed to parse answer (after
retry) → LLMBadOutput: no fallbacks, error surfaces honestly.

Key functions
-------------
build_prompt(state, world, percept, ctx, prefs=None) -> list : Build LLM prompt.
decide_hybrid(state, world, percept, manager, ctx) -> dict : Hybrid: score goals + LLM choice.
decide_llm(state, world, percept, manager, ctx) -> dict : Pure LLM decision.
plan_agenda(state, world, ctx, manager) -> Agenda|None : Create long-term agenda.
apply_actions(actions, state, world, clock) -> list : Execute tool sequence.
"""

from __future__ import annotations

import json
import re

from ..inference import LLMBadOutput
from .act import score
from .agenda import Agenda, Milestone
from .appraisal import _race_rel, appraise_present
from .value import BAL  # feel_nudge_cap (mirrors PB — importing PB here cycles play↔mind)


def _nudge(cur: float, want: float) -> float:
    """feel/need tools NUDGE a channel by at most ±feel_nudge_cap, never overwrite it outright
    (spec §5 E) — a model reply can no longer erase a justified grudge or hunger in one call."""
    cap = BAL["feel_nudge_cap"]
    return round(max(0.0, min(1.0, cur + max(-cap, min(cap, want - cur)))), 6)

NEED_RU = {"fatigue": "усталость", "hunger": "голод", "social": "тяга к общению",
           "purpose": "нужда в деле", "wealth": "жажда наживы", "comfort": "тяга к уюту",
           "novelty": "тяга к новизне"}
EMO_RU = {"anger": "гнев", "fear": "страх", "joy": "радость", "distress": "подавленность",
          "disgust": "отвращение"}
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
  buy    {"seller": "<имя рядом>", "good": "<его вещь>"} — сторговать вещь у того, кто РЯДОМ (платишь монетой; будете торговаться о цене)
  say    {"to": "<имя>", "text": "<реплика>"}   — сказать вслух РАДИ ЦЕЛИ (узнать/сторговаться/запугать)
  know   {"query": "<что вспоминаешь о городе/людях>"} — вспомнить факт мира (где что, кто есть кто);
                                                 ответ ляжет в память к следующему ходу
  feel   {"emotion": "anger|fear|joy|distress|disgust", "value": 0.0-1.0} — изменить свою эмоцию
  need   {"need": "hunger|fatigue|social|purpose|wealth|comfort|novelty", "value": 0.0-1.0} — свою нужду
  note   {"text": "<мысль/намерение>"}          — записать замысел в память (увидишь в след. ходы)
  promise {"to": "<имя>", "what": "<что сделаешь>", "when": "утром|днём|вечером|ночью|завтра",
           "where": "<известное место или пусто>"} — дать СЛОВО (встреча/услуга). Мир ПОМНИТ
           обещания: сдержишь — уважение, бросишь — дурная слава. Не обещай попусту.
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
    "• Есть монеты и рядом продают то, что тебе НУЖНО или ЖЕЛАННО (оружие, снедь, вещь твоей мечты) — "
    "buy: сторгуйся. Но не скупай что попало — лишь то, что тебе вправду нужно или к чему лежит душа.\n"
    "• Последствия реальны: удар ранит и убивает; кражу и нападение выдают СВИДЕТЕЛИ рядом. Преступление "
    "при толпе — глупость: выследи и жди, пока мишень останется ОДНА.\n"
    "• Хищник не только схемит, но и ДЕЙСТВУЕТ: если ты жаден/злонравен, а рядом уязвимая, богато одетая "
    "или отбившаяся цель и НЕТ свидетелей — не медли, лови момент. Это твоя роль в этой истории.\n"
    "• Боишься того, кто рядом — беги (move прочь) или бей, а не разговаривай.\n"
    "• Не топчись в толпе без дела. Выбери 1–3 инструмента, которые РЕАЛЬНО продвинут тебя этот ход.\n"
    "• Жесты и словечки — ТОЛЬКО из своей персоны; НЕ повторяй жестов и оборотов из своих прошлых "
    "ходов и из чужих реплик (все «потирают шрам» — это балаган).")


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
    aff = r.get("affinity", 0.0)
    parts = []
    if aff > 0:                                          # a KNOWN, liked face — name the bond in words so
        parts.append("близкий друг" if aff >= 0.6 else   # the NPC greets an acquaintance, not a "stranger"
                     "добрый знакомый" if aff >= 0.25 else "знакомый")
    elif aff < 0:
        parts.append(("враг" if aff <= -0.5 else "неприязнь") + f" {abs(aff):.1f}")
    if r.get("fear"):
        parts.append(f"боишься {r['fear']:.1f}")
    if r.get("trust"):
        parts.append(f"доверие {r['trust']:.1f}")
    return ", ".join(parts) or "нейтрально"


def build_prompt(state, world, percept, ctx: dict, prefs=None):
    me = percept.me
    cfg = state.config
    roles = ctx.get("roles", {})
    names = ctx.get("names", {})                   # id → human-readable name (for readable prompts and say/attack goals)
    nm = lambda i: names.get(i, i)                 # noqa: E731
    last = ctx.get("last_actions", {})
    place_desc = ctx.get("place_desc", {})

    lines = [f"ВРЕМЯ: {ctx.get('time', 'день')} (ход {ctx.get('clock', 0)}).", ""]
    sexes = ctx.get("sexes", {})
    me_sex = sexes.get(cfg.id)
    lines.append(f"ТЫ — {cfg.name}"
                 + (f", {me_sex}" if me_sex else "")
                 + f", {roles.get(cfg.id, cfg.role)}. HP {me.hp}/{me.max_hp}. "
                 "Говори о себе и спрягай глаголы СТРОГО в своём роде.")
    lines.append(f"Черты: {_traits_line(cfg.traits)}.")
    persona = ctx.get("personas", {}).get(cfg.id)  # rich persona from the pool: manner/quirk/aspirations
    if persona:
        lines.append(f"КТО ТЫ: {persona}")
    lines.append(f"Нужды: {_needs_line(state.needs)}.")
    lines.append(f"Эмоции: {_emo_line(state.emotion, state.emotion_target)}.")

    lines.append("")
    zones = ctx.get("zones", {})                   # id → zone name ('table by the window') — who is where in the building
    my_zone = zones.get(cfg.id)
    lines.append(f"МЕСТО: {me.place}. {place_desc.get(me.place, '')}"
                 + (f" Ты сейчас — {my_zone}." if my_zone else ""))
    res = world.ground.get(me.place, [])
    if res:
        lines.append("  Здесь можно воспользоваться: " + ", ".join(
            f"«{i.name}»" + (f" (закрывает: {NEED_RU.get(i.satisfies, i.satisfies)})" if i.satisfies else "")
            for i in res) + ".")
    lines.append("  Выходы: " + (", ".join(percept.exits) or "нет") + ".")
    news = ctx.get("news") or []
    if news:
        lines.append("  О ЧЁМ СУДАЧИТ ГОРОД (годные темы для беседы): " + "; ".join(news) + ".")
    my_rumor = ctx.get("rumor_of", {}).get(cfg.id)
    if my_rumor:
        lines.append(f"  ТЫ слыхал здешний слух: «{my_rumor}» — поделишься или придержишь, "
                     "дело твоё (другие могут его и не знать).")
    my_topics = (ctx.get("topics_of") or {}).get(cfg.id) or []
    if my_topics:
        lines.append("  ТВОИ ТЕМЫ (о чём тебе есть что сказать): "
                     + "; ".join(f"«{t}»" for t in my_topics[:3]) + " — заведи, к слову.")
    said = (ctx.get("pc_said") or {}).get(cfg.id)
    if said:
        lines.append(f"  ⚑ Чужак рядом только что сказал вслух: «{said}» — ответь, если тебе есть "
                     "что сказать, или занимайся своим.")
    ev = ctx.get("event")
    if ev:
        lines.append(f"  ⚡ ТОЛЬКО ЧТО: {ev} — отреагируй по своему характеру (страх/любопытство/"
                     "вмешаться/не моё дело).")
    now = ctx.get("now") or []
    if now:                                            # anti-chorus: wave sees requests from previous one
        lines.append("  ⏱ В ЭТУ САМУЮ МИНУТУ уже: " + "; ".join(now[:5]) + ". "
                     "НЕ повторяй чужое действие, жест, предмет или тему слово-в-слово — "
                     "у тебя СВОЯ жизнь: другой предмет, другая тема, или просто продолжай своё. "
                     "Если к гостю/чужаку УЖЕ обратились — не окликай его следом вторым голосом: "
                     "человек не может отвечать двоим разом; вернись к своему делу или соседу.")
    oath = ctx.get("oaths", {}).get(cfg.id)
    if oath:
        lines.append(f"  ⚑ {oath}")
    fore = ctx.get("foreshadow", {}).get(cfg.id)
    if fore:
        lines.append(f"  ⚑ {fore}")
    conv = ctx.get("convs", {}).get(cfg.id)
    if conv:
        lines.append("")
        lines.append(conv)

    if percept.present:
        lines.append("")
        lines.append("РЯДОМ С ТОБОЙ (здесь же):")
        for b in percept.present:
            wealth = "богато одет" if b.appearance >= .6 else "прилично" if b.appearance >= .4 else "простак"
            st = "повержен" if b.down() else f"HP {b.hp}"
            act = last.get(b.id, "—")
            zb = zones.get(b.id)
            bsx = sexes.get(b.id)
            lines.append(f"  • {nm(b.id)} ({(bsx + ', ') if bsx else ''}{roles.get(b.id, '?')}, "
                         f"{wealth}, {st}"
                         + (f", {zb}" if zb else "") + f"). "
                         f"Прошлый ход: {act}. Твоё отношение: {_rel_line(state, b.id)}.")
    if percept.nearby:
        lines.append("")
        lines.append("ВИДишь ПОБЛИЗОСТИ (соседние места):")
        for b in percept.nearby:
            lines.append(f"  • {nm(b.id)} ({roles.get(b.id, '?')}) — в «{b.place}». "
                         f"Прошлый ход: {last.get(b.id, '—')}.")

    hist = ctx.get("history", {}).get(cfg.id, [])
    if hist:
        lines.append("")
        lines.append("ТВОИ ПОСЛЕДНИЕ ДЕЙСТВИЯ: " + " → ".join(hist[-10:]) + ".")
    notes = [m.text for m in state.memory.items if m.kind == "note"][-5:]
    if notes:
        lines.append("ТВОИ МЫСЛИ (память): " + "; ".join(notes) + ".")

    market = [m for m in (ctx.get("market") or []) if m.get("pid") != cfg.id]
    if market:
        lines.append("")
        lines.append("ТОРГ РЯДОМ (можешь купить — buy, если НУЖНО/ЖЕЛАННО): "
                     + "; ".join(f"{m['name']} держит «{m['good']}» (~{m['price']} зм)" for m in market[:6]) + ".")
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


def _ask(manager, messages, temperature: float, who: str) -> dict:
    """Model call + JSON parsing: one retry on bad response, then LLMBadOutput.
    (Transport errors are retried and raised by ModelManager.call — not caught here.)"""
    for _attempt in range(2):
        resp = manager.call("npc_mind", messages, schema=True,
                            options={"temperature": temperature})
        data = _parse(resp.get("content"))
        if isinstance(data, dict):
            return data
    raise LLMBadOutput(f"npc_mind: ответ не разобран ({who})")


def decide_hybrid(state, world, percept, manager, ctx: dict) -> dict:
    """HYBRID: mechanical core provides ranked DRIVES (assertiveness/consistency), LLM
    chooses from top IN CHARACTER, adds dialogue and DESCRIBES what it does/thinks."""
    appraise_present(  # seeing them moves emotion/relationships FIRST (player never auto-seeded)
        state, world, percept, _race_rel(), skip_seed_id=ctx.get("player_id"),
    )
    ranked = score(state, world, percept)
    prefs = [(a.label(), (g.kind if g else "idle"), u) for a, g, u in ranked[:5]]
    data = _ask(manager, build_prompt(state, world, percept, ctx, prefs=prefs), 0.55, state.config.id)
    if not isinstance(data.get("actions"), list) or not data["actions"]:
        raise LLMBadOutput(f"npc_mind: нет actions в решении ({state.config.id})")
    return {"think": str(data.get("think", ""))[:160], "does": str(data.get("does", ""))[:160],
            "actions": data["actions"][:3], "prefs": prefs, "src": "llm"}


def decide_llm(state, world, percept, manager, ctx: dict) -> dict:
    """Full question to model. Returns {'think', 'actions':[...]}."""
    data = _ask(manager, build_prompt(state, world, percept, ctx), 0.7, state.config.id)
    if not isinstance(data.get("actions"), list):
        raise LLMBadOutput(f"npc_mind: нет actions в решении ({state.config.id})")
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
    """Reflective call (NOT every tick): nature+memory+situation → one long-term agenda.
    Mechanical core then reactively pulls current milestone. None — only if model answered
    but gave no milestones (no agenda — honest outcome, not fallback)."""
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
    data = _ask(manager, [{"role": "system", "content": _PLAN_SYS},
                          {"role": "user", "content": user}], 0.8, f"агенда {cfg.id}")
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


# ── tool sequence execution over the world ──
def _find_body(world, name):
    if not name:
        return None
    low = str(name).strip().lower()
    for b in world.bodies.values():
        if b.id.lower() == low:
            return b
    aliases = getattr(world, "aliases", None) or {}         # human-readable name → id (live location)
    bid = aliases.get(low)
    return world.bodies.get(bid) if bid else None


def _find_item(items, name):
    if not name:
        return None
    low = str(name).strip().lower()
    return next((i for i in items if low in i.name.lower() or i.name.lower() in low), None)


def apply_actions(actions, state, world, clock: int) -> list:
    """Execute tool sequence. Returns list of event strings (for log)."""
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
                    names = getattr(world, "names", None) or {}
                    who = names.get(me.id) or me.id        # to memory — NAME, not bare id
                    vs.memory.add(f"{who} сказал(а) мне: «{txt}»", clock, importance=0.4,
                                  kind="heard", about=[me.id])
                log.append(f"💬{tb.id}:«{txt[:40]}»")
            else:
                log.append(f"💬:«{txt[:40]}»")
        elif tool == "know":
            q = str(a.get("query") or "")[:80]
            fn = getattr(world, "lookup", None)             # world knowledge resolver is hung by world owner
            if fn and q:
                info = str(fn(q))[:220]
                state.memory.add(f"вспомнил: {info}", clock, 0.45, kind="fact")
                log.append(f"🧠{q[:32]}")
            else:
                log.append("know✗")
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
                state.emotion[e] = _nudge(state.emotion.get(e, 0.0), float(v))
                log.append(f"~{EMO_RU.get(e, e)}={v}")
        elif tool == "need":
            n, v = a.get("need"), a.get("value")
            if n in state.needs and isinstance(v, (int, float)):
                state.needs[n] = _nudge(state.needs.get(n, 0.0), float(v))
                log.append(f"~{NEED_RU.get(n, n)}={v}")
        elif tool == "note":
            state.memory.add(str(a.get("text", ""))[:120], clock, importance=0.5, kind="note")
            log.append("✎")
        elif tool == "promise":                      # OATH: memory to both sides; world writes deed
            to = str(a.get("to") or "")
            tid_ = _find_body(world, to)
            what = str(a.get("what") or "")[:100]
            when = str(a.get("when") or "")[:20]
            state.memory.add(f"я дал(а) слово ({to}): {what} — {when}", clock, 0.7,
                             kind="note", about=[tid_.id] if tid_ else [])
            if tid_ is not None and tid_.id in getattr(world, "npc_minds", {}):
                world.npc_minds[tid_.id].memory.add(
                    f"{getattr(state.config, 'name', '?')} дал(а) мне слово: {what} — {when}",
                    clock, 0.6, about=[state.config.id])
            log.append(f"слово→{to}: {what[:40]}")
        elif tool == "wait":
            log.append("·")
    return log or ["·"]


def _build_prompt_probe(state, ctx: dict) -> str:
    """Test hook: render just the foreshadow/oath context line for a state (no LLM)."""
    cfg = state.config
    out = []
    fore = ctx.get("foreshadow", {}).get(cfg.id)
    if fore:
        out.append(f"  ⚑ {fore}")
    return "\n".join(out)
