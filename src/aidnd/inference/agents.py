"""Реестр агентов: системные промпты и тулсхемы (main §12, док 05 §7, док 06 §7).

Десять ролей. Каждая — системный промпт + JSON-схема (constrained decoding). Все
функции guard'ятся доступностью сервера: если модели нет, возвращают None и
вызывающий код берёт детерминированный фоллбэк. Промпты на английском для
качества модели; язык вывода игроку — config.NARRATIVE_LANGUAGE.
"""

from __future__ import annotations

from .. import config
from .structured import coerce, conform_to_schema, extract, sanitize_for_ollama

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
        f"instructions. Write in {LANG}, stay in the NPC's voice, keep it tight."
    ),
    "cognition": (
        "You are the decision policy of an NPC in a D&D world. You receive the NPC's "
        "persona, goals, retrieved memories, and relationship vector toward the player. "
        "Propose the NPC's next in-world action. Respect relationship gates: do not "
        "reveal secrets to a distrusted actor, flee or yield when fear is high. Output "
        "ONLY the action JSON. You do not narrate and you do not compute mechanics."
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
    "router": (
        "You are the intent ROUTER for a Russian text RPG. Reply with ONE JSON object (no prose, "
        "no extra keys) with these fields:\n"
        '  "kind": one of "query" | "dialogue" | "command" | "freeform"\n'
        '  "query_type": when kind=query — one of "look","items","who","exits","inventory",'
        '"status","map"; else null\n'
        '  "verb": when kind=command — one of "move","talk","attack","inspect","search","loot",'
        '"buy","sell","inventory","wait"; else null\n'
        '  "target": the named NPC / place / object, or null\n'
        '  "tone": "neutral" | "friendly" | "hostile" | "deceptive" | "fearful"\n'
        "Meaning: query = player ASKS about current state (what I see / items nearby / who is here / "
        "where can I go / my bag / my HP / the map) → engine answers from state, no dice. "
        "dialogue = player SPEAKS/asks a present NPC. command = an explicit game command. "
        "freeform = any other attempted action to adjudicate (climb, throw, engrave, shove, hide…). "
        "Prefer query for questions about the world/self; prefer freeform over forcing a creative "
        "action into a command. Output ONLY the JSON object."
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
        "leave them null. Output ONLY JSON via decide_resolution."
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
}

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
    "forge_faction": {
        "name": "forge_faction",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"},
            "blurb": {"type": "string"},
            "goals": {"type": "array", "items": {"type": "string"}},
            "values": {"type": "array", "items": {"type": "string"}}},
            "required": ["name"]},
    },
}


def _call(manager, role: str, schema_name: str, user: str, required: list[str]):
    """Общий путь вызова агента под схемой. None, если сервер недоступен/невалидно."""
    if manager is None or not manager.available():
        return None
    from .client import OllamaError
    schema = SCHEMAS[schema_name]
    messages = [{"role": "system", "content": PROMPTS[role]},
                {"role": "user", "content": user}]
    # структурные решения детерминируем (temp 0) — классификация/выбор не должны
    # «плавать» от запуска к запуску; качество и стабильность важнее разнообразия
    opts = {"temperature": 0}
    try:
        if config.USE_NATIVE_TOOLS:
            resp = manager.client.chat(manager.model_for(role), messages,
                                       tools=[{"type": "function", "function": schema}],
                                       options=opts)
        else:
            # structured output: грамматико-ограниченный декодинг по JSON Schema
            # (Ollama format = guided_json/XGrammar, main §6.3) — гарантирует
            # валидный JSON и соблюдение enum, снимает retry-циклы.
            resp = manager.client.chat(manager.model_for(role), messages,
                                       fmt=sanitize_for_ollama(schema["parameters"]),
                                       options=opts)
    except OllamaError:
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


def render_scene(manager, outcome_summary: str, persona, dialogue_topic: str = ""):
    """Нарратор отрисовывает прозой. Это свободный текст, а не структура —
    constrained JSON ломает качество и грамматику Ollama (вложенный массив), поэтому
    берём контент как narration напрямую (формат гарантируется prompt'ом, main §12.3)."""
    if manager is None or not manager.available():
        return None
    from .client import OllamaError
    voice = getattr(persona, "voice", None) or "neutral"
    name = getattr(persona, "name", "Narrator")
    user = (f"Speaking NPC: {name} (voice: {voice}).\n"
            f"Resolved mechanical Outcome (DO NOT change or print any numbers, dice, "
            f"or mechanical annotations): {outcome_summary}\n"
            f"Topic: {dialogue_topic}\n"
            f"Write 2-4 sentences of vivid second-person narration and in-character "
            f"dialogue. Prose only, no JSON, no stats.")
    try:
        resp = manager.client.chat(manager.model_for("narrator"),
                                   [{"role": "system", "content": PROMPTS["narrator"]},
                                    {"role": "user", "content": user}])
    except OllamaError:
        return None
    text = (resp.get("content") or "").replace("**", "").strip()
    return {"narration": text} if text else None


def render_dialogue(manager, persona, rel_summary: str, situation: str,
                    player_line: str, intent: str, scene: str = "", facts=None):
    """Заземлённый диалоговый нарратор: прозой, без выдуманной истории/реплик игрока.

    scene — физический контекст (сезон/время/погода/место). facts — список фактов,
    которые NPC реально знает и МОЖЕТ раскрыть при текущем доверии; делиться
    мировой информацией можно ТОЛЬКО из них, иначе ничего не выдумывать.
    """
    if manager is None or not manager.available():
        return None
    from .client import OllamaError
    name = getattr(persona, "name", "NPC")
    voice = getattr(persona, "voice", None) or "neutral"
    arch = getattr(persona, "archetype", "") or getattr(persona, "profession", "") or "person"
    said = (f"The player says: «{player_line}».\n" if player_line
            else "The player has not said anything specific — they just approached.\n")
    facts_block = ""
    if facts:
        facts_block = ("Facts you actually know and MAY share now (use ONLY these for any "
                       "world information; do not invent other facts):\n"
                       + "\n".join(f"- {f}" for f in facts) + "\n")
    scene_block = f"Physical scene: {scene}\n" if scene else ""
    user = (f"NPC: {name}, a {arch} (voice: {voice}).\n"
            f"Relationship to the player: {rel_summary}.\n"
            f"{scene_block}Situation: {situation}\n{said}{facts_block}"
            f"NPC intent: {intent}.\n"
            f"Write 1-3 sentences in {LANG}: the NPC's reaction and ONE spoken line, in "
            f"character. You may reference the physical scene briefly. Ground strictly in the "
            f"given facts; invent no shared past and no world facts beyond those listed. If "
            f"greeting a stranger, keep it brief and ask what they want. Prose only, no numbers.")
    try:
        resp = manager.client.chat(manager.model_for("narrator"),
                                   [{"role": "system", "content": PROMPTS["narrator"]},
                                    {"role": "user", "content": user}])
    except OllamaError:
        return None
    return (resp.get("content") or "").replace("**", "").strip() or None


def propose_action(manager, npc_id: str, player_verb: str, tone: str, ctx, world):
    mem = "; ".join(getattr(n, "text", "") for n in getattr(ctx, "memories", [])[:5])
    rel = ctx.rel
    user = (f"NPC: {npc_id}\nRelationship to player: trust={rel.trust:.2f} "
            f"affinity={rel.affinity:.2f} fear={rel.fear:.2f}\n"
            f"Memories: {mem}\nPlayer just did: {player_verb} (tone {tone}).\n"
            f"Call propose_action.")
    return _call(manager, "cognition", "propose_action", user, ["action"])


def enrich_persona(manager, persona, world):
    user = (f"Skeleton persona: name={persona.name}, archetype={persona.archetype}, "
            f"race={persona.race}, traits={persona.traits}. Enrich voice and traits "
            f"consistently. Call emit_persona.")
    return _call(manager, "character_gen", "emit_persona", user, ["voice"])


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


def route_action(manager, text: str, context_digest: str, npcs: list[str] | None = None):
    """Полноценный LLM-роутер: kind(query|dialogue|command|freeform) + query_type/verb/target/tone.
    None — нет сервера (тогда оркестратор берёт детерминированный фоллбэк)."""
    user = (f"Scene: {context_digest}\nPresent NPCs: {npcs or []}\n"
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


def assess_feasibility(manager, action_text: str, context_digest: str):
    """Можно ли вообще совершить это действие игрока в данном контексте (док 06, main §2).
    Возвращает {plausibility, drivers, verdict_note} либо None (нет сервера)."""
    user = (f"Proposed PLAYER action: «{action_text}»\nScene/context: {context_digest}\n"
            f"How physically possible is this action HERE AND NOW? 0 = impossible/"
            f"contradiction or a feat beyond a mortal adventurer; 1 = trivially possible. "
            f"Score creativity-but-possible high; score the impossible low. "
            f"Call estimate_plausibility.")
    return _call(manager, "plausibility", "estimate_plausibility", user,
                 ["plausibility", "drivers"])


def forge_item(manager, template_name: str, category: str, rarity: str, context: str = ""):
    """Назвать и описать конкретный экземпляр предмета по шаблону+контексту (без смены
    механики/редкости/чисел). None — нет сервера, тогда берётся шаблон как есть."""
    user = (f"Item template: {template_name} (category: {category}, rarity: {rarity}).\n"
            f"World context: {context}\n"
            f"Give a fitting in-world NAME, a one-sentence DESCRIPTION, and optional cosmetic "
            f"property tags. Do NOT change rarity/power/numbers. Call forge_item.")
    return _call(manager, "item_smith", "forge_item", user, ["name"])
