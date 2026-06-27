"""Гильдия приключенцев: стояние/ранг, контракты на угрозы региона, перки.

Стояние — репутация `faction:adventurers_guild` в world.reputation (персист через события faction_rep).
Ранг растёт за выполненные контракты/задания. Перки по рангу: наводки на угрозы (взятие контракта
ОТКРЫВАЕТ путь к подземелью → бой достижим), скидки в лавках (вяжется позже в систему снабжения).
Контракты на угрозы — региональные подземелья (REGION_SITES); NPC-партии гильдии забирают невзятые
задания (это и есть «выполнено другими»).
"""

from __future__ import annotations

from ..gen.provenance import Provenance
from ..gen.quest_gen import Predicate, Quest, Rewards, Stage

GUILD = "faction:adventurers_guild"
GUILD_DESK = "building:adventurers_guild"          # дом гильдии (мастер гильдии — npc:guildmaster_yarra)
GUILD_MASTER = "npc:guildmaster_yarra"

# ранги по стоянию (репутации 0..1)
RANKS = [(0.0, "Новичок"), (0.15, "Подмастерье"), (0.35, "Ветеран"), (0.6, "Мастер"), (0.85, "Легенда")]
# минимальный РАНГ (индекс), чтобы взять контракт данной опасности
MIN_RANK = {"низкая": 0, "средняя": 1, "высокая": 1, "смертельная": 2}
_DANGER_GOLD = {"низкая": 40, "средняя": 80, "высокая": 150, "смертельная": 300}
_DANGER_XP = {"низкая": 100, "средняя": 200, "высокая": 350, "смертельная": 600}


def rank_of(rep: float) -> tuple[int, str]:
    idx, name = 0, RANKS[0][1]
    for i, (th, nm) in enumerate(RANKS):
        if rep >= th:
            idx, name = i, nm
    return idx, name


def next_rank(rep: float) -> tuple[float | None, str | None]:
    for th, nm in RANKS:
        if rep < th:
            return th, nm
    return None, None


def perks_at(rank_idx: int) -> list[str]:
    """Перки, открытые на текущем ранге (человекочитаемо для UI)."""
    out = []
    if rank_idx >= 1:
        out.append("Наводки на угрозы: берёшь контракт — гильдия указывает путь к логову.")
    if rank_idx >= 2:
        out.append("Скидка 10% в городских лавках (по членству гильдии).")
        out.append("Доступны смертельно опасные контракты.")
    if rank_idx >= 3:
        out.append("Скидка 15% и приоритетные контракты.")
    return out


def shop_discount(rank_idx: int) -> float:
    """Скидка в лавках по рангу (доля). Вяжется в систему снабжения (этап A)."""
    return 0.15 if rank_idx >= 3 else 0.10 if rank_idx >= 2 else 0.0


def threat_level(world, site_place: str) -> float:
    """Угроза подземелья 0..1: РАСТЁТ со временем, пока логово не зачищено (нарастание давления
    на округу). Зачищено → 0. Чем выше угроза — тем дороже контракт и тревожнее вести."""
    if f"cleared:{site_place}" in world.flags:
        return 0.0
    from ..world.environment import day_number
    return min(1.0, day_number(world.clock.tick) / 14.0)   # к ~2 неделям — пик угрозы


def escalated_gold(base_gp: int, threat: float) -> int:
    """Награда контракта растёт с угрозой (до +80% при пике) — город платит за нарастающую опасность."""
    return int(round(base_gp * (1.0 + threat * 0.8)))


def threat_label(threat: float) -> str:
    return ("спокойно" if threat < 0.2 else "тревожно" if threat < 0.5
            else "опасно" if threat < 0.8 else "критично")


def contract_standing(quest) -> float:
    """Прирост стояния гильдии за выполненный контракт/задание (0 — не контракт)."""
    if getattr(quest, "kind", "") not in ("board", "guild", "side", "emergent"):
        return 0.0
    return min(0.18, 0.05 + (getattr(quest.rewards, "xp", 0) or 0) / 2500)


def contract_id(site_key: str) -> str:
    return f"quest:guild_{site_key}"


def register_guild_contracts(world, quest_system) -> None:
    """Контракты гильдии на региональные угрозы — not_offered; активируются взятием (take_contract)."""
    from .region import REGION_SITES
    for sk, sp in REGION_SITES.items():
        place = sp["place"]
        danger = sp.get("danger", "средняя")
        qid = contract_id(sk)
        if qid in world.quests:
            continue
        reward = Rewards(currency={"gp": _DANGER_GOLD.get(danger, 80)},
                         xp=_DANGER_XP.get(danger, 200))   # стояние гильдии даёт complete-хук (не reward)
        q = Quest(
            quest_id=qid, kind="guild", title=f"Контракт: {sp['label']}", giver_ref=GUILD_DESK,
            state="not_offered",
            stages=[
                Stage("do", f"зачистить угрозу — «{sp['label']}»",
                      completion_conditions=[Predicate("Flag", [f"cleared:{place}"])],
                      on_complete=[{"effect": "complete"}]),     # зачистил → контракт выполнен (без возврата)
            ],
            current_stages=[], rewards=reward, framing=sp.get("contents", sp["label"]),
            world_bindings=[GUILD_DESK, place],
            provenance=Provenance(source="authored", generator="guild@1.0"))
        q.req_kind = "guild_contract"
        q.req_ref = place
        q.req_place = place
        q.site_key = sk
        q.danger = danger
        quest_system.register(q)
