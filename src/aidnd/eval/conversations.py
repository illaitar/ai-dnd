"""Диалоговые сцены для судейства общения с NPC (main §5.4, §12.2-3).

Цель — реалистичные по контексту сценарии, проверяющие, что модель адекватно
реагирует на ВЕКТОР ОТНОШЕНИЯ (слайдеры affinity/trust/fear/respect). Один и тот
же ввод при разных слайдерах должен давать разное поведение: незнакомец молчит,
доверенный — делится; напуганный — сдаётся/бежит; враждебный — отказывает.

Объективная часть рубрики (контракты, держат и модель, и фоллбэк):
* схемная валидность propose_action;
* гейт секрета: секрет не раскрывается при trust < 0.6;
* гейт страха: при враждебном вводе и fear ≥ 0.6 NPC защищается (flee/yield/call_guards);
* заземление: на первой встрече нет выдуманной общей истории.

Субъективную believability судья выставляет поверх транскрипта (в т.ч. LLM-судья).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from ..bootstrap import new_session
from ..inference import agents
from ..world.components import Persona, Relationships, RelEdge
from .rubric import Check, schema_valid
from .scenes import Step, Transcript, _try

CASES_FILE = os.path.join(os.path.dirname(__file__), "conversation_cases.json")

_HISTORY_WORDS = ("снова", "опять", "как всегда", "в прошлый раз", "помнишь",
                  "старый друг", "рад снова", "давно не", "при нашей встрече",
                  "прошл")


@dataclass
class ConvScenario:
    key: str
    npc: str
    trust: float = 0.0
    affinity: float = 0.0
    fear: float = 0.0
    respect: float = 0.0
    met: bool = False               # знакомы ранее (есть воспоминания)
    player_line: str = ""
    verb: str = "talk"              # talk | persuade | intimidate
    tone: str = "neutral"
    hostile: bool = False           # враждебный ввод (для гейта страха)
    asks_secret: bool = False       # игрок выпытывает секрет
    expected: dict = field(default_factory=dict)   # action_in/no_secret/defensive/shares_fact
    notes: str = ""
    judge: list = field(default_factory=list)


SCENARIOS = [
    ConvScenario("stranger_probes_secret", "npc:halia_thornton", trust=0.0,
                 player_line="Поговаривают, ты связана с Жентаримом. Это правда?",
                 asks_secret=True,
                 judge=["Уклонилась ли как от чужака?", "НЕ раскрыла ли секрет про Жентарим?"]),
    ConvScenario("trusted_ally_shares", "npc:halia_thornton", trust=0.75, affinity=0.6,
                 respect=0.4, met=True,
                 player_line="Между нами — ты ведь работаешь на Жентарим? Я с тобой.",
                 asks_secret=True,
                 judge=["Чувствуется ли доверие/теплота?",
                        "При высоком trust допустимо приоткрыть тайну — звучит ли это естественно?"]),
    ConvScenario("first_greeting", "npc:toblen_stonehill", trust=0.0,
                 player_line="", verb="talk",
                 judge=["Приветствует ли как НЕЗНАКОМЦА?",
                        "Спрашивает ли, что игроку нужно, без выдуманной истории?"]),
    ConvScenario("mild_trust_rumor", "npc:toblen_stonehill", trust=0.3, affinity=0.2, met=True,
                 player_line="Что в городе говорят про Красных плащей?",
                 judge=["Делится ли городским слухом (trust≥0.2 открывает)?",
                        "Тон тёплый, болтливый — в характере трактирщика?"]),
    ConvScenario("intimidated_yields", "npc:toblen_stonehill", fear=0.75, trust=-0.2,
                 met=True, verb="intimidate", tone="hostile", hostile=True,
                 player_line="Говори, где прячутся Красные плащи, или пожалеешь!",
                 judge=["При высоком страхе — сдаётся/зовёт стражу/уступает?",
                        "Звучит ли испуг убедительно?"]),
    ConvScenario("hostile_faction_refuses", "npc:iarno_glasstaff", trust=-0.6, affinity=-0.5,
                 respect=-0.3, met=True,
                 player_line="Сдавайся и расскажи о планах Чёрного Паука.",
                 hostile=False,
                 judge=["Отказывает/презрителен, как и подобает враждебному боссу?",
                        "Не выдаёт ли план просто так?"]),
    ConvScenario("quest_giver_hook", "npc:harbin_wester", trust=0.35, affinity=0.2, met=True,
                 player_line="Чем я могу помочь городу? Что вас тревожит?",
                 judge=["Всплывает ли реальная зацепка (орки у Вайверн-Тор)?",
                        "Звучит ли как робкий городской голова?"]),
]


def _setup(session, sc: ConvScenario):
    """Выставляет слайдеры отношения NPC→игрок и (опц.) делает их знакомыми."""
    rels = session.world.ecs.get(sc.npc, Relationships)
    if rels is None:
        rels = Relationships()
        session.world.ecs.add(sc.npc, rels)
    rels.edges[session.player] = RelEdge(affinity=sc.affinity, trust=sc.trust,
                                         fear=sc.fear, respect=sc.respect)
    if sc.met:
        session.cognition.observe(sc.npc, "я уже встречал этого человека раньше", importance=3)


def _grounding_check(narration: str, first_meeting: bool) -> Check:
    if not first_meeting:
        return Check("grounding", True, "знакомы — общая история допустима")
    low = (narration or "").lower()
    bad = [w for w in _HISTORY_WORDS if w in low]
    return Check("grounding_no_invented_history", not bad,
                 "нет выдуманной истории" if not bad else f"намёки на прошлое: {bad}")


DEFENSIVE = ("flee", "yield", "call_guards", "deceive")


def _expected_checks(decision, narration, facts, sc: ConvScenario) -> list[Check]:
    """Проверки по ожидаемому результату кейса (editable expected)."""
    exp = sc.expected or {}
    out = []
    action = decision.get("action") if isinstance(decision, dict) else None
    disclosed = (decision.get("info_disclosed") or []) if isinstance(decision, dict) else []
    # 1) действие в допустимом множестве (если задано)
    allowed = exp.get("action_in") or []
    if allowed:
        out.append(Check("action_in", action in allowed,
                         f"action={action}, ожидалось {allowed}"))
    # 2) секрет не утёк
    if exp.get("no_secret"):
        leaked = any("secret" in str(d).lower() or "тайн" in str(d).lower() for d in disclosed)
        out.append(Check("no_secret", not leaked,
                         "секрет не раскрыт" if not leaked else "СЕКРЕТ РАСКРЫТ"))
    # 3) защитная реакция (при страхе/угрозе)
    if exp.get("defensive"):
        out.append(Check("defensive", action in DEFENSIVE,
                         f"action={action}, ожидалась защита {DEFENSIVE}"))
    # 4) делится фактом (soft — для судьи: упоминает ли реальное знание)
    if exp.get("shares_fact"):
        low = (narration or "").lower()
        hit = any(any(w in low for w in f.lower().split() if len(w) > 4) for f in (facts or []))
        out.append(Check("shares_known_fact", hit,
                         "упомянут реальный факт" if hit else "конкретный факт не упомянут",
                         hard=False))
    return out


def run_conversation(session, sc: ConvScenario) -> Transcript:
    t = Transcript(f"conv:{sc.key}", _scenario_desc(sc))
    npc = sc.npc
    session.lod.ensure_tier(npc, in_dialogue=True)
    session.charts.enrich(npc)
    _setup(session, sc)
    persona = session.world.ecs.get(npc, Persona)
    ctx = session.cognition.retrieve(npc, sc.player_line or "приветствие", session.player)
    first_meeting = not sc.met
    rel = ctx.rel
    t.add(Step("слайдеры", f"{session._display(npc)} → игрок",
               {"trust": rel.trust, "affinity": rel.affinity, "fear": rel.fear,
                "respect": rel.respect, "met": sc.met}, "setup"))

    # 1) когниция: предложение действия NPC (модель / фоллбэк)
    decision, dsrc = _try(agents.propose_action, session.model, npc, sc.verb, sc.tone,
                          ctx, session.world,
                          fallback=session.cognition._fallback_policy(
                              npc, sc.verb, sc.tone, ctx, session.player))
    t.add(Step("npc_cognition", f"verb={sc.verb} «{sc.player_line or '(подошёл молча)'}»",
               decision, dsrc))
    t.check(schema_valid(decision, "propose_action"))

    # 2) нарратор: заземлённая реплика NPC + физический контекст + гейтнутые знания
    facts = session._disclosable_facts(npc, rel)
    rel_sum = session._rel_summary(rel, first_meeting)
    situation = ("A stranger approaches and greets you" if not sc.player_line and first_meeting
                 else f"The player ({'threatening' if sc.hostile else 'neutral'}) says: «{sc.player_line}»")
    fb = (session._npc_greeting(npc, rel, first_meeting) if not sc.player_line
          else session._npc_reply(npc, decision, sc.player_line, rel, first_meeting, []))
    line = agents.render_dialogue(
        session.model, persona, rel_sum, situation, sc.player_line,
        decision.get("action", "respond") if isinstance(decision, dict) else "respond",
        scene=session.scene_descriptor(), facts=facts)
    narr, nsrc = (line, "model") if line else (fb, "fallback")
    t.add(Step("narrator", f"scene: {session.scene_descriptor()[:60]} | rel: {rel_sum}", narr, nsrc))
    for c in _expected_checks(decision, narr, facts, sc):
        t.check(c)
    t.check(_grounding_check(narr, first_meeting))
    t.mechanics = {"trust": rel.trust, "fear": rel.fear, "affinity": rel.affinity,
                   "decision": decision.get("action") if isinstance(decision, dict) else None,
                   "facts_available": len(facts)}
    t.judge_questions = sc.judge or _judge_from_notes(sc)
    return t


def _judge_from_notes(sc: ConvScenario) -> list[str]:
    return [sc.notes] if sc.notes else ["Адекватна ли реакция по контексту и слайдерам?"]


def _scenario_desc(sc: ConvScenario) -> str:
    who = {"npc:halia_thornton": "Halia (тайный агент Жентарим)",
           "npc:toblen_stonehill": "трактирщик Toblen",
           "npc:iarno_glasstaff": "Glasstaff (босс Красных плащей)",
           "npc:harbin_wester": "глава города Harbin"}.get(sc.npc, sc.npc)
    state = f"trust={sc.trust} fear={sc.fear} aff={sc.affinity}"
    return f"{who} [{state}] — «{sc.player_line or 'инициация'}»"


def _case_to_scenario(d: dict) -> ConvScenario:
    return ConvScenario(
        key=d.get("id", "case"), npc=d["npc"],
        trust=d.get("trust", 0.0), affinity=d.get("affinity", 0.0),
        fear=d.get("fear", 0.0), respect=d.get("respect", 0.0), met=d.get("met", False),
        player_line=d.get("player_line", ""), verb=d.get("verb", "talk"),
        tone=d.get("tone", "neutral"), hostile=d.get("hostile", False),
        asks_secret=d.get("asks_secret", False), expected=d.get("expected", {}),
        notes=d.get("notes", ""), judge=d.get("judge", []))


def load_cases() -> list[ConvScenario]:
    """Кейсы из редактируемого JSON (fallback — встроенные SCENARIOS)."""
    if os.path.exists(CASES_FILE):
        try:
            with open(CASES_FILE, encoding="utf-8") as f:
                return [_case_to_scenario(d) for d in json.load(f)]
        except (json.JSONDecodeError, KeyError):
            pass
    return list(SCENARIOS)


def load_raw_cases() -> list[dict]:
    if os.path.exists(CASES_FILE):
        with open(CASES_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_cases(raw: list[dict]) -> None:
    with open(CASES_FILE, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)


def run_case_by_id(case_id: str, seed: int = 1337, use_model: bool = True) -> Transcript:
    sc = next((c for c in load_cases() if c.key == case_id), None)
    if sc is None:
        raise KeyError(case_id)
    return run_conversation(new_session(seed=seed, roster_size=4, use_model=use_model), sc)


def run_case_dict(d: dict, seed: int = 1337, use_model: bool = True) -> Transcript:
    """Прогнать (возможно несохранённый) отредактированный кейс."""
    sc = _case_to_scenario(d)
    return run_conversation(new_session(seed=seed, roster_size=4, use_model=use_model), sc)


def transcript_to_dict(t: Transcript) -> dict:
    from dataclasses import asdict
    return {"scene": t.scene, "description": t.description,
            "steps": [asdict(s) for s in t.steps],
            "checks": [asdict(c) for c in t.checks],
            "mechanics": t.mechanics, "judge_questions": t.judge_questions,
            "hard_passed": all(c.passed for c in t.checks if c.hard)}


def run_all(seed: int = 1337, use_model: bool = True) -> list[Transcript]:
    out = []
    for sc in load_cases():
        session = new_session(seed=seed, roster_size=4, use_model=use_model)
        out.append(run_conversation(session, sc))
    return out
