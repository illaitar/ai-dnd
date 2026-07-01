"""ДОЛГОСРОЧНЫЕ ЦЕЛИ (агенды) — слой поверх реактивной механики. Реактивное ядро умеет отвечать
лишь на ТЕКУЩИЙ тик (нужда/угроза/возможность в поле зрения); оно НЕ придумает «скопить на пекарню»,
«завоевать Нэлл» или «отомстить Гарету». Это придумывает LLM-планировщик (рефлексия по памяти/натуре/
ситуации) и кладёт в state.agendas. Каждая агенда = исход + вехи; текущая веха ИНЖЕКТИТСЯ обычной
механической целью в propose_goals, и ядро тянет её реактивно (сближается/выжидает/бьёт/работает/дарит).

Мирные и хищные цели — один механизм: отличается лишь kind вехи (need/affiliate/trade vs acquire/harm)
и цель. Острая нужда/угроза по-прежнему ПЕРЕБИВАЮТ агенду (реактивный слой выигрывает арбитраж).
LLM-планировщик — в llm_agent.plan_agenda; здесь модель данных + продвижение вех + офлайн-заглушка.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Milestone:
    desc: str
    kind: str                                   # механическая цель: need|affiliate|trade|acquire|harm
    target: str | None = None                   # сущность / имя нужды / место
    meta: dict = field(default_factory=dict)    # доп. (source для need и т.п.)
    done: dict = field(default_factory=lambda: {"type": "never"})   # предикат завершения вехи


@dataclass
class Agenda:
    summary: str
    kind: str = "ambition"                      # ambition|wealth|courtship|revenge|predation|…
    importance: float = 0.7                     # базовый payoff инжектируемой цели [0..1]
    milestones: list = field(default_factory=list)
    cursor: int = 0
    status: str = "active"                       # active | done | abandoned

    def current(self) -> Milestone | None:
        if self.status != "active" or self.cursor >= len(self.milestones):
            return None
        return self.milestones[self.cursor]

    def view(self) -> dict:
        m = self.current()
        return {"summary": self.summary, "kind": self.kind, "importance": round(self.importance, 2),
                "status": self.status, "cursor": self.cursor, "steps": len(self.milestones),
                "now": m.desc if m else "—"}


def _wealth(state, world) -> float:
    b = world.bodies.get(state.config.id)
    return sum(i.value for i in (b.loot + b.carrying)) if b else 0.0


def _met(cond: dict, state, world) -> bool:
    """Проверяемый предикат завершения вехи (маленький словарь типов — расширяемо)."""
    ty = cond.get("type")
    if ty == "wealth":
        return _wealth(state, world) >= float(cond.get("value", 1.0))
    if ty == "dead":
        tb = world.bodies.get(cond.get("id"))
        return bool(tb and tb.down())
    if ty == "affinity":
        return (state.relationships.get(cond.get("id")) or {}).get("affinity", 0.0) >= float(cond.get("value", 0.5))
    if ty == "at":
        b = world.bodies.get(state.config.id)
        return bool(b and b.place == cond.get("place"))
    if ty == "have":
        b = world.bodies.get(state.config.id)
        nm = str(cond.get("item", "")).lower()
        return bool(b and any(nm in i.name.lower() for i in b.loot + b.carrying))
    return False                                 # "never" — веха-стояк, сама не закрывается


def advance_agendas(state, world) -> list:
    """Продвинуть вехи, чьи условия выполнены; завершить исчерпанные агенды. Вернуть события."""
    events = []
    for ag in getattr(state, "agendas", None) or []:
        if ag.status != "active":
            continue
        m = ag.current()
        while m and _met(m.done, state, world):
            ag.cursor += 1
            events.append((ag.summary, "веха", m.desc))
            m = ag.current()
        if ag.cursor >= len(ag.milestones):
            ag.status = "done"
            events.append((ag.summary, "исполнена", ""))
    return events


# ── офлайн-заглушка планировщика: детерминированные агенды по натуре (для демо/тестов без LLM) ──
class StubPlanner:
    """Без LLM: выдаёт правдоподобную агенду из черт (мирную или хищную). LLM-версия — llm_agent."""

    def plan(self, state, world, ctx=None) -> Agenda | None:
        t = state.config.traits
        if t.get("malice", 0) > 0.6 or t.get("greed", 0) > 0.75:
            mark = ctx.get("mark") if ctx else None
            return predation_agenda(mark or "цель")
        if t.get("sociability", 0) > 0.6:
            return courtship_agenda((ctx or {}).get("beloved", "Нэлл"))
        return wealth_agenda((ctx or {}).get("dream", "своё дело"), goal=1.0)


# ── фабрики типовых агенд (мирные и нет) ──
def wealth_agenda(dream: str, goal: float = 1.0, work: str | None = None) -> Agenda:
    src = {"source": work} if work else {}
    return Agenda(f"скопить на {dream}", "wealth", 0.75, [
        Milestone(f"заработать на {dream}", "need", "wealth", src, {"type": "wealth", "value": goal}),
    ])


def courtship_agenda(beloved: str) -> Agenda:
    return Agenda(f"завоевать расположение — {beloved}", "courtship", 0.8, [
        Milestone(f"расположить к себе {beloved}", "affiliate", beloved, {},
                  {"type": "affinity", "id": beloved, "value": 0.5}),
    ])


def revenge_agenda(foe: str) -> Agenda:
    return Agenda(f"отомстить — {foe}", "revenge", 0.9, [
        Milestone(f"покончить с {foe}", "harm", foe, {}, {"type": "dead", "id": foe}),
    ])


def predation_agenda(mark: str) -> Agenda:
    return Agenda(f"обчистить — {mark}", "predation", 0.85, [
        Milestone(f"завладеть добром {mark}", "acquire", mark, {}, {"type": "have", "item": "кошель"}),
    ])
