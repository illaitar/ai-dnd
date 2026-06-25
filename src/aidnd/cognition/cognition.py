"""Когнитивный слой L3 (main §5.6).

Пайплайн парсинг-оценка-отыгрыш в части NPC: retrieve (память+отношения),
policy (предложение действия NPC с гейтами отношений), observe (запись памяти),
appraise (эволюция отношений), reflect (синтез рефлексий). LLM-пути имеют
детерминированные фоллбэки (док 08 §9), поэтому работают без сервера.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..world.components import Persona, RelEdge
from .memory import CognitionStore, _similarity, _tokens
from .relationships import appraise as _appraise
from .relationships import edge, gate_open


def _stems(toks: set[str]) -> set[str]:
    """5-символьные префиксы значимых слов — грубый стеммер против рус. словоизменения."""
    return {w[:5] for w in toks if len(w) >= 4}


@dataclass
class RetrievedContext:
    persona: Persona | None
    rel: RelEdge
    memories: list = field(default_factory=list)
    topic: str = ""


class Cognition:
    def __init__(self, world, store: CognitionStore | None = None, model=None) -> None:
        self.world = world
        self.store = store or CognitionStore()
        self.model = model

    # --- retrieve (main §5.2) --------------------------------------------- #
    def retrieve(self, npc_id: str, query: str, player_id: str | None = None) -> RetrievedContext:
        mem = self.store.memory(npc_id)
        nodes = mem.retrieve(query, self.world.clock.tick)
        rel = edge(self.world, npc_id, player_id) if player_id else RelEdge()
        persona = self.world.ecs.get(npc_id, Persona)
        return RetrievedContext(persona=persona, rel=rel, memories=nodes, topic=query)

    # --- recall: релевантные запросу факты под гейтом (граф знаний) -------- #
    def recall(self, npc_id: str, query: str, rel: RelEdge | None = None, *,
               gate_level: float | None = None, topic: str | None = None,
               k: int = 5, exclude: set | None = None) -> list[dict]:
        """Наиболее релевантные запросу факты, которые NPC ЗНАЕТ и готов раскрыть.

        Гейт: эффективное доверие (gate_level от пройденной проверки убеждения/обмана,
        иначе rel.trust) против sensitivity факта. Ранжирование: токен-оверлап запроса с
        текстом/тегами/темой факта + бонус за совпадение темы + лёгкий приоритет
        общеизвестного. Топ-k (самый релевантный первым) — это контекст для нарратора."""
        persona = self.world.ecs.get(npc_id, Persona)
        if persona is None:
            return []
        from ..content.knowledge import disclosable
        trust = gate_level if gate_level is not None else (rel.trust if rel else 0.0)
        items = disclosable(persona, trust, topic)
        if exclude:                                     # напр. факты, которые игрок уже знает (unknown-first)
            items = [it for it in items if it.get("fact_id") not in exclude]
        # стем-токены (5-symbol prefix) гасят рус. словоизменение: «красных»≈«красные»
        qstem = _stems(_tokens(query or ""))

        def score(it: dict) -> float:
            ftoks = _tokens(it.get("fact", ""))
            for t in (it.get("tags") or []):
                ftoks |= _tokens(str(t))
            if it.get("topic"):
                ftoks |= _tokens(str(it["topic"]))
            rels = _similarity(qstem, _stems(ftoks)) if qstem else 0.0
            gate = (it.get("disclosure_gate") or {}).get("trust", 0.0)
            prior = 0.08 * (1.0 - gate)                 # общеизвестное чуть выше при прочих равных
            tb = 0.25 if (topic and it.get("topic") == topic) else 0.0
            return rels + tb + prior

        return sorted(items, key=score, reverse=True)[:k]

    # --- observe / appraise (main §5.4) ----------------------------------- #
    def observe(self, npc_id: str, text: str, importance: int = 5) -> None:
        self.store.memory(npc_id).add_observation(text, self.world.clock.tick, importance)

    def appraise(self, npc_id: str, actor_id: str, verb: str, tone: str | None = None,
                 success: bool | None = None) -> dict:
        return _appraise(self.world, npc_id, actor_id, verb, tone, success)

    def observe_and_appraise(self, npc_id: str, actor_id: str, verb: str,
                             tone: str | None, summary: str) -> None:
        self.observe(npc_id, summary, importance=6 if verb in ("attack", "give", "help") else 4)
        self.appraise(npc_id, actor_id, verb, tone)
        if verb != "attack":          # в бою не рефлексируем на каждый удар (лаг + шум)
            self.maybe_reflect(npc_id)

    def maybe_reflect(self, npc_id: str, every: int = 4) -> list[dict]:
        """Накопив опыт, NPC периодически синтезирует рефлексии (роль reflection).
        Память когниции вне state_hash, так что реплей не страдает."""
        mem = self.store.memory(npc_id)
        obs = [n for n in mem.nodes.values() if n.kind == "observation"]
        if len(obs) >= 3 and len(obs) % every == 0:
            return self.reflect(npc_id)
        return []

    # --- policy (NPC action proposer, main §12.2) ------------------------- #
    def policy(self, npc_id: str, player_verb: str, tone: str, ctx: RetrievedContext,
               player_id: str) -> dict:
        """Предлагает действие NPC. LLM при наличии модели, иначе детерминированный
        фоллбэк с гейтами отношений."""
        if self.model is not None:
            from ..inference.agents import propose_action
            out = propose_action(self.model, npc_id, player_verb, tone, ctx, self.world)
            if out:
                return out
        return self._fallback_policy(npc_id, player_verb, tone, ctx, player_id)

    _SOCIABLE_TRAITS = {"welcoming", "gossipy", "friendly", "talkative", "chatty", "jovial",
                        "gregarious", "warm"}
    _RESERVED_TRAITS = {"secretive", "manipulative", "suspicious", "cold", "gruff", "taciturn",
                        "ambitious", "cowardly"}
    _SOCIABLE_JOBS = {"innkeeper", "merchant", "bartender", "host", "trader",
                      "shopkeeper", "barkeep"}

    def _sociable(self, npc_id: str) -> bool:
        """Радушен по натуре: сфера услуг или общительные черты → болтает с чужаками.
        Скрытные/манипулятивные/интриганы — нет, даже если профессия торговая (напр., Халия)."""
        from ..world.components import Persona
        p = self.world.ecs.get(npc_id, Persona)
        if not p:
            return False
        traits = {t.lower() for t in (p.traits or [])}
        if traits & self._RESERVED_TRAITS:
            return False
        if traits & self._SOCIABLE_TRAITS:
            return True
        return (p.profession or "") in self._SOCIABLE_JOBS or (p.archetype or "") in self._SOCIABLE_JOBS

    def _fallback_policy(self, npc_id, player_verb, tone, ctx, player_id) -> dict:
        rel = ctx.rel
        # враждебные намерения
        if player_verb in ("attack", "threaten", "intimidate"):
            if gate_open(self.world, npc_id, player_id, "flee"):
                return {"action": "flee", "rationale_tags": ["high_fear"]}
            if rel.respect < -0.2 or player_verb == "attack":
                return {"action": "call_guards", "rationale_tags": ["threatened"]}
            return {"action": "yield", "rationale_tags": ["intimidated"]}
        if player_verb == "steal":
            return {"action": "call_guards", "rationale_tags": ["theft"]}
        if player_verb in ("persuade", "talk"):
            if gate_open(self.world, npc_id, player_id, "share_secret"):
                return {"action": "share_info", "info_disclosed": ["secret"],
                        "rationale_tags": ["trusts_player"]}
            if gate_open(self.world, npc_id, player_id, "share_info"):
                return {"action": "share_info", "info_disclosed": ["rumor"],
                        "rationale_tags": ["mild_trust"]}
            if self._sociable(npc_id) and tone != "hostile":   # сфера услуг/болтлив — радушен к чужаку
                return {"action": "share_info", "info_disclosed": ["rumor"],
                        "rationale_tags": ["sociable"]}
            return {"action": "withhold", "rationale_tags": ["distrust"]}
        if player_verb == "trade":
            return {"action": "trade", "rationale_tags": ["merchant"]}
        return {"action": "respond", "rationale_tags": ["neutral"]}

    # --- reflect (main §5.5, §12.7) --------------------------------------- #
    def reflect(self, npc_id: str) -> list[dict]:
        mem = self.store.memory(npc_id)
        recent = [n for n in mem.nodes.values() if n.kind == "observation"]
        if len(recent) < 3:
            return []
        if self.model is not None:
            from ..inference.agents import emit_reflections
            out = emit_reflections(self.model, npc_id, recent, self.world)
            made = []
            for r in out or []:                       # модель может переименовать поля
                if not isinstance(r, dict):
                    continue
                stmt = (r.get("statement") or r.get("text") or r.get("summary")
                        or r.get("reflection"))
                if not stmt:
                    continue
                ev = r.get("evidence_ids") or []
                mem.add_reflection(stmt, ev, self.world.clock.tick, r.get("importance", 7))
                made.append({"statement": stmt, "evidence_ids": ev,
                             "importance": r.get("importance", 7)})
            if made:
                return made
        # фоллбэк: одна агрегирующая рефлексия по последним наблюдениям
        recent.sort(key=lambda n: n.t)
        ev = [n.node_id for n in recent[-5:]]
        statement = "Игрок недавно активно влиял на мою жизнь."
        mem.add_reflection(statement, ev, self.world.clock.tick, 6)
        return [{"statement": statement, "evidence_ids": ev, "importance": 6}]
