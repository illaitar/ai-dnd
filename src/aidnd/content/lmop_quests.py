"""Квесты LMoP: основной сюжет как авторский DAG + побочки (док 05 §2, §4.1).

Основной сюжет уложен в граф стадий (для вертикального среза — ключевые узлы).
Побочки привязаны к реальным NPC и провенансу предметов.
"""

from __future__ import annotations

from ..gen.provenance import Provenance
from ..gen.quest_gen import Predicate, Quest, QuestSystem, Rewards, Stage


def _main_plot() -> Quest:
    return Quest(
        quest_id="quest:lost_mine", kind="main", title="Затерянный рудник Фэндалина",
        giver_ref="npc:gundren_rockseeker", state="active",
        current_stages=["s1"],
        stages=[
            Stage("s1", "Goblin Arrows: зачистить логово Крэгмо, освободить пленника",
                  completion_conditions=[Predicate("NpcDead", ["npc:klarg"])],
                  on_complete=[{"effect": "set_flag", "flag": "cragmaw_cleared"}],
                  next_stages=["s2"], hooks_revealed=["redbrands"]),
            Stage("s2", "Phandalin: разобраться с Красными плащами (Glasstaff)",
                  completion_conditions=[Predicate("NpcDead", ["npc:iarno_glasstaff"])],
                  on_complete=[{"effect": "set_flag", "flag": "post_redbrand_purge"}],
                  next_stages=["s3"], hooks_revealed=["black_spider"]),
            Stage("s3", "The Spider's Web: добыть карту к Wave Echo Cave",
                  completion_conditions=[Predicate("AnyOf", [
                      Predicate("HasItem", ["pc:hero", "it:gundren_map"]),
                      Predicate("KnowsFact", ["pc:hero", "wave_echo_location"])])],
                  next_stages=["s4"]),
            Stage("s4", "Wave Echo Cave: победить Нежнара, Чёрного Паука",
                  completion_conditions=[Predicate("NpcDead", ["npc:nezznar"])],
                  on_complete=[{"effect": "set_flag", "flag": "lost_mine_won"}]),
        ],
        rewards=Rewards(xp=2000, faction_rep={"faction:lords_alliance": 0.3}),
        world_bindings=["npc:gundren_rockseeker", "npc:klarg", "npc:iarno_glasstaff"],
        provenance=Provenance(source="authored", generator="lmop@1.0"),
    )


def _lionshield_quest() -> Quest:
    return Quest(
        quest_id="quest:lionshield_goods", kind="side", title="Украденный товар",
        giver_ref="npc:linene_graywind", state="not_offered",
        stages=[
            Stage("s1", "вернуть ящики Львинощит Костер",
                  completion_conditions=[Predicate("HasItem", ["pc:hero", "it:lionshield_crate"])],
                  next_stages=["s2"]),
            Stage("s2", "доставить ящики Линен Грейвинд",
                  completion_conditions=[Predicate("ItemInContainer",
                                         ["it:lionshield_crate", "shop:lionshield"])],
                  on_complete=[{"effect": "complete"}]),
        ],
        rewards=Rewards(currency={"gp": 50}, xp=100,
                        faction_rep={"faction:lords_alliance": 0.1}),
        world_bindings=["npc:linene_graywind", "it:lionshield_crate"],
        provenance=Provenance(source="authored", generator="lmop@1.0",
                              satisfied=["giver_has_motive", "objective_reachable"]),
    )


def _wyvern_tor_quest() -> Quest:
    return Quest(
        quest_id="quest:wyvern_tor_orcs", kind="side", title="Беда у Вайверн-Тор",
        giver_ref="npc:harbin_wester", state="not_offered",
        stages=[
            Stage("s1", "разобраться с орками у Вайверн-Тор",
                  completion_conditions=[Predicate("LairCleared", ["place:wyvern_tor"])],
                  on_complete=[{"effect": "complete"}], optional=True),
        ],
        rewards=Rewards(currency={"gp": 100}, xp=200, faction_rep={"faction:phandalin": 0.15}),
        world_bindings=["npc:harbin_wester", "place:wyvern_tor"],
        provenance=Provenance(source="authored", generator="lmop@1.0"),
    )


def _cragmaw_milestone() -> Quest:
    """Скрытая мировая веха: смерть Кларга → флаг cragmaw_cleared (гейтит пейсинг и хук Красных
    плащей в director/orchestrator). Раньше это давала стадия s1 lost_mine — сохраняем механизм
    после замены основного сюжета на генерацию. Невидима в UI/журнале (kind=milestone)."""
    return Quest(
        quest_id="quest:milestone_cragmaw", kind="milestone", title="", giver_ref=None,
        state="active", current_stages=["m1"],
        stages=[Stage("m1", "", completion_conditions=[Predicate("NpcDead", ["npc:klarg"])],
                      on_complete=[{"effect": "set_flag", "flag": "cragmaw_cleared"}], next_stages=[])])


def register_quests(world, quest_system: QuestSystem) -> None:
    # основной сюжет теперь генерируется на старте (gen.campaign), а не lost_mine; здесь — побочки + вехи
    for q in (_lionshield_quest(), _wyvern_tor_quest(), _cragmaw_milestone()):
        quest_system.register(q)
    from .board import register_board_quests
    register_board_quests(world, quest_system)          # простые задания с доски объявлений
    from .guild import register_guild_contracts
    register_guild_contracts(world, quest_system)       # контракты гильдии на региональные угрозы


def classic_main_plot() -> Quest:
    """Авторский LMoP-сюжет — для сценария-«классики» (по запросу)."""
    return _main_plot()
