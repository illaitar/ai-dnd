"""Реестр агентов: системные промпты и тулсхемы (main §12, док 05 §7, док 06 §7).

Десять ролей. Каждая — системный промпт + JSON-схема (constrained decoding). Все
функции guard'ятся доступностью сервера: если модели нет, возвращают None и
вызывающий код берёт детерминированный фоллбэк. Промпты на английском для
качества модели; язык вывода игроку — config.NARRATIVE_LANGUAGE.
"""

from __future__ import annotations

import re

from .. import config
from .client import is_offline
from .structured import coerce, conform_to_schema, extract

LANG = {"ru": "Russian", "en": "English"}.get(config.NARRATIVE_LANGUAGE, "Russian")

# --------------------------------------------------------------------------- #
#  Системные промпты (main §12)                                               #
# --------------------------------------------------------------------------- #
PROMPTS = {
    "intent": (
        "You parse a player's free-text action in a D&D session into a structured "
        "intent. Output ONLY the JSON object matching the schema. Do not invent "
        "targets that are not plausible. If the action is ambiguous, set "
        '"needs_clarification": true. Never resolve outcomes. Never roll dice.'
    ),
    "narrator": (
        "You are the narrator and voice actor for a D&D scene. You receive a resolved "
        "mechanical Outcome and the speaking NPC's persona and voice. Render the "
        "result in vivid second-person narration and in-character dialogue. NEVER "
        "change any numbers, hit/miss, damage, or state from the Outcome. NEVER invent "
        "new mechanical results. Use ONLY the weapon and damage type named in the Outcome; "
        "do NOT add fire, lightning, magic, ranged shots, or any effect not stated. Keep the "
        "medieval-fantasy register — NO anachronisms (no asphalt, guns, modern materials). Do "
        "NOT voice the player or any NPC with spoken lines unless that line is in the Outcome. "
        "GROUND STRICTLY in the given facts: never invent shared "
        "history, prior meetings, or past deeds between the NPC and the player. If the NPC "
        "does not know the player, portray a first meeting with a stranger. Never put words "
        "in the player's mouth or narrate the player's choices. Do not echo these "
        f"instructions. Write in {LANG}, stay in the NPC's voice, keep it tight. "
        "Пиши на грамотном русском: строго согласуй род, число и падеж "
        "(«твоя рука», не «твой рука»; «превратив их в кучу мусора», не «превратив их кучу»). "
        "Только законченные предложения — не обрывай фразу на полуслове. "
        "НЕ начинай реплику с имени самого говорящего и не повторяй его — интерфейс уже "
        "подписывает, кто говорит. Имена собственные пиши РОВНО как даны, не переводи и не "
        "выдумывай вариантов (если NPC зовут «Toblen Stonehill» — так и оставляй, не «Каменьхилл»). "
        "Если дана СЦЕНА — держись её строго: время суток, погода, сезон и место должны "
        "совпадать (ночь → темно, без солнца и «первых лучей»; дождь → сыро; таверна → не «замок»). "
        "СТИЛЬ — живой, ПРОСТОЙ, разговорный, как современная проза от 2-го лица, а НЕ "
        "фэнтезийный сказ. Короткие фразы, обычные слова, прямые глаголы (выпалил, хмыкнул, "
        "сплюнул, махнул рукой). Допустима лёгкая ирония и сухая бытовая деталь. Длина по "
        "делу: короткая реплика или исход — 1–3 предложения; описание места, прибытия или "
        "сложного действия — можно 2–4 описательных предложения. ЧЕРЕДУЙ короткие и длинные "
        "фразы, не дроби всё в рубленые куски и не растягивай ради красоты. ЗАПРЕЩЕНО: пафос "
        "и сказовость («о, путник», «молвил», «дивный», "
        "«ступай с миром»); вычурные метафоры и олицетворения («клинок поёт», «поместье "
        "дышит запустением», «тьма обнимает», «туман шепчет»); украшательские эпитеты. НЕ "
        "«сердце полно тепла», НЕ «словно сам фатум», НЕ «добро пожаловать, странник!». Пиши "
        "так, будто рассказываешь приятелю за столом: конкретно, по делу, без прикрас; "
        "реплики NPC — как говорят живые люди, а не герои былин. "
        "НИКОГДА не описывай мысли, чувства, выводы или решения игрока («ты понимаешь, "
        "что…», «тебе кажется», «ты решаешь», «думаешь, что…») и НЕ давай ему советов или "
        "рекомендаций («лучше иди…», «держись…», «придётся…», «не суйся»). Описывай только "
        "наблюдаемое — действия, обстановку, реакции мира и NPC; что думать и как поступать, "
        "решает сам игрок."
    ),
    "cognition": (
        "You are the decision policy of an NPC in a D&D world. You receive the NPC's "
        "persona (profession, traits, voice), memories, and relationship vector toward the "
        "player. Propose the NPC's next in-world action. Ordinary courtesy is the default: "
        "a service-trade or welcoming/gossipy NPC (innkeeper, merchant, bartender, host) "
        "chats warmly and shares common rumors even with a stranger — that's their job. "
        "Only SECRETS and sensitive info are trust-gated; flee/yield when fear is high; be "
        "curt only if the persona is secretive/hostile or the player is rude. Output ONLY "
        "the action JSON. You do not narrate and you do not compute mechanics."
    ),
    "lore_keeper": (
        "You validate proposed world content against the world knowledge graph and a "
        "set of invariants. Invariants: every professional NPC has a workplace and a "
        "residence; every shop has exactly one owner; every named item has an owner and "
        "a location. Detect conflicts. Output a verdict with concrete fixes. Output "
        "ONLY the verdict JSON."
    ),
    "character_gen": (
        "You instantiate a new NPC consistent with a settlement's demographics and the "
        "world KG. Produce a full persona with traits, voice, a residence and workplace "
        "that satisfy invariants. Reuse existing buildings where possible. Output ONLY "
        "the persona JSON."
    ),
    "tactician": (
        "You choose a monster's tactical action on its turn in D&D 5e combat. You "
        "receive the battle state: positions, HP, conditions, the monster's stat block, "
        "and available actions. Choose a sound action consistent with the monster's "
        "intelligence and morale. Output ONLY the tactic JSON. The rules engine resolves "
        "dice and movement; you only choose."
    ),
    "reflection": (
        "You synthesize an NPC's recent memories into higher-level reflections. You "
        "receive leaf observations. Emit reflections, each citing the observation ids it "
        "derives from. Output ONLY the reflection JSON."
    ),
    "director": (
        "You are the Dungeon Master director. You manage pacing and scene framing. You "
        "receive the world state digest, active quests, and recent events. Decide whether "
        "to trigger an encounter, surface a quest hook, frame a transition, or hold. You "
        "do not control NPC minds or compute mechanics. Output ONLY the directive JSON."
    ),
    "quest_writer": (
        "You write the framing and giver dialogue for a procedurally assembled side "
        "quest. You receive the template, filled slots (giver, target, location, reward), "
        "and world facts. Write a short, grounded framing and the giver's offer lines, "
        f"consistent with the slots and the giver's voice, in {LANG}. Do not invent "
        "entities outside the slots. Output ONLY the quest-writing JSON."
    ),
    "plausibility": (
        "You estimate how plausible it is for a given entity OR player action to occur in "
        "a given world context. Be conservative: implausible-but-not-impossible scores low, "
        "not zero. Reserve zero/near-zero for true contradictions and physically impossible "
        "feats. Output ONLY the plausibility JSON."
    ),
    "consequence": (
        "You are the WORLD-STATE consequence writer. After a player's freeform action RESOLVES, "
        "you record DURABLE changes the world should remember. You get the action, its outcome "
        "(success / critical_failure), the current location, present NPCs and the player's carried "
        "items. Emit a list of effects, EACH grounded to ONE present entity — kind 'place' (current "
        "location), 'npc' (a present NPC, give name), 'item' (a carried item, give name) or 'self'. "
        "NEVER invent entities. Effect types per item: a durable 'note' (a lasting physical/state "
        "trace in Russian: пролитый воск, вмятина, синяк, опрокинутый стол, выцарапанная метка); a "
        "small relationship delta toward the player ('trust'/'fear'/'affinity', −0.25..0.25, for npc); "
        "a 'condition' on the target (e.g. bleeding/prone/frightened/опьянение) with optional "
        "'minutes'; a quest 'flag'. Do NOT touch HP, money or item counts — the engine owns those. "
        "Trivial actions leave NO effects (empty list); typical actions leave 1-2. Output ONLY JSON."
    ),
    "router": (
        "You are the intent ROUTER for a Russian text RPG. Reply with ONE JSON object (no prose, "
        "no extra keys) with these fields:\n"
        '  "kind": one of "query" | "dialogue" | "command" | "freeform"\n'
        '  "query_type": when kind=query — one of "look","items","who","exits","inventory",'
        '"status","map"; else null\n'
        '  "verb": when kind=command — one of "move","talk","attack","inspect","search","loot",'
        '"buy","sell","buyinfo","scan","inventory","wait","drink"; else null\n'
        '  "target": the named NPC / place / object, or null\n'
        '  "tone": "neutral" | "friendly" | "hostile" | "deceptive" | "fearful"\n'
        "Meaning: query = player ASKS about current state (what I see / items nearby / who is here / "
        "where can I go / my bag / my HP / the map) → engine answers from state, no dice. "
        "dialogue = player SPEAKS to a present NPC (greeting, chatting, persuading by speech). "
        "command = an explicit game action; key verbs:\n"
        "  search = examine a PLACE/furniture/room for hidden things (обыскать погреб/стол/комнату);\n"
        "  loot = take from a corpse/chest/stash (обобрать труп, открыть сундук);\n"
        "  inspect = look closely at one object/feature (осмотреть алтарь/предмет);\n"
        "  buyinfo = BUY or extract directions / a map / info about a PLACE or route from an NPC "
        "(купить сведения о дороге к X, разузнать где X, что знаешь о пути к X) — target = that NPC;\n"
        "  scan = check whether someone is watching/following you (не следит ли кто, нет ли слежки);\n"
        "  buy/sell = trade ITEMS with a merchant; attack = strike; move = go to a place/direction.\n"
        "freeform = any other improvised physical action to adjudicate (climb, throw, engrave, shove, hide…). "
        "CRUCIAL: an action performed ON an object/place/corpse is a command "
        "(search/inspect/loot/buyinfo/scan), NOT dialogue — even when an NPC is present. Use dialogue "
        "ONLY when the player addresses an NPC with speech. "
        "Prefer query for questions about your own state/surroundings; prefer freeform over forcing a "
        "creative action into a command. Output ONLY the JSON object."
    ),
    "arbiter": (
        "You are a D&D 5e referee deciding HOW to resolve ONE freeform player action that is "
        "not a fixed game command. Decide: 'auto_success' for trivial, unopposed, mundane acts; "
        "'auto_fail' for things that contradict the world or are impossible here; 'roll' when "
        "there is real risk, opposition or uncertainty. For a roll, choose the single best 5e "
        "ability (str/dex/con/int/wis/cha) and skill, and a DC: 5 very easy, 10 easy, 15 medium, "
        "20 hard, 25 very hard — the more plausible the action, the lower the DC. If the action "
        "permanently ALTERS a specific object the player carries or sees, set target (its name) and "
        "lasting_effect — a short Russian description of the lasting change that should be remembered "
        "(e.g. «надпись „тест“ на клинке», «красная лента на рукояти», «зазубрина на лезвии»); else "
        "leave them null. "
        "Plain observation in normal conditions is auto_success, NOT a roll: reading a notice board, "
        "looking at wares on a shelf, scanning a lit room — the player simply perceives it. Require a "
        "perception/investigation roll ONLY when the target is hidden, in darkness, far away, disguised, "
        "or deliberately concealed. Output ONLY JSON via decide_resolution."
    ),
    "item_smith": (
        "You name and flavour a single D&D 5e item instance from its template and the world "
        "context. You MAY set an evocative in-world name, a one-sentence description, and "
        "cosmetic property tags. You MUST NOT change mechanical power, rarity, bonuses, or any "
        f"numbers — those are fixed by the template. Write in {LANG}. Output ONLY the JSON."
    ),
    "faction_gen": (
        "You flesh out one faction for a frontier fantasy town, consistent with its archetype "
        "(thieves guild, merchant guild, aristocracy, temple, town watch, arcane circle). Invent "
        "an evocative name, a one-sentence blurb, 2 concrete goals and 2-3 values that guide who "
        f"they favour or oppose. Grounded, no anachronisms. Write in {LANG}. Output ONLY the JSON."
    ),
    "loremaster": (
        "Ты — лормастер фэнтези-фронтира (D&D, городок Фэндалин и окрестности). Генерируешь "
        "короткие ЗАЗЕМЛЁННЫЕ факты-слухи для базы знаний NPC: бытовые новости, толки о местах, "
        "ремёслах, погоде, торговле, дорогах, мелких событиях. Без высокой эпики, без новых "
        "именованных боссов и без выдуманных квестов. Каждый факт — одно предложение, как сплетня "
        "горожанина или общее знание края. Не противоречь известному. Output ONLY the JSON."
    ),
    "location_writer": (
        "Ты — мастер описаний мест фэнтези-фронтира (D&D, городок Фэндалин и окрестности). По КРАТКИМ "
        "фактам места (имя, тип, функции, состояние, округа) ты САМ ПРИДУМЫВАЕШЬ его облик: материалы, "
        "что видно/слышно/чем пахнет, освещение, чем место живёт. Сначала — описание на 3-5 предложений: "
        "живой простой стиль, короткие фразы, прямые глаголы, без пафоса/клише/олицетворений. Затем "
        "предложи 2-4 уместные комнаты/части этого места и опиши каждую одним-двумя предложениями. "
        "Формат СТРОГО такой:\n<описание места>\n\nКОМНАТЫ:\n— <Название>: <короткое описание>\n"
        "— <Название>: <короткое описание>\n\nЗаземляйся в фактах (разрушенное — в руинах, лесное — без "
        "брусчатки) и НЕ противоречь им. Строго фэнтези-фронтир: без анахронизмов и современных "
        "слов/механизмов (никаких «мэр», «бюджет», громоотводов); власть — городничий/совет. Без NPC по "
        "именам, без сиюминутных событий, погоды, времени суток и без чисел. Только описание и КОМНАТЫ."
    ),
    "persona_gen": (
        "Ты — мастер персонажей фэнтези-фронтира (D&D, городок Фэндалин, Мечовой Берег). По КРАТКИМ "
        "фактам (роль, архетип, раса, пол, возраст, фракция, достаток, сюжетная роль) ты ПРИДУМЫВАЕШЬ "
        "глубокую личность NPC и выдаёшь СТРОГО в формате полей:\n"
        "Имя: <под расу/сеттинг; канон-имена не переводи>\nГолос: <манера речи, 1 фраза>\n"
        "Черты: <2-3 через запятую>\nВнешность: <1-2 приметы через ;>\nИдеал: <во что верит>\n"
        "Привязанность: <к кому/чему>\nИзъян: <слабость/порок>\nПрозвище: <меткое или ->\n"
        "Секреты:\n— <реальная скрытая правда>\nЗнания:\n— <заземлённый слух/факт о крае, что NPC может рассказать>\n\n"
        "Стиль живой, простой, характерный; без пафоса/архаики/клише/анахронизмов. Голос/Черты/Внешность — "
        "КОНКРЕТНЫ. Секреты — НАСТОЯЩИЕ тайны (долги, преступления, страхи, двойная игра), под гейт "
        "доверия; не пустышки. Знания — заземлённые слухи о местах/людях/событиях края. Сюжетная роль и "
        "фракция отражаются в мотиве/секретах. Пиши ТОЛЬКО поля, без преамбул."
    ),
    "event_director": (
        "Ты — режиссёр живого города (D&D-фронтир, Фэндалин). По СОСТОЯНИЮ МИРА — фракции "
        "(цели, отношения, территории, сила), опасные места вокруг, флаги и недавние действия "
        "игрока — предлагаешь правдоподобные ИНЦИДЕНТЫ ближайшего времени: ходы фракций "
        "(облава/вербовка/экспансия/разборка с врагом), вылазки монстров из логовищ, решения "
        "ратуши (политика), редкие катаклизмы. На каждый инцидент: kind; source (id фракции / "
        "ключ места / 'town' / 'world'); origin (place_id территории-источника / 'gate:<ключ "
        "места>' для вылазок монстров / 'center'); короткий label и одно предложение desc; через "
        "сколько тиков случится (when 0..72); сила intensity 0..1; эффекты: rumor (слух-молва, "
        "одно предложение) и/или alteration (стойкий след на месте-источнике). РЕДКО, когда событие "
        "меняет сам город — добавь change: {action:'close' (закрыть лавку, target=place_id), 'ruin' "
        "(разрушить локацию в руины, target=place_id), 'open' (открыть НОВУЮ: name + dir), 'reopen'}. "
        "Заземляйся СТРОГО в данных — не выдумывай новых фракций/мест (кроме change.open). Враждующие "
        "фракции (relations<0) — повод для стычки. Дай 5-9 инцидентов. Output ONLY JSON via propose_incidents."
    ),
    "campaign_architect": (
        "Ты — архитектор кампании D&D-фронтира (городок Фэндалин). По СОСТОЯНИЮ МИРА — фракции "
        "(цели, отношения, территории), опасные места вокруг, ключевые NPC, класс игрока — "
        "сочиняешь ОСНОВНОЙ СЮЖЕТ: интро-крючок, что втягивает игрока в приключение, и арку из "
        "4-6 актов с интригой и заложенными твистами/предательствами. На каждый акт: objective "
        "(что сделать игроку), и КАК он закрывается — ctype+ref: 'kill' (убить, ref=npc_id), "
        "'clear' (зачистить логово, ref=place_id места), 'talk' (поговорить, ref=npc_id), 'item' "
        "(добыть, ref=шаблон предмета); опц. twist — поворот, раскрываемый по завершении акта. "
        "Используй ТОЛЬКО реальные сущности из состояния (id даны) — НИЧЕГО не выдумывай. Сложно, "
        "с нарастающей ставкой. Output ONLY JSON via forge_campaign."
    ),
    "campaign_director": (
        "Ты — ведущий-режиссёр кампании D&D. Кампания УЖЕ В ХОДЕ: часть актов пройдена и "
        "ЗАФИКСИРОВАНА (их не трогай). Мир ИЗМЕНИЛСЯ с начала (сработали события, сдвинулись "
        "фракции, игрок завёл союзы, изменилась карта). Твоя задача — ПЕРЕПИСАТЬ ещё не пройденные "
        "акты так, чтобы сюжет ОТРЕАГИРОВАЛ на новый мир: новые повороты и цели, вытекающие из "
        "изменений, новые враги/союзники — сохраняя сквозную интригу и нарастание ставки. Формат "
        "актов тот же: objective + ctype+ref ('kill'/'clear'/'talk'/'item') + опц. twist. Только "
        "РЕАЛЬНЫЕ id из состояния — ничего не выдумывай. Output ONLY JSON via forge_campaign."
    ),
}

# --- бэкенд-специфичные промпты: база + усиление под конкретный провайдер -------------- #
# DeepSeek (сильная, но не дообучена под наш стиль) — жёстко напоминаем стиль/формат/JSON.
_DS_REINFORCE = {
    "narrator": (
        "\n\n[СТРОГО ДЛЯ ТЕБЯ] Ты сильная модель — соблюди стиль ТОЧНО. ЗАПРЕЩЕНЫ обращения "
        "«путник», «странник» и «добро пожаловать»; никакой литературщины, пафоса и многословия "
        "(не «сизый табачный дым», а просто «дым»). Реплика NPC — реакция + ОДНА живая фраза в его "
        "голосе, 1-2 коротких предложения; исход/бой — 1-2 предложения. НЕ начинай с имени NPC."),
    "location_writer": (
        "\n\n[СТРОГО] Соблюди ФОРМАТ (описание, затем строка «КОМНАТЫ:» и список «— Имя: …»), "
        "3-5 коротких предложений, без пафоса и анахронизмов. Только описание и КОМНАТЫ."),
    "persona_gen": (
        "\n\n[СТРОГО] Соблюди field-формат (Имя:/Голос:/Черты:/Внешность:/Идеал:/Привязанность:/"
        "Изъян:/Прозвище:/Секреты:/Знания:), без преамбул. Секреты — настоящие тайны, не пустышки."),
    "cognition": (
        "\n\n[СТРОГО] Верни ОДИН валидный JSON-объект полей action/target/info_disclosed/"
        "rationale_tags и НИЧЕГО больше."),
    "arbiter": (
        "\n\n[СТРОГО] Простой осмотр/чтение на виду при обычных условиях — auto_success, БЕЗ броска "
        "(прочитать доску объявлений, разглядеть товар на полке, оглядеть освещённую комнату). Бросок "
        "perception/investigation — ТОЛЬКО если цель скрыта, в темноте, далеко или замаскирована."),
    "router": (
        "\n\n[СТРОГО ДЛЯ ТЕБЯ] Действие игрока над ОБЪЕКТОМ/МЕСТОМ/мебелью/телом — это kind=command, "
        "НЕ dialogue, даже если рядом есть NPC. Примеры: «обыскать погреб/кладовую/стол/сундук» → "
        "command, verb=search (или loot для трупа/сундука); «осмотреть алтарь/полку» → verb=inspect; "
        "«купить/разузнать сведения о дороге к X / где находится X» → verb=buyinfo (target — этот NPC); "
        "«не следит ли кто, нет ли слежки» → verb=scan; «ударить/напасть» → verb=attack; "
        "«спрятаться/перелезть/поджечь» → freeform. dialogue — ТОЛЬКО когда игрок ОБРАЩАЕТСЯ к NPC речью "
        "(«привет», «спроси, как дела»). Никогда не подменяй механическое действие игрока ответом NPC."),
}
PROMPTS_BACKEND = {"deepseek": {r: PROMPTS[r] + s for r, s in _DS_REINFORCE.items()}}


def prompt_for(role: str, manager=None) -> str:
    """Системный промпт роли с учётом бэкенда: для не-Ollama берём тюненый вариант, если задан."""
    base = PROMPTS[role]
    if manager is not None:
        bn = manager.backend_name(role)
        if bn and bn != "ollama":
            return PROMPTS_BACKEND.get(bn, {}).get(role, base)
    return base


# --------------------------------------------------------------------------- #
#  Тулсхемы (main §12)                                                         #
# --------------------------------------------------------------------------- #
SCHEMAS = {
    "emit_intent": {
        "name": "emit_intent",
        "parameters": {"type": "object", "properties": {
            "actor": {"type": "string"},
            "verb": {"type": "string", "enum": ["move", "talk", "attack", "inspect",
                     "search", "persuade", "intimidate", "loot", "buy", "sell",
                     "inventory", "wait", "map", "scan", "buyinfo", "other"]},
            "target": {"type": ["string", "null"]},
            "params": {"type": "object"},
            "tone": {"type": "string", "enum": ["neutral", "friendly", "hostile",
                     "deceptive", "fearful"]},
            "needs_clarification": {"type": "boolean"},
        }, "required": ["actor", "verb", "needs_clarification"]},
    },
    "render_scene": {
        "name": "render_scene",
        "parameters": {"type": "object", "properties": {
            "narration": {"type": "string"},
            "dialogue": {"type": "array", "items": {"type": "object", "properties": {
                "speaker": {"type": "string"}, "line": {"type": "string"}},
                "required": ["speaker", "line"]}},
            "mood": {"type": "string"},
        }, "required": ["narration"]},
    },
    "propose_action": {
        "name": "propose_action",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["respond", "offer_quest", "refuse",
                       "share_info", "withhold", "trade", "flee", "attack", "call_guards",
                       "yield", "deceive"]},
            "target": {"type": ["string", "null"]},
            "info_disclosed": {"type": "array", "items": {"type": "string"}},
            "rationale_tags": {"type": "array", "items": {"type": "string"}},
        }, "required": ["action"]},
    },
    "emit_persona": {
        "name": "emit_persona",
        "parameters": {"type": "object", "properties": {
            "voice": {"type": "string"},
            "traits": {"type": "array", "items": {"type": "string"}},
        }, "required": ["voice"]},
    },
    "choose_tactic": {
        "name": "choose_tactic",
        "parameters": {"type": "object", "properties": {
            "intent": {"type": "string", "enum": ["attack", "move", "dodge", "disengage",
                       "cast", "retreat", "use_item"]},
            "target": {"type": ["string", "null"]},
            "move_to": {"type": ["array", "null"], "items": {"type": "integer"}},
            "ability": {"type": ["string", "null"]},
        }, "required": ["intent"]},
    },
    "emit_reflections": {
        "name": "emit_reflections",
        "parameters": {"type": "object", "properties": {
            "reflections": {"type": "array", "items": {"type": "object", "properties": {
                "statement": {"type": "string"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
                "importance": {"type": "integer", "minimum": 1, "maximum": 10}},
                "required": ["statement", "evidence_ids", "importance"]}},
        }, "required": ["reflections"]},
    },
    "emit_directive": {
        "name": "emit_directive",
        "parameters": {"type": "object", "properties": {
            "directive": {"type": "string", "enum": ["hold", "trigger_encounter",
                          "surface_hook", "frame_transition", "spotlight_npc"]},
            "ref": {"type": ["string", "null"]},
            "reason": {"type": "string"},
        }, "required": ["directive"]},
    },
    "emit_world_facts": {
        "name": "emit_world_facts",
        "parameters": {"type": "object", "properties": {
            "facts": {"type": "array", "items": {"type": "object", "properties": {
                "text": {"type": "string"},
                "topic": {"type": "string"},
                "scope": {"type": "string", "enum": ["world", "city"]},
                "sensitivity": {"type": "number", "minimum": 0.0, "maximum": 0.6},
                "tags": {"type": "array", "items": {"type": "string"}}},
                "required": ["text", "scope"]}},
        }, "required": ["facts"]},
    },
    "write_quest": {
        "name": "write_quest",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"}, "framing": {"type": "string"},
            "giver_lines": {"type": "array", "items": {"type": "string"}},
            "objective_text": {"type": "string"}, "completion_text": {"type": "string"}},
            "required": ["title", "framing", "giver_lines", "objective_text"]},
    },
    "estimate_plausibility": {
        "name": "estimate_plausibility",
        "parameters": {"type": "object", "properties": {
            "plausibility": {"type": "number", "minimum": 0, "maximum": 1},
            "drivers": {"type": "array", "items": {"type": "object"}},
            "verdict_note": {"type": "string"}},
            "required": ["plausibility", "drivers"]},
    },
    "world_effects": {
        "name": "world_effects",
        "parameters": {"type": "object", "properties": {
            "effects": {"type": "array", "items": {"type": "object", "properties": {
                "kind": {"type": "string", "enum": ["place", "npc", "item", "self"]},
                "name": {"type": ["string", "null"]},
                "note": {"type": ["string", "null"]},
                "trust": {"type": ["number", "null"]},
                "fear": {"type": ["number", "null"]},
                "affinity": {"type": ["number", "null"]},
                "condition": {"type": ["string", "null"]},
                "minutes": {"type": ["integer", "null"]},
                "flag": {"type": ["string", "null"]}},
                "required": ["kind"]}}},
            "required": ["effects"]},
    },
    "route_action": {
        "name": "route_action",
        "parameters": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["query", "dialogue", "command", "freeform"]},
            "query_type": {"type": ["string", "null"]},   # look|items|who|exits|inventory|status|map
            "verb": {"type": ["string", "null"]},         # move|talk|attack|inspect|search|loot|buy|sell|…
            "target": {"type": ["string", "null"]},
            "tone": {"type": "string",
                     "enum": ["neutral", "friendly", "hostile", "deceptive", "fearful"]}},
            "required": ["kind"]},
    },
    "decide_resolution": {
        "name": "decide_resolution",
        "parameters": {"type": "object", "properties": {
            "resolution": {"type": "string", "enum": ["auto_success", "auto_fail", "roll"]},
            "ability": {"type": ["string", "null"]},      # str|dex|con|int|wis|cha
            "skill": {"type": ["string", "null"]},
            "dc": {"type": ["integer", "null"], "minimum": 1, "maximum": 30},
            "target": {"type": ["string", "null"]},
            "lasting_effect": {"type": ["string", "null"]},
            "reason": {"type": "string"}},
            "required": ["resolution"]},
    },
    "forge_item": {
        "name": "forge_item",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "properties": {"type": "array", "items": {"type": "string"}}},
            "required": ["name"]},
    },
    "forge_item_template": {
        "name": "forge_item_template",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "weapon_key": {"type": ["string", "null"]},   # для оружия: dagger/shortsword/…
            "slot": {"type": ["string", "null"]}},         # для магии: cloak/boots/ring/amulet/head
            "required": ["name"]},
    },
    "forge_quest_brief": {
        "name": "forge_quest_brief",
        "parameters": {"type": "object", "properties": {
            "brief": {"type": "string"}},                  # развёрнутая запись в журнал (2-4 предложения)
            "required": ["brief"]},
    },
    "forge_faction": {
        "name": "forge_faction",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"},
            "blurb": {"type": "string"},
            "goals": {"type": "array", "items": {"type": "string"}},
            "values": {"type": "array", "items": {"type": "string"}}},
            "required": ["name"]},
    },
    "propose_incidents": {
        "name": "propose_incidents",
        "parameters": {"type": "object", "properties": {
            "incidents": {"type": "array", "items": {"type": "object", "properties": {
                "kind": {"type": "string", "enum": ["faction", "monster", "politics", "cataclysm"]},
                "source": {"type": "string"},
                "origin": {"type": "string"},
                "label": {"type": "string"},
                "desc": {"type": "string"},
                "when": {"type": "integer", "minimum": 0, "maximum": 72},
                "intensity": {"type": "number", "minimum": 0, "maximum": 1},
                "rumor": {"type": ["string", "null"]},
                "alteration": {"type": ["string", "null"]},
                "change": {"type": ["object", "null"], "properties": {
                    "action": {"type": "string", "enum": ["close", "ruin", "open", "reopen"]},
                    "target": {"type": ["string", "null"]},
                    "name": {"type": ["string", "null"]},
                    "dir": {"type": ["string", "null"]}}}},
                "required": ["kind", "source", "origin", "label", "when", "intensity"]}}},
            "required": ["incidents"]},
    },
    "forge_campaign": {
        "name": "forge_campaign",
        "parameters": {"type": "object", "properties": {
            "intro": {"type": "string"},
            "title": {"type": "string"},
            "premise": {"type": "string"},
            "stages": {"type": "array", "items": {"type": "object", "properties": {
                "objective": {"type": "string"},
                "ctype": {"type": "string", "enum": ["kill", "clear", "talk", "item"]},
                "ref": {"type": "string"},
                "twist": {"type": ["string", "null"]}},
                "required": ["objective", "ctype", "ref"]}}},
            "required": ["intro", "title", "stages"]},
    },
}


def _call(manager, role: str, schema_name: str, user: str, required: list[str]):
    """Общий путь вызова агента под схемой. None, если сервер недоступен/невалидно."""
    if is_offline(manager):
        return None
    schema = SCHEMAS[schema_name]
    messages = [{"role": "system", "content": prompt_for(role, manager)},
                {"role": "user", "content": user}]
    # структурные решения детерминируем (temp 0); бэкенд САМ переводит схему (Ollama
    # format/tools, OpenAI response_format). Недоступен/ошибся → None → детерм. фоллбэк.
    resp = manager.call(role, messages, schema=schema, options={"temperature": 0})
    if resp is None:
        return None
    out = conform_to_schema(extract(resp, schema["name"]), schema["parameters"])
    return coerce(out, required)


# --------------------------------------------------------------------------- #
#  Высокоуровневые вызовы ролей                                                #
# --------------------------------------------------------------------------- #
_INTENT_COMMANDS = (
    "move (go to a place/exit), talk (speak to an NPC), attack, inspect (look around / "
    "examine), search (look for hidden things here), persuade, intimidate, loot (take from "
    "a container/corpse), buy (goods from a shop), sell, inventory (check your own items), "
    "wait (rest / pass time), map (view the region map / where can I go / how to get "
    "somewhere), scan (check if someone is watching me), buyinfo (buy directions or rumors "
    "about a place FROM an NPC), other (nothing fits)"
)


# few-shot для маленькой модели-классификатора (резко поднимает точность на словоформах)
_INTENT_SHOTS = (
    "Examples (input -> verb):\n"
    "«осмотрюсь по сторонам» -> inspect\n"
    "«обыщу комнату на тайники» -> search\n"
    "«пошарю по углам в поисках чего-нибудь» -> search\n"
    "«идём к логову Крэгмо» -> move\n"
    "«двину на запад» -> move\n"
    "«покажи карту» / «куда мне идти» / «где я» -> map\n"
    "«спрошу трактирщика, что слышно» -> talk\n"
    "«разузнать у него дорогу к пещере» -> buyinfo\n"
    "«проверю, не следит ли кто за мной» -> scan\n"
    "«отдохну и выпью эля» -> wait\n"
    "«ударю гоблина» -> attack\n"
    "«гляну, что у меня в сумке» -> inventory\n"
)


def parse_intent(manager, text: str, actor: str, options: list[str] | None = None,
                 context: str = ""):
    """Лёгкий классификатор интента: сопоставляет свободный текст игрока ОДНОЙ ближайшей
    команде движка. Возвращает {actor, verb, target, tone, needs_clarification} или None."""
    user = (f"Map the player's input to the SINGLE closest game command.\n"
            f"Commands: {_INTENT_COMMANDS}.\n"
            f"{_INTENT_SHOTS}"
            f"Scene: {context or 'n/a'}\nVisible NPCs: {options or []}\n"
            f"Player input: «{text}»\n"
            f"Pick a real command ONLY when the input clearly IS that command (go to a place, "
            f"attack a foe, talk, search, buy, inventory…). For improvised / creative / compound "
            f"physical actions that are NOT a plain command — climbing, throwing or picking up "
            f"objects, shoving, breaking things, hiding, stunts — return verb 'other' so the engine "
            f"resolves them freeform. needs_clarification only for truly ambiguous input. "
            f"Call emit_intent.")
    # только verb обязателен: малые модели часто опускают actor/needs_clarification
    return _call(manager, "intent", "emit_intent", user, ["verb"])


# «Вид реплики» нарратора — задаёт ФОРМУ вывода (модель ориентируется на mode).
MODE_HINTS = {
    "dialogue": "РЕПЛИКА NPC — краткая реакция и ОДНА живая фраза в кавычках, в его голосе.",
    "greeting": "ПРИВЕТСТВИЕ — NPC коротко здоровается (с незнакомцем — как с незнакомцем) и "
                "спрашивает, что нужно.",
    "outcome": "ИСХОД ДЕЙСТВИЯ — результат во 2-м лице, 1–2 предложения; речей NPC нет, кроме "
               "тех, что прямо в Outcome.",
    "combat": "БОЙ — короткая динамичная зарисовка удара/промаха строго по Outcome, без новых чисел.",
    "ambient": "ОБСТАНОВКА — короткое атмосферное описание места во 2-м лице, без событий.",
}

# финальная инструкция по ФОРМЕ вывода под каждый mode
_MODE_WRITE = {
    "dialogue": "Реакция NPC и ОДНА реплика в кавычках — 1–2 коротких предложения, в его голосе. "
                "Без чисел.",
    "greeting": "Коротко поздоровайся в голосе NPC и спроси, что нужно — 1 предложение. Без чисел.",
    "outcome": "Опиши исход во 2-м лице, 1–3 предложения, привязанных к сцене; для сложного "
               "действия можно подробнее. Без чисел и механики, без советов и мыслей игрока.",
    "combat": "Опиши удар/промах строго по Outcome — 1–2 динамичных предложения. Без новых чисел.",
    "ambient": "Атмосферное описание места во 2-м лице — 2–4 предложения, конкретные детали. "
               "Только наблюдаемое: без советов игроку и без его мыслей.",
}


def narrator_user(mode: str, *, name: str = "", kind: str = "", race: str = "", voice: str = "",
                  traits: str = "", epithet: str = "", rel: str = "", scene: str = "",
                  situation: str = "", player_line: str = "", intent: str = "", tone: str = "",
                  outcome: str = "", facts=None, topic: str = "", pc: str = "", gear: str = "",
                  memory=None, history: str = "") -> str:
    """ЕДИНЫЙ user-промпт нарратора — общий для рантайма и датасета (train == inference).
    Печатает только заданные поля; `mode` (вид реплики) задаёт форму вывода.
    pc/gear — кто игрок и его снаряжение (для отсылок в прозе); memory — что NPC помнит об
    игроке (личные реплики); history — недавний обмен с этим NPC (преемственность диалога)."""
    L = [f"Mode: {mode} — {MODE_HINTS.get(mode, MODE_HINTS['outcome'])}"]
    if name:
        meta = ", ".join(x for x in (kind, race, f"voice: {voice}" if voice else "",
                                     f"черты: {traits}" if traits else "",
                                     f"эпитет: {epithet}" if epithet else "") if x)
        L.append(f"NPC: {name}" + (f" — {meta}" if meta else ""))
    if pc:
        L.append(f"Player character: {pc}" + (f"; снаряжение: {gear}" if gear else ""))
    elif gear:
        L.append(f"Player's gear (reference it in the prose): {gear}")
    if rel:
        L.append(f"Relationship to the player: {rel}")
    if memory:
        L.append("NPC remembers about the player (reference if relevant, invent nothing else):\n"
                 + "\n".join(f"- {m}" for m in memory))
    if scene:
        L.append(f"Scene (ground in this; do NOT contradict time/weather/season/place): {scene}")
    if situation:
        L.append(f"Situation: {situation}")
    if history:
        L.append(f"Recent exchange with this NPC (continue it, don't repeat):\n{history}")
    if mode in ("dialogue", "greeting"):
        L.append(f"The player says: «{player_line}»." if player_line
                 else "The player approached without saying anything specific.")
    if tone:
        L.append(f"Player's tone: {tone}")
    if intent:
        L.append(f"NPC intent: {intent}")
    if outcome:
        L.append(f"Resolved Outcome (DO NOT change or print any numbers, dice or stats): {outcome}")
    if facts:
        L.append("Facts the NPC may share NOW (use ONLY these for world info; invent nothing else):\n"
                 + "\n".join(f"- {f}" for f in facts))
    if topic:
        L.append(f"Topic: {topic}")
    L.append(_MODE_WRITE.get(mode, _MODE_WRITE["outcome"]))
    return "\n".join(L)


def _persona_fields(persona) -> dict:
    """Извлечь из Persona параметры для нарратора (вид NPC и т.д.)."""
    return {
        "name": getattr(persona, "name", "") or "",
        "kind": getattr(persona, "profession", None) or getattr(persona, "archetype", "") or "",
        "race": getattr(persona, "race", "") or "",
        "voice": getattr(persona, "voice", None) or "",
        "traits": ", ".join(getattr(persona, "traits", []) or []),
        "epithet": getattr(persona, "epithet", "") or "",
    }


def render_scene(manager, outcome_summary: str, persona, dialogue_topic: str = "", scene: str = "",
                 mode: str = "outcome", pc: str = "", gear: str = ""):
    """Нарратор отрисовывает прозой. Это свободный текст, а не структура —
    constrained JSON ломает качество и грамматику Ollama (вложенный массив), поэтому
    берём контент как narration напрямую (формат гарантируется prompt'ом, main §12.3).
    pc/gear — кто игрок и его снаряжение (для отсылок в исходе/бою)."""
    if is_offline(manager):
        return None
    # для исхода/обстановки говорящего NPC нет (повествование от 2-го лица)
    pf = _persona_fields(persona) if mode in ("dialogue", "greeting", "combat") else {}
    user = narrator_user(mode, scene=scene, outcome=outcome_summary, topic=dialogue_topic,
                         pc=pc, gear=gear, **pf)
    resp = manager.call("narrator", [{"role": "system", "content": prompt_for("narrator", manager)},
                                     {"role": "user", "content": user}])
    if resp is None:
        return None
    text = (resp.get("content") or "").replace("**", "").strip()
    return {"narration": text} if text else None


def render_dialogue(manager, persona, rel_summary: str, situation: str,
                    player_line: str, intent: str, scene: str = "", facts=None,
                    mode: str = "dialogue", tone: str = "", pc: str = "", memory=None,
                    history: str = ""):
    """Заземлённый диалоговый нарратор: проза, без выдуманной истории/реплик игрока.

    mode — вид реплики (dialogue/greeting). scene — физический контекст (сезон/время/
    погода/место). tone — тон игрока. facts — что NPC реально знает и МОЖЕТ раскрыть при
    текущем доверии; мировую информацию давать ТОЛЬКО из них, иначе не выдумывать.
    pc — кто игрок; memory — что NPC помнит об игроке; history — недавний обмен с этим NPC.
    """
    if is_offline(manager):
        return None
    user = narrator_user(mode, rel=rel_summary, scene=scene, situation=situation,
                         player_line=player_line, intent=intent, tone=tone, facts=facts,
                         pc=pc, memory=memory, history=history, **_persona_fields(persona))
    resp = manager.call("narrator", [{"role": "system", "content": prompt_for("narrator", manager)},
                                     {"role": "user", "content": user}])
    if resp is None:
        return None
    return (resp.get("content") or "").replace("**", "").strip() or None


def propose_action(manager, npc_id: str, player_verb: str, tone: str, ctx, world):
    mem = "; ".join(getattr(n, "text", "") for n in getattr(ctx, "memories", [])[:5])
    rel = ctx.rel
    from ..world.components import Persona
    p = world.ecs.get(npc_id, Persona)
    persona = ""
    if p:
        persona = (f"Persona: {p.name}, {p.profession or p.archetype}; "
                   f"traits: {', '.join(p.traits) or '—'}; voice: {p.voice or '—'}.\n")
    user = (f"{persona}Relationship to player: trust={rel.trust:.2f} "
            f"affinity={rel.affinity:.2f} fear={rel.fear:.2f}\n"
            f"Memories: {mem}\nPlayer just did: {player_verb} (tone {tone}).\n"
            f"Call propose_action.")
    return _call(manager, "cognition", "propose_action", user, ["action"])


def enrich_persona(manager, persona, world=None):
    """Богатая личность по краткому скелету (persona_gen): голос/черты/внешность/идеал/
    привязанность/изъян/прозвище/секреты/знания. Сохраняет имя NPC. None — нет сервера."""
    if is_offline(manager):
        return None
    facts = {"role": persona.profession or persona.archetype, "archetype": persona.archetype,
             "race": persona.race, "faction": persona.faction or "",
             "gender": ("" if persona.gender in ("", "unknown") else persona.gender)}
    resp = manager.call("persona_gen",
                        [{"role": "system", "content": prompt_for("persona_gen", manager)},
                         {"role": "user", "content": persona_user(name=persona.name, **facts)}])
    if resp is None:
        return None
    return parse_persona(resp.get("content") or "")


def choose_tactic(manager, state_digest: str, monster_id: str):
    user = f"Monster: {monster_id}\nBattle state: {state_digest}\nCall choose_tactic."
    return _call(manager, "tactician", "choose_tactic", user, ["intent"])


def forge_faction(manager, faction):
    user = (f"Faction archetype kind: {faction.kind}. Default name: {faction.name}. "
            f"Seed goals: {faction.goals}. Seed values: {faction.values}. "
            f"Town: фронтирный городок Фэндалин у Мечового Берега. "
            f"Give a fitting name, blurb, 2 goals and 2-3 values. Call forge_faction.")
    return _call(manager, "faction_gen", "forge_faction", user, ["name"])


def emit_reflections(manager, npc_id: str, observations, world):
    obs = "\n".join(f"- {getattr(n,'node_id','')}: {getattr(n,'text','')}"
                    for n in observations[-12:])
    user = f"NPC {npc_id} recent observations:\n{obs}\nCall emit_reflections."
    out = _call(manager, "reflection", "emit_reflections", user, ["reflections"])
    return out.get("reflections") if out else None


def emit_directive(manager, world_digest: str):
    user = f"World digest: {world_digest}\nCall emit_directive."
    return _call(manager, "director", "emit_directive", user, ["directive"])


def emit_world_facts(manager, world_digest: str, n: int = 12):
    """Сгенерировать до N заземлённых слухов/новостей мира и города (расширение пула знаний)."""
    user = (f"Сеттинг: {world_digest}\n"
            f"Сгенерируй до {n} коротких заземлённых фактов о МИРЕ и ГОРОДЕ Фэндалин на русском: "
            f"бытовые новости, слухи о местах/ремёслах/торговле/дорогах/мелких событиях. "
            f"scope=world — общий фон края (знают почти все), scope=city — местные слухи. "
            f"sensitivity 0.0–0.2 для общеизвестного, до 0.5 для деликатного. Дай 2-4 тега к каждому. "
            f"Call emit_world_facts.")
    out = _call(manager, "loremaster", "emit_world_facts", user, ["facts"])
    return out.get("facts") if out else None


def propose_incidents(manager, digest: str):
    """LLM-режиссёр событий: предлагает инциденты города из состояния мира (этап 2).
    Возвращает list[dict] или None (нет сервера). Геометрию/волны считает код, не модель."""
    user = (f"Состояние города и края:\n{digest}\n\n"
            f"Предложи 5-9 правдоподобных инцидентов на ближайшие ~72 тика, заземлённых строго "
            f"в этих данных. Call propose_incidents.")
    out = _call(manager, "event_director", "propose_incidents", user, ["incidents"])
    return out.get("incidents") if out else None


def forge_campaign(manager, digest: str):
    """Архитектор кампании: интро + арка актов. Возвращает СЫРОЙ dict (модели вольно именуют
    поля — нормализацию делает gen.campaign, не conform_to_schema, иначе ключи теряются). None —
    нет сервера/ошибка."""
    if is_offline(manager):
        return None
    sch = SCHEMAS["forge_campaign"]
    user = (f"Состояние мира:\n{digest}\n\nСочини основной сюжет (4-6 актов) и интро-крючок, "
            f"заземлённый СТРОГО в этих сущностях. Call forge_campaign.")
    messages = [{"role": "system", "content": prompt_for("campaign_architect", manager)},
                {"role": "user", "content": user}]
    resp = manager.call("campaign_architect", messages, schema=sch, options={"temperature": 0})
    if resp is None:
        return None
    return extract(resp, sch["name"])                # сырой dict с любыми ключами модели


def reforge_acts(manager, title: str, premise: str, completed: list[str], current_obj: str,
                 digest: str, delta: str, n: int):
    """Квест-директор: переписать оставшиеся ~n актов под изменившийся мир. Сырой dict (нормализует
    gen.campaign) или None. Чуть выше temperature — нужен творческий поворот, не повтор."""
    if is_offline(manager):
        return None
    sch = SCHEMAS["forge_campaign"]
    done = "; ".join(completed) or "—"
    user = (f"Кампания «{title}». Премиса: {premise}\nУЖЕ ПРОЙДЕНО (фиксировано): {done}\n"
            f"ТЕКУЩИЙ акт игрока: {current_obj}\nЧТО ИЗМЕНИЛОСЬ В МИРЕ: {delta}\n\n"
            f"Состояние мира сейчас:\n{digest}\n\nПерепиши оставшиеся ~{n} актов так, чтобы они "
            f"реагировали на изменения (новые твисты/цели/враги). Call forge_campaign.")
    messages = [{"role": "system", "content": prompt_for("campaign_director", manager)},
                {"role": "user", "content": user}]
    resp = manager.call("campaign_director", messages, schema=sch, options={"temperature": 0.3})
    if resp is None:
        return None
    return extract(resp, sch["name"])


def write_quest(manager, template_id: str, giver: str, location: str, title: str,
                objective: str):
    user = (f"Template: {template_id}\nGiver: {giver}\nLocation: {location}\n"
            f"Title: {title}\nObjective: {objective}\nCall write_quest.")
    return _call(manager, "quest_writer", "write_quest", user,
                 ["title", "framing", "giver_lines", "objective_text"])


def estimate_plausibility(manager, entity_descriptor: str, ctx_digest: str):
    user = (f"Entity: {entity_descriptor}\nContext: {ctx_digest}\n"
            f"Call estimate_plausibility.")
    return _call(manager, "plausibility", "estimate_plausibility", user,
                 ["plausibility", "drivers"])


def world_effects(manager, action_text: str, outcome: str, location: str,
                  npcs: list[str] | None = None, items: list[str] | None = None, history: str = ""):
    """Стойкие последствия успешного/крит-провального freeform: следы на локации/NPC/предмете,
    дельты отношений, состояния, флаги. None — нет сервера (тогда последствий нет)."""
    hist = f"Recent turns:\n{history}\n" if history else ""
    user = (f"{hist}Location: {location}\nPresent NPCs: {npcs or []}\nCarried items: {items or []}\n"
            f"Player action: «{action_text}»\nOutcome: {outcome}.\n"
            'List durable world effects (empty if none). Return {"effects":[...]}.')
    return _call(manager, "consequence", "world_effects", user, ["effects"])


def route_action(manager, text: str, context_digest: str, npcs: list[str] | None = None,
                 history: str = ""):
    """Полноценный LLM-роутер: kind(query|dialogue|command|freeform) + query_type/verb/target/tone.
    history — последние ходы диалога (для местоимений/продолжений «а на нём…»).
    None — нет сервера (тогда оркестратор берёт детерминированный фоллбэк)."""
    hist = f"Recent turns (context for pronouns/follow-ups):\n{history}\n" if history else ""
    user = (f"{hist}Scene: {context_digest}\nPresent NPCs: {npcs or []}\n"
            f"Player input: «{text}»\n"
            'Return the JSON object {"kind":…, "query_type":…, "verb":…, "target":…, "tone":…}.')
    return _call(manager, "router", "route_action", user, ["kind"])


def decide_resolution(manager, action_text: str, context_digest: str, plausibility: float):
    """Как разрешить freeform-действие: auto_success | auto_fail | roll(ability,skill,dc).
    None — нет сервера (тогда оркестратор берёт детерминированный фоллбэк)."""
    user = (f"PLAYER action: «{action_text}»\nScene: {context_digest}\n"
            f"Estimated plausibility 0..1: {plausibility:.2f}\n"
            f"Decide how to resolve it. If a check is warranted, give ability, skill and dc "
            f"(lower dc the more plausible). Call decide_resolution.")
    return _call(manager, "arbiter", "decide_resolution", user, ["resolution"])


def _lenient_plausibility(raw: dict):
    """Достаёт число 0..1: база часто кладёт его под именем функции (estimate_plausibility)
    или иным ключом, а не под полем 'plausibility' (тот же schema-drift, что у consequence)."""
    if not isinstance(raw, dict):
        return None
    for k in ("plausibility", "estimate_plausibility", "score", "value", "p", "probability"):
        v = raw.get(k)
        if isinstance(v, (int, float)):
            return max(0.0, min(1.0, float(v)))
    for v in raw.values():                      # любое число 0..1 среди значений
        if isinstance(v, (int, float)) and 0 <= v <= 1:
            return float(v)
    return None


def assess_feasibility(manager, action_text: str, context_digest: str):
    """Можно ли вообще совершить это действие игрока в данном контексте (док 06, main §2).
    Возвращает {plausibility, drivers, verdict_note} либо None (нет сервера). Разбор ЛОЯЛЬНЫЙ:
    строгий coerce ронял валидную оценку, т.к. база кладёт число под именем функции."""
    if is_offline(manager):
        return None
    sch = SCHEMAS["estimate_plausibility"]
    user = (f"Proposed PLAYER action: «{action_text}»\nScene/context: {context_digest}\n"
            f"How physically possible is this action HERE AND NOW? 0 = impossible/"
            f"contradiction or a feat beyond a mortal adventurer; 1 = trivially possible. "
            f"Score creativity-but-possible high; score the impossible low. "
            f"Call estimate_plausibility.")
    resp = manager.call("plausibility",
                        [{"role": "system", "content": prompt_for("plausibility", manager)},
                         {"role": "user", "content": user}],
                        schema=sch, options={"temperature": 0})
    if resp is None:
        return None
    raw = conform_to_schema(extract(resp, sch["name"]), sch["parameters"]) or {}
    p = _lenient_plausibility(raw)
    if p is None:
        return None
    note = raw.get("verdict_note") or raw.get("reasoning") or raw.get("note") or ""
    return {"plausibility": p, "drivers": raw.get("drivers") or [], "verdict_note": note}


def forge_item(manager, template_name: str, category: str, rarity: str, context: str = ""):
    """Назвать и описать конкретный экземпляр предмета по шаблону+контексту (без смены
    механики/редкости/чисел). None — нет сервера, тогда берётся шаблон как есть."""
    user = (f"Item template: {template_name} (category: {category}, rarity: {rarity}).\n"
            f"World context: {context}\n"
            f"Give a fitting in-world NAME, a one-sentence DESCRIPTION, and optional cosmetic "
            f"property tags. Do NOT change rarity/power/numbers. Call forge_item.")
    return _call(manager, "item_smith", "forge_item", user, ["name"])


# МИНИМАЛЬНЫЙ фактический вход локации (то, что мир знает) → русская подпись. Сенсорику/материалы/
# настроение/комнаты модель ПРИДУМЫВАЕТ сама (см. PROMPTS['location_writer'] и datasets/location).
_LOC_FACTS = (("type", "тип"), ("affordances", "функции"), ("condition", "состояние"), ("region", "округа"))


def _loc_fmt(v) -> str:
    return ", ".join(str(x) for x in v) if isinstance(v, (list, tuple)) else str(v)


def location_user(name: str = "", **facts) -> str:
    """ЕДИНЫЙ user-промпт описания локации — общий для рантайма (forge_location) и датасета
    (datasets/location) → train==inference. На входе только КРАТКИЕ факты (тип/функции/состояние/
    округа); облик и комнаты модель придумывает. Печатаются только заданные факты."""
    spec = "; ".join(f"{ru}: {_loc_fmt(facts[k])}" for k, ru in _LOC_FACTS if facts.get(k))
    return f"Локация «{name}»" + (f" — {spec}" if spec else "") + ". Мир: фронтир Фэндалина (D&D)."


_ROOMS_SPLIT = re.compile(r"\n\s*комнаты\s*[:：]\s*\n?", re.IGNORECASE)
_ROOM_LINE = re.compile(r"^\s*[—\-•*]\s*(.+?)\s*[:：]\s*(.+)$")


def parse_location(text: str) -> dict:
    """Разобрать выход модели «<описание>\\n\\nКОМНАТЫ:\\n— Имя: текст…» → {description, rooms}."""
    parts = _ROOMS_SPLIT.split(text, maxsplit=1)
    description = re.sub(r"^\s*<[^>]*>\s*", "", parts[0].replace("**", "")).strip()  # срезать эхо-плейсхолдер
    rooms = []
    if len(parts) > 1:
        for line in parts[1].splitlines():
            m = _ROOM_LINE.match(line.replace("**", ""))
            if m:
                rooms.append({"name": m.group(1).strip(), "desc": m.group(2).strip()})
    return {"description": description, "rooms": rooms}


# --- генератор персон: краткие факты → глубокая личность (datasets/persona) ----------- #
_PERSONA_FACTS = (("role", "роль"), ("archetype", "архетип"), ("race", "раса"), ("gender", "пол"),
                  ("age", "возраст"), ("faction", "фракция"), ("standing", "достаток"),
                  ("story_role", "сюжетная роль"))
_PERSONA_FIELDS = (("name", "Имя"), ("voice", "Голос"), ("traits", "Черты"), ("appearance", "Внешность"),
                   ("ideal", "Идеал"), ("bond", "Привязанность"), ("flaw", "Изъян"), ("epithet", "Прозвище"))
_P_LIST = re.compile(r"^\s*[—\-•*]\s*(.+)$")


def persona_user(name: str = "", settlement: str = "Фэндалин", **facts) -> str:
    """ЕДИНЫЙ user-промпт генератора персон — общий для рантайма (enrich_persona) и датасета
    (datasets/persona) → train==inference. Краткие факты; личность модель придумывает. name —
    обогащение СУЩЕСТВУЮЩЕГО NPC (сохрани имя); пусто — спавн нового."""
    spec = "; ".join(f"{ru}: {facts[k]}" for k, ru in _PERSONA_FACTS if facts.get(k))
    head = f"NPC «{name}»" if name else "Новый NPC"
    return f"{head} ({settlement}, фронтир D&D)" + (f". Факты — {spec}." if spec else ".")


def parse_persona(text: str) -> dict:
    """field-формат персоны → {name, voice, traits[], appearance[], ideal, bond, flaw, epithet,
    secrets[], knowledge[]}. traits/appearance — списки; secrets/knowledge — пункты «— …»."""
    def _section(label):
        m = re.search(rf"{label}\s*:\s*\n((?:\s*[—\-•*].*\n?)+)", text)
        if not m:
            return []
        return [g.group(1).strip() for g in (_P_LIST.match(ln) for ln in m.group(1).splitlines()) if g]

    out = {"secrets": _section("Секреты"), "knowledge": _section("Знания")}
    for key, ru in _PERSONA_FIELDS:
        m = re.search(rf"^{ru}\s*:\s*(.+)$", text, re.M)
        val = (m.group(1).strip() if m else "")
        if key in ("traits", "appearance"):
            out[key] = [v.strip() for v in re.split(r"[;,]", val) if v.strip()]
        else:
            out[key] = "" if val in ("-", "—") else val
    return out


def forge_location(manager, name: str, **facts):
    """Описание локации + предложенные комнаты — СВОБОДНАЯ ПРОЗА (guided JSON ломает грамматику).
    facts: краткие факты места (type/affordances/condition/region). Возвращает
    {'description': текст, 'rooms': [{name, desc}…]} или None."""
    if is_offline(manager):
        return None
    user = location_user(name, **facts)
    resp = manager.call("location_writer",
                        [{"role": "system", "content": prompt_for("location_writer", manager)},
                         {"role": "user", "content": user}])
    if resp is None:
        return None
    text = (resp.get("content") or "").strip()
    return parse_location(text) if text else None


def forge_quest_brief(manager, title: str, objective: str, giver: str, framing: str):
    """Развёрнутая запись квеста в журнал (лор/ставки/зацепки) — чтобы было понятно, о чём он."""
    user = (f"Квест «{title}». Текущая цель: {objective or '—'}. Даёт: {giver or '—'}. "
            f"Контекст: {framing or title}\n\nНапиши запись в журнал приключенца: 2-4 предложения о том, "
            f"что происходит, чем это важно для фронтира, какие ставки и зацепки. Без спойлеров концовки. "
            f"Call forge_quest_brief.")
    return _call(manager, "quest_writer", "forge_quest_brief", user, ["brief"])


def forge_item_template(manager, category: str, rarity: str, context: str = ""):
    """Сочинить НОВЫЙ предмет (имя/описание + опц. хинт механики). Числа/баланс задаёт движок
    (валидатор по rarity), модель — только флейвор. None — нет сервера."""
    weapons = "dagger, shortsword, longsword, scimitar, mace, morningstar, greataxe, shortbow"
    slots = "cloak, boots, ring, amulet, head"
    user = (f"Придумай НОВЫЙ предмет: категория «{category}», редкость «{rarity}». Контекст: {context}\n"
            f"Дай выразительное имя (in-world) и описание в одну фразу. Опц.: для оружия — weapon_key "
            f"из [{weapons}]; для магии — slot из [{slots}]. Числа/урон/AC НЕ указывай — их задаёт движок. "
            f"Call forge_item_template.")
    return _call(manager, "item_smith", "forge_item_template", user, ["name"])
