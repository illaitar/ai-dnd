"""End-to-end сцены для судейства (LLM-as-judge, main §13).

Каждая сцена прогоняется через полный движок и собирает транскрипт: контекст,
выход агента (модель ИЛИ детерминированный фоллбэк — с пометкой source),
механические факты и автопроверки рубрики. Внешний судья (человек/LLM) читает
транскрипт и выставляет субъективную believability поверх автопроверок.

Запуск:  python -m aidnd.eval            (все сцены, человекочитаемо)
         python -m aidnd.eval --json     (машинный транскрипт)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..bootstrap import new_session
from ..gen import check_world_invariants
from ..inference import agents
from ..world.components import Persona
from .rubric import (
    Check,
    gate_respected,
    intent_valid,
    narrator_preserves_numbers,
    schema_valid,
)


@dataclass
class Step:
    role: str
    context: str
    output: object = None
    source: str = "fallback"        # model | fallback
    note: str = ""


@dataclass
class Transcript:
    scene: str
    description: str
    steps: list = field(default_factory=list)
    checks: list = field(default_factory=list)
    mechanics: dict = field(default_factory=dict)
    judge_questions: list = field(default_factory=list)

    def add(self, step: Step):
        self.steps.append(step)

    def check(self, c: Check):
        self.checks.append(c)

    @property
    def auto_passed(self) -> bool:
        return all(c.passed for c in self.checks)


def _try(fn, *args, fallback=None):
    """Вызывает агента модели; возвращает (output, 'model') либо (fallback, 'fallback')."""
    out = fn(*args)
    if out is not None:
        return out, "model"
    return fallback, "fallback"


# --------------------------------------------------------------------------- #
#  Сцена 1. Парсинг намерения игрока (Intent Parser, main §12.1)              #
# --------------------------------------------------------------------------- #
def scene_intent(session) -> Transcript:
    t = Transcript("intent_parse", "Парсинг свободного текста игрока в структурный интент")
    utterances = [
        ("бью гоблина мечом", ["Кларг", "Гоблин-страж"]),
        ("спрашиваю Тоблена про Красных плащей", ["Тоблен Стоунхилл"]),
        ("крадусь к сундуку и обыскиваю его", []),
    ]
    for text, opts in utterances:
        out, src = _try(agents.parse_intent, session.model, text, "pc:hero", opts,
                        fallback=_fallback_intent(session, text))
        t.add(Step("intent_parser", f"player: «{text}» | options={opts}", out, src))
        t.check(intent_valid(out, opts))
    t.judge_questions = ["Совпадает ли verb с реальным намерением игрока?",
                         "Не выдуман ли target вне видимых опций?"]
    return t


def _fallback_intent(session, text):
    a = session._parse_intent(text)
    return {"actor": a.actor, "verb": a.verb, "target": a.target,
            "tone": a.tone, "needs_clarification": False}


# --------------------------------------------------------------------------- #
#  Сцена 2. Диалог в таверне: L3 + когниция + нарратор (main §5, §12.2-3)     #
# --------------------------------------------------------------------------- #
def scene_tavern_dialogue(session) -> Transcript:
    t = Transcript("tavern_dialogue",
                   "Игрок расспрашивает трактирщика Тоблена о Красных плащах")
    npc = "npc:toblen_stonehill"
    session.lod.ensure_tier(npc, in_dialogue=True)

    # ленивое обогащение персоны (first L3)
    persona = session.world.ecs.get(npc, Persona)
    out, src = _try(agents.enrich_persona, session.model, persona, session.world,
                    fallback={"voice": "тёплый, болтливый", "traits": persona.traits})
    t.add(Step("character_gen/enrich", f"skeleton: {persona.name}, {persona.archetype}",
               out, src))
    t.check(schema_valid(out, "emit_persona"))

    # когниция: предложение действия NPC с учётом отношений
    ctx = session.cognition.retrieve(npc, "Красные плащи", session.player)
    rel = ctx.rel
    decision, dsrc = _try(agents.propose_action, session.model, npc, "talk", "neutral",
                          ctx, session.world,
                          fallback=session.cognition._fallback_policy(
                              npc, "talk", "neutral", ctx, session.player))
    t.add(Step("npc_cognition", f"trust={rel.trust:.2f} fear={rel.fear:.2f} topic=redbrands",
               decision, dsrc))
    t.check(schema_valid(decision, "propose_action"))
    t.check(gate_respected(decision, rel.trust, rel.fear))

    # нарратор отрисовывает реплику — заземлённый диалог (без выдуманной истории)
    rel_sum = session._rel_summary(rel, first_meeting=not ctx.memories)
    fb = {"narration": session._npc_reply(npc, decision, "что слышно о Красных плащах?",
                                          rel, not ctx.memories, [])}
    line = agents.render_dialogue(session.model, persona, rel_sum,
                                  "The player asks about the Redbrands.",
                                  "что слышно о Красных плащах?", decision.get("action", "respond"))
    narr, nsrc = ({"narration": line}, "model") if line else (fb, "fallback")
    t.add(Step("narrator", f"reply intent={decision.get('action')}; rel={rel_sum}", narr, nsrc))
    t.check(narrator_preserves_numbers(set(), narr.get("narration", "")))
    t.mechanics = {"trust": rel.trust, "fear": rel.fear, "decision": decision.get("action")}
    t.judge_questions = [
        "Звучит ли реплика как трактирщик (in-character, voice)?",
        "Соответствует ли тон решению (withhold→уклончиво, share_info→делится)?",
        "Не раскрыл ли секрет при низком доверии?"]
    return t


# --------------------------------------------------------------------------- #
#  Сцена 3. Боевой раунд: композиция + тактик + нарратор (док 09, §12.3, §12.6)#
# --------------------------------------------------------------------------- #
def scene_combat_round(session) -> Transcript:
    t = Transcript("combat_round", "Атака игрока по Кларг + ход монстра + нарратив исхода")
    session.handle("идти в логово")
    session.handle("идти в пещеру")
    session.start_combat(["npc:klarg", "npc:goblin_1", "npc:goblin_2"])
    eng = session.combat
    if not eng.is_pc_turn():
        eng.advance_turn()
    # поставим PC вплотную к Кларг (сцена про разрешение атаки, не про движение)
    kpos = eng.state.combatants["npc:klarg"].pos
    adj = next((n for n in eng.state.grid.neighbors(*kpos) if not eng.state.at(n)), None)
    if adj:
        eng.state.combatants["pc:hero"].pos = adj
    req = eng.pc_declare_attack("npc:klarg")
    from ..rules.dice import validate_player_roll
    atk = validate_player_roll(req, [18])     # nat 18 + мод → попадание
    out = eng.submit_roll(atk)
    hit = out.get("hit", False)
    dmg = 0
    if not out["done"]:
        dreq = out["next_request"]
        dmg_res = validate_player_roll(dreq, [6])
        dmg = dmg_res.total
        out = eng.submit_roll(dmg_res)
    t.add(Step("rules_engine", f"attack mod={req.modifier} vs AC {req.dc}; nat 18",
               {"hit": hit, "damage": dmg}, "deterministic"))
    t.mechanics = {"attack_mod": req.modifier, "target_ac": req.dc, "damage": dmg, "hit": hit}

    # нарратор отрисовывает механический исход — НЕ меняя цифры
    persona = session.world.ecs.get("npc:klarg", Persona)
    mech_summary = f"pc:hero hits npc:klarg for {dmg} damage with a longsword"
    narr, nsrc = _try(agents.render_scene, session.model, mech_summary, persona, "combat",
                      fallback={"narration": f"Клинок героя рассекает Кларга на {dmg} урона."})
    t.add(Step("narrator", mech_summary, narr, nsrc))
    t.check(narrator_preserves_numbers({dmg, req.modifier, req.dc}, narr.get("narration", ""),
                                       hit=hit))

    # ход монстра — тактик
    eng.advance_turn()
    cur = eng.state.current()
    if cur and cur != session.player:
        digest = f"round {eng.state.round}; Кларг hp low; PC in melee"
        tac, tsrc = _try(agents.choose_tactic, session.model, digest, cur,
                         fallback={"intent": "attack", "target": session.player})
        t.add(Step("combat_tactician", digest, tac, tsrc))
        t.check(schema_valid(tac, "choose_tactic"))
    t.judge_questions = [
        "Сохранил ли нарратор урон ровно " + str(dmg) + " и факт попадания?",
        "Уместна ли тактика монстра по интеллекту/морали?"]
    return t


# --------------------------------------------------------------------------- #
#  Сцена 4. Консистентная ленивая генерация NPC (Lore-Keeper, main §12.4-5)   #
# --------------------------------------------------------------------------- #
def scene_lazy_npc(session) -> Transcript:
    t = Transcript("lazy_npc_generation",
                   "Игрок обратился к незаполненному слоту «стражник» → полная персона")
    before = len(session.world.npcs())
    npc_id = session.charts.spawn_npc("Безымянный Страж", "human", "guard",
                                      "region:phandalin", place_id="place:phandalin_square")
    persona = session.world.ecs.get(npc_id, Persona)
    from ..world.components import Profession
    prof = session.world.ecs.get(npc_id, Profession)
    # обогащение персоны моделью (творческое поле voice)
    out, src = _try(agents.enrich_persona, session.model, persona, session.world,
                    fallback={"voice": "сухой, по-военному краткий", "traits": persona.traits})
    persona.voice = out.get("voice", persona.voice)
    t.add(Step("character_gen", f"slot=guard at square; spawned {npc_id}",
               {"name": persona.name, "works_at": prof.workplace_ref if prof else None,
                "lives_in": prof.residence_ref if prof else None, "voice": persona.voice}, src))
    t.check(schema_valid(out, "emit_persona"))
    # инварианты после коммита: профессия ⟹ workplace + residence (main §12.4)
    viol = check_world_invariants(session.world)
    t.check(Check("world_invariants", not viol,
                  "нет нарушений" if not viol else f"{len(viol)} нарушений"))
    t.check(Check("npc_persisted", len(session.world.npcs()) == before + 1,
                  "NPC зафиксирован в сторе"))
    t.mechanics = {"works_at": prof.workplace_ref if prof else None,
                   "lives_in": prof.residence_ref if prof else None}
    t.judge_questions = ["Уместна ли персона для роли стражника и демографии Фэндалина?"]
    return t


SCENES = {
    "intent_parse": scene_intent,
    "tavern_dialogue": scene_tavern_dialogue,
    "combat_round": scene_combat_round,
    "lazy_npc_generation": scene_lazy_npc,
}


def run_scene(name: str, seed: int = 1337, use_model: bool = True) -> Transcript:
    session = new_session(seed=seed, roster_size=8, use_model=use_model)
    return SCENES[name](session)


def run_all(seed: int = 1337, use_model: bool = True) -> list[Transcript]:
    # отдельная сессия на сцену — изоляция состояния
    return [run_scene(name, seed, use_model) for name in SCENES]
