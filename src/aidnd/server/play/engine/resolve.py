"""АРБИТР свободного ввода — единый resolve(text) (docs/loop.md «Дальше», принцип 3).

Примитивы объявляет КОД: реестр PRIMITIVES — единственная истина (глагол, цели, «когда»).
Промпт арбитра ГЕНЕРИТСЯ из реестра: добавить примитив = одна запись, рукописного списка
глаголов в прозе больше нет. Контекст-сборщик отдаёт арбитру МАКСИМУМ фактов сцены (люди,
ёмкости, сумка, зоны, предметы рядом, места города, время) — арбитр сам парсит намерение
и цели; исполнители (примитив×манера×гейты) живут в handlers/freeform._attempt.

Key functions
-------------
resolve(text: str, sc: dict) -> dict | None : Parse player input to verb-target-manner plan via LLM arbiter.
assemble_context(sc: dict) -> str : Gather scene facts (NPCs, items, zones) for arbiter.
normalize_plan(out: dict, cap: int = 3) -> dict : Validate and clean arbiter response into executable plan.
_voice(p, rel, kind, player_text) -> str : NPC speaks in-character (LLM narrator) — folds in persona,
    memory of the player, grudges and world-lookup facts; records the player's tone. [moved from world.py]
_world_lookup(query, from_node) -> str : truthful world facts (buildings with a route, locals) for the
    know/ask tool — never lets the model invent the city. [moved from world.py]
_dm_snapshot(sc: dict) -> str : narrator snapshot of the live scene (place/time, who is where, audible
    lines, nearby items) so the DM describes THIS world, not an invented one. [moved from world.py]
"""

from __future__ import annotations

import json

from aidnd.server.play.engine.core import (
    _PHASE_RU,
    _S,
    PLAYER,
    _binfo,
    _city_name,
    _display,
    _gt,
    _mark_seen,
    _model,
    _mt,
    _phase,
    _spurns,
    _store,
    _wid,
)

# Реестр примитивов: цели — какие поля обязаны быть заполнены; when — как узнать намерение.
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
    """Промпт арбитра из реестра — код объявил примитивы, проза производная."""
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
    zid_of = {v: k for k, v in (lv.get("zone_names") or {}).items()}
    afar, total = [], 0
    for zpl, imap in (lv.get("zone_items") or {}).items():   # видимое ГЛАЗАМИ по чужим зонам
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
    return normalize_plan(out)


def normalize_plan(out: dict, cap: int = 3) -> dict:
    """Ответ арбитра → честный план: список звеньев-словарей, кап длины, wait-балласт
    выброшен из цепочек (wait осмыслен только соло — как не-действие для нарратора)."""
    steps = out.get("plan") if isinstance(out.get("plan"), list) else None
    if steps is None:
        steps = [out]                                # обратная совместимость: один шаг
    steps = [s for s in steps if isinstance(s, dict)]
    if str(out.get("verdict") or "") == "narrate":
        d = next((s.get("detail") for s in steps if s.get("detail")), out.get("detail"))
        steps = [{"verb": "wait", "detail": d or ""}]
    if len(steps) > 1:
        steps = [s for s in steps if (s.get("verb") or "wait") != "wait"] or steps[:1]
    return {"verdict": out.get("verdict") or "do", "plan": steps[:cap]}


# ─── Сервисы нарратора/арбитра, переехавшие из world.py (docs/structure.md, Phase B) ────────
# Голос NPC, справка мира и DM-снимок — это арбитр/нарратор-слой, не сцена; их дом здесь.
_VOICE = {
    "gruff": "грубовато",
    "warm": "тепло",
    "clipped": "сухо и коротко",
    "florid": "витиевато",
    "meek": "робко",
    "booming": "громко, зычно",
}
_STANCE = {
    "warm": "дружелюбно",
    "neutral": "нейтрально",
    "wary": "настороженно",
    "dour": "хмуро",
    "greedy": "с расчётом на выгоду",
    "hostile": "враждебно",
}


def _voice(p, rel, kind, player_text=None) -> str:
    mgr = _model()
    per = getattr(p, "persona", None) or {}
    bits = [f"Ты — {p.name}, {p.role} на фронтире (тёмное фэнтези)."]
    if per:  # богатая персона из пула
        if per.get("origin"):
            bits.append(f"Родом: {per['origin']}.")
        if per.get("voice"):
            bits.append(f"Говоришь {_VOICE.get(per['voice'], 'обычно')}.")
        if per.get("speech"):
            bits.append("Речевые привычки: " + "; ".join(per["speech"][:2]) + ".")
        if per.get("quirk"):
            bits.append(f"Причуда: {per['quirk']}.")
        if per.get("wants"):
            bits.append("Стремишься: " + "; ".join(per["wants"][:2]) + ".")
        bits.append(f"К чужаку держишься {_STANCE.get(per.get('stance'), 'нейтрально')}.")
        if per.get("secret"):
            bits.append(
                f"У тебя есть тайна (НЕ выдавай без веской причины): {per['secret'].get('what', '')}."
            )
    if _spurns(p):  # обида/гнев ПЕРЕВЕШИВАЮТ радушие персоны
        bits.append(
            "Ты ЗОЛ на этого человека (вспомни, почему) — никакого радушия: "
            "холод, резкость или презрение, по твоему характеру."
        )
    here_name = _binfo(_S.get("inside"))["name"] if _S.get("inside") else "улица города"
    bits.append(
        f"МЕСТО: город называется «{_city_name()}», вы сейчас — {here_name}. "
        "КАНОН: о людях и местах ЭТОГО города говори только то, что есть в памяти и справке — "
        "здешних имён и заведений не выдумывай (и город зови ТОЛЬКО его настоящим именем). "
        "Вымысел допустим лишь о дальних краях и былом, и подавай его как слух."
    )
    bits.append(
        "СОБЕСЕДНИК — чужак-путник. Его внешности, одежды и имени ты НЕ ЗНАЕШЬ, пока он сам "
        "не показал/назвал — НЕ приписывай ему одежд, черт и званий (не путай его с другими "
        "посетителями из памяти)."
    )
    lv = _S.get("live") or {}
    just = (lv.get("last") or {}).get(p.id)
    if just and just != "—":
        bits.append(f"Только что ты: {just}.")
    mems = p.state.memory.recall(player_text or "разговор с чужаком-игроком", now=_mt(), k=5)
    mine = [m for m in mems if PLAYER in (m.about or [])]
    other = [m for m in mems if PLAYER not in (m.about or [])]
    if mine:  # непрерывность: NPC помнит ИМЕННО вас
        bits.append("ТЫ ПОМНИШЬ О СОБЕСЕДНИКЕ: " + "; ".join(m.text for m in mine) + ".")
    if other:  # прочее — фон, НЕ про собеседника
        bits.append(
            "ПРОЧЕЕ ИЗ ПАМЯТИ (про ДРУГИХ людей, НЕ про собеседника — не смешивай): "
            + "; ".join(m.text for m in other)
            + "."
        )
    if player_text:  # вопрос о мире → справка сразу (не выдумывать)
        info = _world_lookup(player_text, _S.get("loc"))
        if "не скажу" not in info:
            bits.append(
                f"СПРАВКА МИРА (это истина — придерживайся её, имена и места не выдумывай): {info}."
            )
    bits.append(
        f"Симпатия к собеседнику {rel.get('affinity', 0):.2f} (низкая — суше/настороже, высокая — теплее). "
        "Отвечай В ХАРАКТЕРЕ, живой разговорной речью, 1-2 фразы, без ремарок-описаний. "
        "Помнишь собеседника — покажи это естественно, не пересказывай память дословно. "
        'ФОРМАТ — строго JSON: {"say": "<реплика>", "player_tone": '
        '"friendly|neutral|rude|threat"} (player_tone — как звучали слова СОБЕСЕДНИКА к тебе). '
        "Если для ответа НУЖЕН факт о городе или людях (где что находится, кто есть кто) — "
        'верни СТРОГО JSON {"ask": "<короткий вопрос>"} вместо реплики: получишь справку и ответишь.'
    )
    acquainted = any(PLAYER in (m.about or []) for m in p.state.memory.items)
    user = (
        (
            "К тебе снова подошёл тот самый человек, которого ты помнишь, — поприветствуй его "
            "КАК ЗНАКОМОГО, опираясь на то, что помнишь."
            if acquainted
            else "К тебе подошёл незнакомец и заговорил — брось первую реплику."
        )
        if kind == "greet"
        else f"Он говорит: «{player_text}». Ответь."
    )
    msgs = [{"role": "system", "content": " ".join(bits)}, {"role": "user", "content": user}]
    resp = mgr.call("narrator", msgs, options={"temperature": 0.85})
    content = (resp.get("content") if resp else "").strip()

    def _parse(c):
        i, j = c.find("{"), c.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(c[i : j + 1])
            except (json.JSONDecodeError, ValueError):
                return None
        return None

    d = _parse(content)
    if d and d.get("ask"):  # тулкол ask: справка мира → второй заход
        info = _world_lookup(str(d["ask"]), _S.get("loc"))
        msgs += [
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": f"СПРАВКА МИРА: {info}. Теперь ответь собеседнику (тот же JSON-формат).",
            },
        ]
        resp = mgr.call("narrator", msgs, options={"temperature": 0.85})
        content = (resp.get("content") if resp else "").strip()
        d = _parse(content)
    if d and d.get("say"):
        _S["last_tone"] = d.get("player_tone") or "neutral"
        return str(d["say"]).strip() or f"{p.name} молчит."
    _S["last_tone"] = "neutral"
    return content or f"{p.name} молчит."


def _world_lookup(query: str, from_node: int | None = None) -> str:
    """Справка мира для тулкола know/ask: здания (с дорогой от точки), люди (местные знают местных).
    Отвечает ТОЛЬКО реальными фактами графа/пула — не даёт LLM галлюцинировать о городе."""
    city, people = _S.get("city"), _S.get("people") or {}
    if city is None:
        return "не припомню"
    q, outs = query.lower(), []
    for bid, kb in sorted(city.key_buildings.items()):
        info = _binfo(bid)
        nm = info["name"]
        words = (nm + " " + info["kind"]).lower().replace("«", " ").replace("»", " ").split()
        if any(w[:5] in q for w in words if len(w) > 3):
            _mark_seen(bid)  # рассказали — теперь знаешь, метка на карте
            if from_node is not None:
                r = city.route(from_node, kb.node)
                if r.found:
                    outs.append(
                        f"{nm}: {r.bearing or 'недалеко'}, ~{max(1, len(r.nodes) - 1)} мин ходу"
                    )
                    continue
            outs.append(nm)
    for _pid, p in sorted(people.items()):
        first = p.name.split()[0].lower()
        if p.role in q or first in q or p.name.lower() in q:
            place = _binfo(p.work)["name"] if p.work else None
            outs.append(f"{p.name} — {p.role}" + (f", обычно в «{place}»" if place else ""))
        if len(outs) >= 3:
            break
    return "; ".join(outs[:3]) if outs else "точно не скажу — не знаю такого"


def _dm_snapshot(sc: dict) -> str:
    """СНИМОК живой сцены для нарратора: место/время/погода, кто где и чем занят, последние
    реплики, предметы вокруг игрока. Нарратор ОПИСЫВАЕТ этот мир, а не выдумывает свой."""
    lv = _S.get("live") or {}
    amb = (sc or {}).get("ambient") or {}
    parts = [f"МЕСТО: {(sc.get('location') or {}).get('name', lv.get('place', 'улица'))}. "
             f"{lv.get('pdesc', '')}",
             f"ВРЕМЯ: {amb.get('time', _PHASE_RU[_phase()])}, {_gt() // 60 % 24:02d}:{_gt() % 60:02d}; "
             f"погода: {amb.get('weather', '—')}; в зале {amb.get('mood', '—')}."]
    w = lv.get("world")
    people = _S.get("people") or {}
    if w is not None:
        pb = w.bodies.get(PLAYER)
        if pb is not None:
            parts.append(f"ИГРОК сейчас: {pb.place}.")
            objs = [i.name for i in (w.ground.get(pb.place) or [])][:8]
            if objs:
                parts.append("Рядом с игроком: " + ", ".join(objs) + ".")
        folks = []
        for pid in list(w.npc_minds)[:8]:
            if pid == PLAYER or w.bodies[pid].down():
                continue
            folks.append(f"{_display(pid, people)} ({w.bodies[pid].place}) — "
                         f"{(lv.get('last') or {}).get(pid, 'занят собой')}")
        if folks:
            parts.append("ЛЮДИ: " + "; ".join(folks) + ".")
        lines = []
        my = (lv.get("zonemap") or {}).get(PLAYER)
        ev = _S.get("eaves") or {}
        for c in (lv.get("convs") or [])[-3:]:
            znm = (lv.get("zone_names") or {}).get(c.get("zone"))
            audible = (PLAYER in (c.get("members") or []) or c.get("zone") == my
                       or (znm and znm == ev.get("place")))
            if not audible:                          # чужой стол — нарратору не дарим
                continue
            for who, txt in c.get("log", [])[-2:]:
                lines.append(f"{lv.get('names', {}).get(who, who)}: «{txt[:70]}»")
        if lines:
            parts.append("ПОСЛЕДНИЕ РЕПЛИКИ (что игроку слышно): " + " | ".join(lines[-5:]))
    return "\n".join(parts)
