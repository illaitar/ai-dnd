"""Детерминированный движок правил 5e (main §7).

Движок принимает Action, проверяет легальность, при нужде эмитит RollRequest,
разрешает по броску, мутирует состояние через event log, возвращает Outcome.
Нарратор отрисовывает Outcome, не влияя на цифры. Это инвариант архитектуры:
LLM никогда не решает исход и не считает правила.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .checks import assemble_modifier, passive_check
from .dice import DiceService, RollRequest, RollResult


@dataclass
class Action:
    actor: str
    verb: str                       # talk|attack|move|inspect|persuade|intimidate|...
    target: str | None = None
    params: dict = field(default_factory=dict)
    tone: str = "neutral"
    targets_npc: bool = False


@dataclass
class Outcome:
    actor: str
    verb: str
    target: str | None = None
    success: bool | None = None
    crit: bool = False
    fumble: bool = False
    detail: dict = field(default_factory=dict)
    summary: str = ""               # механическое описание (фоллбэк нарратора)


def d20_test(result: RollResult, dc: int | None, is_attack: bool) -> dict:
    """Семантика d20-теста 5e (док 07 §5)."""
    crit = result.nat == 20
    fumble = result.nat == 1
    if is_attack:
        if crit:
            return {"success": True, "crit": True, "fumble": False}
        if fumble:
            return {"success": False, "crit": False, "fumble": True}
        return {"success": dc is None or result.total >= dc, "crit": False, "fumble": False}
    # обычная проверка/спасбросок: nat 20/1 — яркий успех/досадный провал
    success = (dc is None) or (result.total >= dc)
    if crit:
        success = True
    if fumble:
        success = False
    return {"success": success, "crit": crit, "fumble": fumble}


class RulesEngine:
    def __init__(self, world, dice: DiceService) -> None:
        self.world = world
        self.dice = dice

    # ----------------------------------------------- проверки/спасброски ---
    def build_check_request(
        self, actor: str, skill: str, dc: int, *, target: str | None = None,
        kind: str = "skill", env_adv: int = 0,
    ) -> RollRequest:
        is_save = kind == "save"
        mod, adv = assemble_modifier(
            self.world, actor,
            skill=None if is_save else skill,
            ability=skill if is_save else None,
            target=target, kind=kind,
        )
        adv = max(-1, min(1, adv + env_adv))          # погода/свет (док 07 §6)
        return self.dice.request_player(
            kind=kind, dice="1d20", modifier=mod, advantage=adv, dc=dc,
            roller=actor, context={"skill": skill, "target": target},
        )

    def try_passive(self, actor: str, skill: str, dc: int) -> bool:
        return passive_check(self.world, actor, skill) >= dc

    def adjudicate(
        self, action: Action, request: RollRequest, result: RollResult,
    ) -> Outcome:
        is_attack = request.kind == "attack"
        verdict = d20_test(result, request.dc, is_attack)
        return Outcome(
            actor=action.actor, verb=action.verb, target=action.target,
            success=verdict["success"], crit=verdict["crit"], fumble=verdict["fumble"],
            detail={"total": result.total, "nat": result.nat, "dc": request.dc,
                    "skill": request.context.get("skill")},
            summary=self._mech_summary(action, verdict, result, request),
        )

    def _mech_summary(self, action, verdict, result, request) -> str:
        sk = request.context.get("skill", request.kind)
        head = f"{action.actor} {sk} → {result.total}"
        if request.dc is not None:
            head += f" против DC {request.dc}"
        tag = "успех" if verdict["success"] else "провал"
        if verdict["crit"]:
            tag = "критический успех"
        elif verdict["fumble"]:
            tag = "критический провал"
        return f"{head}: {tag}."

    # ------------------------------------------------- бездейственные ------
    def resolve_no_roll(self, action: Action) -> Outcome:
        return Outcome(
            actor=action.actor, verb=action.verb, target=action.target,
            success=True, summary=f"{action.actor} выполняет {action.verb}.",
        )
