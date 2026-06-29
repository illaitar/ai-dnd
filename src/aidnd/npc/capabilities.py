"""Способности NPC — замкнутый набор (9 семейств) под единым контрактом.

Каждая Cap = {available, score, [effect], [voice]}. «Гейт» свёрнут в available()
(физически/контекстно возможно?) и в пол полезности (нежелательное набирает мало).
score(s, ctx) — слагаемые utility из состояния: нужды × давление, черты × контекст,
отношения, обязательства, выгода − риск. Арбитр сравнивает баллы и выбирает (см. arbiter).

100 ситуаций ложатся на эти ~60 команд: новая ситуация — это параметр/слагаемое, а не
новый код-путь. Поля ctx.d(...) — входы LLM-суждения (угроза/интерес/сочность/месть);
офлайн передаются прямо.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

FAMILIES = ("move", "body", "trade", "serve", "demand", "speak", "fight", "law", "pursue")


@dataclass
class Effects:
    deltas: dict | None = None      # дельты состояния (декларативно)
    world: list | None = None       # события мира (декларативно): ("alarm",), ("attack", tgt)
    narration: str = ""             # подсказка озвучки / шаблон


@dataclass
class Cap:
    key: str
    family: str
    available: Callable             # (s, ctx) -> bool
    score: Callable                 # (s, ctx) -> float
    voice: str = ""                 # шаблон озвучки (точка LLM №1)


# --- помощники чтения контекста/состояния ------------------------------------
def _hour(c) -> int:
    return (c.time_hhmm or 1200) // 100


def _night(c) -> bool:
    h = _hour(c)
    return h >= 21 or h < 6


def _morning(c) -> bool:
    return 6 <= _hour(c) < 12


def _midday(c) -> bool:
    return 11 <= _hour(c) <= 14


def _evening(c) -> bool:
    return 18 <= _hour(c) < 24


def _sr(s, c) -> dict:               # отношение к источнику стимула
    return s.rel(c.stim.source or c.stim.target)


def _tr(s, c) -> dict:               # отношение к цели стимула
    return s.rel(c.stim.target or c.stim.source)


# --- набор способностей ------------------------------------------------------
CAPABILITIES: list[Cap] = [

    # ─ ДВИЖЕНИЕ ─ (быт, бегство, сопровождение, маршрут)
    Cap("flee", "move",
        lambda s, c: c.danger > 0.15 or c.k() == "attack_on_town",
        lambda s, c: c.danger * (1.5 - s.t("bravery")) + (0.7 if s.has_mood("afraid") else 0)),
    Cap("approach_help", "move",
        lambda s, c: c.k() in {"scream", "fire", "brawl", "theft_seen"},
        lambda s, c: s.t("bravery") * 1.0 + 0.45 + s.t("loyalty") * 0.3
        - c.danger * (1.2 - s.t("bravery")) * 1.1),
    Cap("follow", "move",
        lambda s, c: c.k() == "asked_follow",
        lambda s, c: 0.55 + _sr(s, c)["affinity"] * 0.6 + _sr(s, c)["trust"] * 0.5 - s.n("purpose") * 0.9),
    Cap("decline_request", "move",
        lambda s, c: c.k() in {"asked_follow", "asked_errand", "asked_hire", "asked_guide"},
        lambda s, c: s.n("purpose") * 1.1 + (1 - s.t("sociability")) * 0.3 - _sr(s, c)["affinity"] * 0.4),
    Cap("lead_guide", "move",
        lambda s, c: c.k() == "asked_guide",
        lambda s, c: 0.4 + s.t("greed") * c.d("pay", 0.5) - c.d("risk", 0.3) * (1 - s.t("bravery"))),
    Cap("routine_work", "move",
        lambda s, c: c.k() == "tick" and 6 <= _hour(c) < 19,
        lambda s, c: 0.5 + s.n("purpose") * 0.7 - s.n("fatigue") * 0.5 - s.n("hunger") * 0.5),
    Cap("routine_sleep", "move",
        lambda s, c: c.k() == "tick",
        lambda s, c: s.n("fatigue") * 1.0 * (1.4 if _night(c) else 0.3)),
    Cap("seek_shelter", "move",
        lambda s, c: c.k() in {"rain", "storm"},
        lambda s, c: 0.6 + (0.3 if s.role in {"фермер", "крестьянин", "жрец"} else 0)),
    Cap("relocate", "move",
        lambda s, c: c.k() in {"wounded", "reroute", "seek_service"},
        lambda s, c: 0.5 + s.n(c.d("drive", "safety")) * 0.9),

    # ─ ТЕЛО ─ (есть/пить)
    Cap("eat", "body",
        lambda s, c: c.k() in {"tick", "hungry"},
        lambda s, c: s.n("hunger") * 1.3 + (0.3 if _midday(c) else 0)),
    Cap("carouse", "body",
        lambda s, c: (c.k() == "festival") or (c.k() == "tick" and _evening(c)),
        lambda s, c: s.n("social") * s.t("sociability") * 1.0 + (0.6 if c.k() == "festival" else 0)
        + (0.5 if s.has_mood("drunk") else 0)),

    # ─ ТОРГОВЛЯ ─
    Cap("sell", "trade",
        lambda s, c: c.k() == "asked_buy",
        lambda s, c: s.t("greed") * 0.8 + 0.5 + s.t("sociability") * 0.2
        - (0.9 * (1 - s.t("greed")) if c.d("bad_rep") else 0)),
    Cap("buy_loot", "trade",
        lambda s, c: c.k() == "offered_for_sale",
        lambda s, c: s.t("greed") * 0.9 + 0.45 - (s.t("lawful") if c.d("stolen") else 0)),
    Cap("refuse_stolen", "trade",
        lambda s, c: c.k() in {"offered_for_sale", "stolen_goods_offered"} and bool(c.d("stolen")),
        lambda s, c: s.t("lawful") * 1.2 + s.t("honesty") * 0.4 + 0.3 - s.t("greed") * 0.3),
    Cap("appraise", "trade",
        lambda s, c: c.k() == "asked_appraise",
        lambda s, c: 0.7 + s.t("sociability") * 0.2 + s.t("greed") * 0.2),
    Cap("restock", "trade",
        lambda s, c: c.k() == "tick" and _morning(c) and s.role in {"торговец", "merchant", "лавочник"},
        lambda s, c: 0.45 + s.n("wealth") * 0.5),
    Cap("raise_price", "trade",
        lambda s, c: c.k() == "supply_cut",
        lambda s, c: s.t("greed") * 0.9 + 0.5),
    Cap("refuse_reputation", "trade",
        lambda s, c: c.k() in {"asked_buy", "asked_lodging", "asked_commission"} and bool(c.d("bad_rep")),
        lambda s, c: (1 - s.t("greed")) * 0.5 + s.t("pride") * 0.5 + s.t("lawful") * 0.3 + 0.3),

    # ─ УСЛУГИ ─ (выдают КОНКРЕТНЫЙ объект/эффект)
    Cap("provide_lodging", "serve",
        lambda s, c: c.k() == "asked_lodging" and s.can_serve("lodging") and not c.d("bad_rep"),
        lambda s, c: s.t("greed") * 0.7 + 0.6),
    Cap("provide_commission", "serve",
        lambda s, c: c.k() == "asked_commission" and s.can_serve("craft") and s.n("purpose") < 0.55,
        lambda s, c: s.t("greed") * 0.7 + 0.55),
    Cap("defer_busy", "serve",
        lambda s, c: c.k() in {"asked_commission", "asked_craft"} and s.can_serve("craft")
        and s.n("purpose") >= 0.55,
        lambda s, c: s.n("purpose") * 1.1 + 0.4),
    Cap("provide_heal", "serve",
        lambda s, c: c.k() == "asked_heal" and s.can_serve("heal"),
        lambda s, c: s.t("loyalty") * 0.5 + s.t("greed") * 0.4 + 0.5),
    Cap("brew_potion", "serve",
        lambda s, c: c.k() == "asked_brew" and s.can_serve("brew"),
        lambda s, c: s.t("greed") * 0.5 + s.t("curiosity") * 0.3 + 0.5),
    Cap("scribe", "serve",
        lambda s, c: c.k() == "asked_scribe" and s.can_serve("scribe"),
        lambda s, c: s.t("greed") * 0.4 + 0.55),
    Cap("guide_hire", "serve",
        lambda s, c: c.k() == "asked_hire" and s.can_serve("guide"),
        lambda s, c: 0.4 + s.t("greed") * c.d("pay", 0.6) - c.d("risk", 0.4) * (1 - s.t("bravery")) * 0.8),

    # ─ ТРЕБОВАНИЕ ПЛАТЫ ─
    Cap("extort", "demand",
        lambda s, c: c.k() in {"tick", "extort_round"} and bool(c.d("victim"))
        and (s.role in {"redbrand", "разбойник"} or s.faction == "faction:redbrands"),
        lambda s, c: s.t("greed") * 0.8 + 0.4 - c.danger * (1 - s.t("bravery"))),
    Cap("collect_debt", "demand",
        lambda s, c: c.k() == "debtor_present" or (c.k() == "tick" and bool(c.d("debtor"))),
        lambda s, c: s.t("greed") * 0.7 + 0.5),
    Cap("demand_ransom", "demand",
        lambda s, c: c.k() == "captive_present",
        lambda s, c: s.t("greed") * 0.9 + 0.3),
    Cap("solicit_alms", "demand",
        lambda s, c: c.k() == "see_rich" and s.role == "нищий",
        lambda s, c: s.n("wealth") * 0.8 + (1 - s.t("pride")) * 0.6),

    # ─ РЕЧЬ ─ (информировать/лгать/мнение/сплетня/обещать/угрожать/учить)
    Cap("inform", "speak",
        lambda s, c: c.k() in {"asked_directions", "asked_lore", "asked_rumor", "asked_faction_symbol"}
        and c.d("knows", True),
        lambda s, c: s.t("sociability") * 0.5 + _sr(s, c)["trust"] * 0.6 + 0.45),
    Cap("refuse_unknown", "speak",
        lambda s, c: c.k() in {"asked_lore", "asked_faction_symbol"} and not c.d("knows", True),
        lambda s, c: 0.65),
    Cap("withhold_secret", "speak",
        lambda s, c: c.k() in {"asked_secret", "asked_rumor"} and bool(c.d("sensitive")),
        lambda s, c: (1 - _sr(s, c)["trust"]) * 0.9 + s.t("honesty") * 0.2 + 0.2),
    Cap("reveal_secret", "speak",
        lambda s, c: c.k() == "asked_secret" and bool(c.d("sensitive")),
        lambda s, c: _sr(s, c)["trust"] * 1.2 - 0.2),
    Cap("opine", "speak",
        lambda s, c: c.k() == "asked_opinion",
        lambda s, c: s.t("sociability") * 0.5 + 0.6),
    Cap("deceive", "speak",
        lambda s, c: c.k() in {"asked_lore", "asked_rumor", "asked_opinion", "asked_directions",
                               "testimony", "accused"} and c.d("interest", 0) > 0,
        lambda s, c: (1 - s.t("honesty")) * 0.9 + c.d("interest", 0) * 0.7),
    Cap("gossip", "speak",
        lambda s, c: c.k() == "meet_npc",
        lambda s, c: s.t("sociability") * 0.8 + c.d("juicy", 0.3) * 0.6),
    Cap("promise", "speak",
        lambda s, c: c.k() == "asked_errand",
        lambda s, c: s.t("sociability") * 0.4 + _sr(s, c)["affinity"] * 0.5 + 0.4 - s.n("purpose") * 0.5),
    Cap("request_task", "speak",
        lambda s, c: c.k() == "faction_order" and (s.role == "глава" or bool(c.d("delegate"))),
        lambda s, c: s.t("ambition") * 0.7 + 0.5),
    Cap("threaten", "speak",
        lambda s, c: c.k() in {"insulted", "debtor_public", "rival_present", "blackmail_target", "accused"},
        lambda s, c: (1 - _tr(s, c)["affinity"]) * 0.6 + s.t("pride") * 0.4 - s.t("lawful") * 0.3
        + (0.4 if c.k() == "blackmail_target" else 0)),
    Cap("persuade", "speak",
        lambda s, c: c.k() in {"asked_persuade", "matchmake"},
        lambda s, c: s.t("sociability") * 0.6 + 0.4),
    Cap("teach", "speak",
        lambda s, c: c.k() == "asked_teach",
        lambda s, c: _sr(s, c)["trust"] * 0.7 + s.t("sociability") * 0.3 + 0.2
        - (0.6 if _sr(s, c)["trust"] < 0.2 else 0)),
    Cap("greet", "speak",
        lambda s, c: c.k() in {"meet_npc", "tick"} or c.k().startswith("asked"),
        lambda s, c: 0.25 + s.t("sociability") * 0.2),
    Cap("thank_gift", "speak",
        lambda s, c: c.k() == "offered_gift",
        lambda s, c: 0.6 + _sr(s, c)["affinity"] * 0.4 - (s.t("pride") * 0.9 if c.d("charity") else 0)),
    Cap("refuse_charity", "speak",
        lambda s, c: c.k() == "offered_gift" and bool(c.d("charity")),
        lambda s, c: s.t("pride") * 1.0 + (1 - s.t("greed")) * 0.2),
    Cap("acknowledge", "speak",
        lambda s, c: c.k() == "player_tells",
        lambda s, c: 0.5 + s.t("curiosity") * 0.3),

    # ─ БОЙ / БЕГСТВО ─
    Cap("attack", "fight",
        lambda s, c: c.k() in {"threatened", "attacked_in_combat", "insulted", "defend_self"},
        lambda s, c: s.t("bravery") * (0.6 + c.d("my_strength", 0.5) - c.d("threat", 0.5))
        - _sr(s, c)["fear"] * 0.5 + (s.t("pride") * 0.4 if c.k() == "insulted" else 0)),
    Cap("defend", "fight",
        lambda s, c: c.k() in {"ally_threatened", "attack_on_town", "theft_seen"}
        and (s.t("bravery") > 0.5 or s.t("loyalty") > 0.55 or s.role in {"стражник", "guard", "наёмник"}),
        lambda s, c: s.t("loyalty") * 0.7 + s.t("bravery") * 0.6 + (0.3 if c.k() == "attack_on_town" else 0)),
    Cap("raise_alarm", "fight",
        lambda s, c: c.k() in {"fire", "theft_seen", "threatened", "brawl", "attack_on_town", "see_intruder"},
        lambda s, c: 0.45 + (0.35 if c.allies_near > 0 else 0) + (1 - s.t("bravery")) * 0.4
        + s.t("lawful") * 0.3),
    Cap("surrender", "fight",
        lambda s, c: c.k() == "cornered" or (c.k() == "attacked_in_combat" and bool(c.d("losing"))),
        lambda s, c: (1 - s.t("bravery")) * 0.8 + _sr(s, c)["fear"] * 0.6 + 0.2 - s.t("pride") * 0.4),
    Cap("yield_demand", "fight",
        lambda s, c: c.k() == "threatened",
        lambda s, c: _sr(s, c)["fear"] * 0.6 + c.d("threat", 0.5) * (1 - s.t("pride")) * 0.9
        - c.d("demand_value", 0) * s.t("greed") * 0.4),
    Cap("take_cover", "fight",
        lambda s, c: c.k() in {"attack_on_town", "alarm_bell"},
        lambda s, c: (1 - s.t("bravery")) * 0.8 + s.n("safety") * 0.5 + 0.2),

    # ─ ЗАКОН ─
    Cap("report_crime", "law",
        lambda s, c: c.k() in {"theft_seen", "witnessed_crime"},
        lambda s, c: s.t("lawful") * 0.9 + 0.3 - c.d("retaliation", 0) * 0.5),
    Cap("apprehend", "law",
        lambda s, c: c.k() in {"see_wanted", "theft_seen"} and s.role in {"стражник", "guard"},
        lambda s, c: s.t("lawful") * 0.8 + s.t("bravery") * 0.5 + 0.2),
    Cap("investigate", "law",
        lambda s, c: c.k() == "case" and s.role == "дознаватель",
        lambda s, c: s.t("curiosity") * 0.6 + s.t("lawful") * 0.6 + 0.3),
    Cap("conceal_fugitive", "law",
        lambda s, c: c.k() == "asked_to_hide",
        lambda s, c: s.t("greed") * c.d("bribe", 0.4) + _sr(s, c)["affinity"] * 0.6 - s.t("lawful") * 0.8 + 0.2),
    Cap("fence_goods", "law",
        lambda s, c: c.k() == "stolen_goods_offered"
        and (s.role in {"осведомитель", "скупщик", "вор"} or s.t("lawful") < 0.3),
        lambda s, c: s.t("greed") * 0.9 - s.t("lawful") * 0.5 + 0.2),
    Cap("testify", "law",
        lambda s, c: c.k() == "asked_testify",
        lambda s, c: s.t("lawful") * 0.7 + 0.2 - c.d("retaliation", 0) * 0.8),

    # ─ ЦЕЛИ / ПРОАКТИВНОСТЬ / МОРАЛЬ ─
    Cap("advance_agenda", "pursue",
        lambda s, c: c.k() in {"tick", "faction_order", "meet_npc"} and (bool(s.agenda) or bool(c.d("important"))),
        lambda s, c: s.t("ambition") * 0.8 + 0.4),
    Cap("seek_out", "pursue",
        lambda s, c: c.k() == "opportunity",
        lambda s, c: s.t("ambition") * 0.6 + s.t("greed") * 0.4 + 0.3),
    Cap("recruit", "pursue",
        lambda s, c: c.k() == "recruit_target",
        lambda s, c: s.t("ambition") * 0.7 + s.t("sociability") * 0.4 + 0.3),
    Cap("mourn_withdraw", "pursue",
        lambda s, c: s.has_mood("grieving"),
        lambda s, c: 0.95),
    Cap("apologize_refund", "pursue",
        lambda s, c: c.k() == "commission_overdue",
        lambda s, c: s.t("honesty") * 0.7 + 0.45),
    Cap("report_neighbor", "law",
        lambda s, c: c.k() == "moral_choice_report",
        lambda s, c: s.t("greed") * c.d("reward", 0.5) + s.t("lawful") * 0.5
        - _tr(s, c)["affinity"] * 0.7 - c.d("retaliation", 0) * 0.4),
    Cap("stay_silent", "pursue",
        lambda s, c: c.k() == "moral_choice_report",
        lambda s, c: _tr(s, c)["affinity"] * 0.7 + s.t("loyalty") * 0.5 + c.d("retaliation", 0) * 0.3 + 0.2),
]

BY_KEY: dict[str, Cap] = {c.key: c for c in CAPABILITIES}
