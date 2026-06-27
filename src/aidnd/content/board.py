"""Доска объявлений: простые квесты, вывешенные в городе (док 05 §4).

Двухстадийные задания: (1) выполнить требование — раздобыть предмет, поговорить с
кем-то или одолеть цель; (2) вернуться к доске и сдать. Требования — те же
предикаты над миром, что у остальных квестов, поэтому прогресс реактивен и
переживает сейв/лоад (стадии продвигаются на событиях, сдача — флаг turnin:<id>).
"""

from __future__ import annotations

from ..gen.provenance import Provenance
from ..gen.quest_gen import Predicate, Quest, Rewards, Stage

BOARD_PLACE = "building:notice_board"


def _board_quest(qid: str, title: str, objective: str, cond: Predicate,
                 rewards: Rewards, framing: str, req_kind: str, req_ref: str,
                 ttl_days: int = 3) -> Quest:
    q = Quest(
        quest_id=qid, kind="board", title=title, giver_ref=BOARD_PLACE, state="offered",
        stages=[
            Stage("do", objective, completion_conditions=[cond], next_stages=["turnin"]),
            Stage("turnin", "вернуться к доске объявлений и сдать задание",
                  completion_conditions=[Predicate("Flag", [f"turnin:{qid}"])],
                  on_complete=[{"effect": "complete"}]),
        ],
        current_stages=[], rewards=rewards, framing=framing,
        world_bindings=[BOARD_PLACE, req_ref],
        provenance=Provenance(source="authored", generator="board@1.0"),
    )
    q.req_kind = req_kind          # для UI: тип требования (item|talk|bounty)
    q.req_ref = req_ref
    q.ttl_days = ttl_days          # срок жизни объявления (дней) — после него судьба: сделали другие/сняли
    q.req_place = req_ref if str(req_ref).startswith(("place:", "building:", "site:")) else None
    return q


def board_quests() -> list[Quest]:
    """Набор простых заданий с доски (детерминированно — сейв/лоад-сейф)."""
    return [
        _board_quest(
            "quest:board_torch", "Нужен факел",
            "раздобыть факел и принести на доску",
            Predicate("HasItem", ["pc:hero", "tmpl:torch"]),
            Rewards(currency={"gp": 12}, xp=50),
            "Караульным не хватает факелов для ночных обходов. Принеси хоть один.",
            req_kind="item", req_ref="tmpl:torch"),
        _board_quest(
            "quest:board_garaele", "Весть для жрицы",
            "поговорить с сестрой Гарэле в Святилище Удачи",
            Predicate("TalkedTo", ["npc:sister_garaele"]),
            Rewards(currency={"gp": 15}, xp=75, faction_rep={"faction:temple": 0.15}),
            "Нужно передать весточку сестре Гарэле. Найди её в святилище.",
            req_kind="talk", req_ref="npc:sister_garaele"),
        _board_quest(
            "quest:board_klarg", "Награда за Кларга",
            "одолеть багбира Кларга в логове Крэгмо",
            Predicate("NpcDead", ["npc:klarg"]),
            Rewards(currency={"gp": 60}, xp=200, faction_rep={"faction:watch": 0.2}),
            "Стража назначила награду за голову багбира Кларга, что засел в логове Крэгмо.",
            req_kind="bounty", req_ref="npc:klarg"),
    ]


def register_board_quests(world, quest_system) -> None:
    for q in board_quests():
        quest_system.register(q)
