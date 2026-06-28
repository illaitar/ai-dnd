"""Прогон гибридной utility-модели NPC по 100 ситуациям (+ контрастные пары).

Каждый сценарий = state (профессия/черты/нужды/настроение/отношения) + стимул + контекст.
Проверяем, что вероятностный арбитр МАРШРУТИЗИРУЕТ в правдоподобную способность (выбранная
входит в ожидаемый набор / семейство), а не выдумывает. Контрастные пары (8a/8b, 78a/78b,
70a/70b, 89a/89b, 100a/100b) доказывают, что одно событие → разное поведение от ЧЕРТ.
Отдельно — тесты вероятностного выбора (вариативность + смещение к лучшему).
"""

from __future__ import annotations

import random

import pytest

from aidnd.npc import Context, Stimulus, choose, distribution, make_state


def R(affinity=0.0, trust=0.0, fear=0.0, debt=0):
    return {"affinity": affinity, "trust": trust, "fear": fear, "debt": debt}


def mk(role="простолюдин", faction="", traits=None, needs=None, mood=None,
       rel=None, agenda=None, wallet=20):
    s = make_state(role=role, faction=faction, seed=0)
    if traits:
        s.traits.update(traits)
    if needs:
        s.needs.update(needs)
    if mood:
        s.mood |= set(mood)
    if rel:
        s.relations.update(rel)
    if agenda:
        s.agenda = list(agenda)
    s.wallet = wallet
    return s


def cx(kind, *, src="", tgt="", data=None, time=1200, danger=0.0, allies=0, here=None):
    return Context(Stimulus(kind, source=src, target=tgt, data=data or {}),
                   time_hhmm=time, danger=danger, allies_near=allies, here=here or [])


def SC(sid, desc, state, ctx, *, expect=None, expect_fam=None, forbid=None, seed=7):
    return {"id": str(sid), "desc": desc, "state": state, "ctx": ctx,
            "expect": set(expect) if expect else None,
            "expect_fam": set(expect_fam) if expect_fam else None,
            "forbid": set(forbid) if forbid else None, "seed": seed}


P = "Игрок"

SCENARIOS = [
    # ── А. Распорядок и быт ──
    SC(1, "кузнец на рассвете→работа", mk("кузнец", needs={"purpose": .5, "hunger": .2, "fatigue": .1}),
       cx("tick", time=600), expect={"routine_work"}),
    SC(2, "трактирщица полдень→дела", mk("трактирщик", needs={"purpose": .5, "hunger": .15}),
       cx("tick", time=1200), expect={"routine_work", "eat"}),
    SC(3, "лавочник сумерки→спать", mk("лавочник", needs={"fatigue": .6, "social": .15}),
       cx("tick", time=2130), expect={"routine_sleep"}),
    SC(4, "фермер утро→работа", mk("фермер", needs={"purpose": .5}), cx("tick", time=700),
       expect={"routine_work"}),
    SC(5, "жрец утро→служба", mk("жрец", needs={"purpose": .5}), cx("tick", time=800),
       expect={"routine_work"}),
    SC(6, "пьянчуга вечер→кутёж", mk("простолюдин", traits={"sociability": .7}, needs={"social": .7},
       mood={"drunk"}), cx("tick", time=1900), expect={"carouse"}),
    SC("6b", "пьянчуга ночь→спать", mk("простолюдин", needs={"fatigue": .8, "social": .1}, mood={"drunk"}),
       cx("tick", time=2330), expect={"routine_sleep"}),
    SC(7, "стражник смена→обход", mk("стражник", needs={"purpose": .5}), cx("tick", time=1000),
       expect={"routine_work"}),

    # ── Б. Восприятие и реакция ──
    SC("8a", "крик: храбрый стражник→помощь", mk("стражник", traits={"bravery": .85, "loyalty": .7}),
       cx("scream", danger=.35), expect={"approach_help"}),
    SC("8b", "крик: трусоватая торговка→бегство", mk("торговец", traits={"bravery": .15}),
       cx("scream", danger=.45), expect={"flee"}, forbid={"approach_help"}),
    SC(9, "дым: кузнец→тушить/тревога", mk("кузнец", traits={"bravery": .6}),
       cx("fire", danger=.3), expect={"approach_help", "raise_alarm"}),
    SC(10, "кража у прилавка→окрик/стража", mk("лавочник"), cx("theft_seen", src="вор", danger=.1),
       expect={"approach_help", "raise_alarm", "report_crime"}),
    SC(11, "драка: прохожий→обойти/звать/влезть", mk("простолюдин", traits={"bravery": .4}),
       cx("brawl", danger=.3), expect={"raise_alarm", "take_cover", "approach_help"}),
    SC(12, "ливень: жрец→под крышу", mk("жрец"), cx("rain"), expect={"seek_shelter"}),
    SC(13, "набат: горожанин→по домам", mk("простолюдин", traits={"bravery": .3, "loyalty": .4},
       needs={"safety": .3}), cx("attack_on_town", danger=.6), expect={"take_cover", "flee", "raise_alarm"}),
    SC(14, "нищий видит богача→клянчит", mk("нищий", needs={"wealth": .7}), cx("see_rich", src="чужак"),
       expect={"solicit_alms"}),
    SC(15, "стражник узнал розыск→задержать", mk("стражник", traits={"bravery": .7}),
       cx("see_wanted", src="беглец"), expect={"apprehend"}),

    # ── В. Движение и пространство ──
    SC(16, "«идём со мной»→следует", mk("простолюдин", needs={"purpose": .1}, rel={P: R(affinity=.5, trust=.4)}),
       cx("asked_follow", src=P), expect={"follow"}),
    SC(17, "торговец утро→склад", mk("торговец", needs={"wealth": .5}), cx("tick", time=800),
       expect={"restock", "routine_work"}),
    SC(18, "раненый→к храму(лечение)", mk("простолюдин", needs={"safety": .6}),
       cx("wounded", data={"drive": "safety"}), expect={"relocate"}),
    SC(19, "избегает переулка→обход", mk("простолюдин", needs={"safety": .5}),
       cx("reroute", data={"drive": "safety"}), expect={"relocate"}),
    SC(20, "контрабандист ведёт тропой", mk("разбойник", traits={"greed": .6}),
       cx("asked_guide", src=P, data={"pay": .7, "risk": .4}), expect={"lead_guide"}),
    SC(21, "спешащий отказывает провожать", mk("простолюдин", needs={"purpose": .8}),
       cx("asked_follow", src=P), expect={"decline_request"}),
    SC(22, "дети разбегаются от стражника", mk("простолюдин", traits={"bravery": .3}),
       cx("startle", danger=.25), expect={"flee"}),

    # ── Г. Диалог: просьбы игрока ──
    SC(23, "спросил дорогу→объясняет", mk("простолюдин", rel={P: R(trust=.3)}),
       cx("asked_directions", src=P, data={"knows": True}), expect={"inform"}),
    SC(24, "снять комнату→ночлег", mk("трактирщик"), cx("asked_lodging", src=P), expect={"provide_lodging"}),
    SC(25, "торг за цену→уступка(бросок)", mk("торговец", traits={"greed": .5}), cx("asked_buy", src=P),
       expect={"sell"}),
    SC(26, "заказ меча→возьмёт", mk("кузнец", needs={"purpose": .3}), cx("asked_commission", src=P),
       expect={"provide_commission"}),
    SC(27, "перевязать рану→услуга", mk("лекарь"), cx("asked_heal", src=P), expect={"provide_heal"}),
    SC(28, "передать весточку→обещает", mk("простолюдин", rel={P: R(affinity=.4)}, needs={"purpose": .2}),
       cx("asked_errand", src=P), expect={"promise"}),
    SC(29, "дарит подарок→благодарность", mk("простолюдин", rel={P: R(affinity=.3)}),
       cx("offered_gift", src=P), expect={"thank_gift"}),
    SC(30, "научить ремеслу→при доверии", mk("кузнец", rel={P: R(trust=.6)}), cx("asked_teach", src=P),
       expect={"teach"}),
    SC("30b", "научить: чужак без доверия→нет", mk("кузнец", rel={P: R(trust=.1)}), cx("asked_teach", src=P),
       forbid={"teach"}),
    SC(31, "предлагают наёмничество→взвешивает", mk("наёмник", traits={"greed": .6, "bravery": .6}),
       cx("asked_hire", src=P, data={"pay": .7, "risk": .4}), expect={"guide_hire"}),
    SC(32, "опознать амулет→если знает", mk("маг"), cx("asked_appraise", src=P), expect={"appraise"}),

    # ── Д. Знание и информация ──
    SC(33, "кузнец про адамантин→рассказ", mk("кузнец", rel={P: R(trust=.3)}),
       cx("asked_lore", src=P, data={"knows": True}), expect={"inform"}),
    SC(34, "простолюдин про тролля→не знает", mk("простолюдин"),
       cx("asked_lore", src=P, data={"knows": False}), expect={"refuse_unknown"}),
    SC(35, "слухи→делится по доверию", mk("трактирщик", traits={"sociability": .75}, rel={P: R(trust=.5)}),
       cx("asked_rumor", src=P, data={"knows": True}), expect={"inform"}),
    SC(36, "игрок рассказал о гоблинах→запоминает", mk("простолюдин", traits={"curiosity": .6}),
       cx("player_tells", src=P), expect={"acknowledge"}),
    SC(37, "покупает у осведомителя сведения", mk("осведомитель", traits={"greed": .6}, rel={P: R(trust=.3)}),
       cx("asked_rumor", src=P, data={"knows": True}), expect={"inform"}),
    SC(38, "мнение о горожанине→по графу", mk("простолюдин"), cx("asked_opinion", src=P, tgt="Сосед"),
       expect={"opine"}),
    SC(39, "учёный про герб→по домену", mk("мудрец"), cx("asked_faction_symbol", src=P, data={"knows": True}),
       expect={"inform"}),

    # ── Е. Торговля ──
    SC(40, "оценивает добычу→цена", mk("торговец", traits={"greed": .6}),
       cx("offered_for_sale", src=P, data={"stolen": False}), expect={"buy_loot"}),
    SC(41, "отказ от краденого", mk("торговец", traits={"lawful": .6, "greed": .4}),
       cx("offered_for_sale", src=P, data={"stolen": True}), expect={"refuse_stolen"}),
    SC(42, "кончился товар→поднимает цену", mk("торговец", traits={"greed": .6}), cx("supply_cut"),
       expect={"raise_price"}),
    SC(43, "руда встала→цены+жалоба", mk("кузнец", traits={"greed": .5}), cx("supply_cut"),
       expect={"raise_price"}),
    SC(44, "конкуренты сбивают цены", mk("лавочник", traits={"greed": .6}),
       cx("asked_buy", src=P, data={"rival": True}), expect={"sell"}),
    SC(45, "постоянному скидка/чужаку наценка", mk("торговец"), cx("asked_buy", src=P), expect={"sell"}),
    SC(46, "отказ дурной репутации", mk("трактирщик", traits={"pride": .6}),
       cx("asked_lodging", src=P, data={"bad_rep": True}), expect={"refuse_reputation"}),
    SC(47, "залог вперёд за дорогой заказ", mk("кузнец", needs={"purpose": .3}, rel={P: R(trust=.1)}),
       cx("asked_commission", src=P, data={"costly": True}), expect={"provide_commission"}),

    # ── Ж. Ремесло и услуги ──
    SC(48, "занят→зайди позже", mk("кузнец", needs={"purpose": .7}), cx("asked_commission", src=P),
       expect={"defer_busy"}),
    SC(49, "алхимик варит зелье", mk("алхимик"), cx("asked_brew", src=P), expect={"brew_potion"}),
    SC(50, "ночлег: ключ+комната", mk("трактирщик"), cx("asked_lodging", src=P), expect={"provide_lodging"}),
    SC(51, "лекарь лечит болезнь", mk("лекарь"), cx("asked_heal", src=P), expect={"provide_heal"}),
    SC(52, "писарь грамоту", mk("писарь"), cx("asked_scribe", src=P), expect={"scribe"}),
    SC(53, "проводник с караваном→торг риск", mk("наёмник", traits={"greed": .6, "bravery": .6}),
       cx("asked_hire", src=P, data={"pay": .7, "risk": .5}), expect={"guide_hire"}),

    # ── З. Социальные связи и мнения ──
    SC(54, "два NPC сплетничают", mk("трактирщик", traits={"sociability": .75}),
       cx("meet_npc", src="Сосед", data={"juicy": .6}), expect={"gossip"}),
    SC(55, "первое впечатление о новичке", mk("простолюдин"), cx("meet_npc", src=P, data={"juicy": .1}),
       expect={"gossip", "greet"}),
    SC(56, "услышал плохое→злословит дальше", mk("простолюдин", traits={"sociability": .6}),
       cx("meet_npc", src="Сосед", data={"juicy": .7}), expect={"gossip"}),
    SC(57, "заступается за друга", mk("простолюдин", traits={"loyalty": .7, "bravery": .6},
       rel={"Обидчик": R(affinity=-.3)}), cx("ally_threatened", src="Обидчик"), expect={"defend"}),
    SC(58, "соседи зовут на праздник", mk("простолюдин", traits={"sociability": .6}, needs={"social": .6}),
       cx("festival"), expect={"carouse"}),
    SC(59, "завидует успешному коллеге", mk("торговец", traits={"pride": .6}, rel={"Коллега": R(affinity=-.2)}),
       cx("rival_present", tgt="Коллега"), expect={"threaten"}),
    SC(60, "сваха сводит двоих", mk("сваха", traits={"sociability": .85}), cx("matchmake", src=P),
       expect={"persuade"}),
    SC(61, "позорит должника на площади", mk("торговец", traits={"pride": .6}),
       cx("debtor_public", tgt="Должник"), expect={"threaten"}),

    # ── И. Эмоции, нужды, характер ──
    SC(62, "усталый→спать/ворчит", mk("простолюдин", needs={"fatigue": .7}), cx("tick", time=2200),
       expect={"routine_sleep"}),
    SC(63, "голодный→перекусить", mk("простолюдин", needs={"hunger": .8}), cx("tick", time=1300),
       expect={"eat"}),
    SC(64, "напуганный прячется/бежит", mk("простолюдин", traits={"bravery": .2}, mood={"afraid"}),
       cx("startle", danger=.4), expect={"flee"}),
    SC(65, "жадный хватает выгоду во вред", mk("торговец", traits={"greed": .85, "lawful": .2}),
       cx("stolen_goods_offered", src=P, data={"stolen": True}), expect={"fence_goods"}),
    SC(66, "гордый отвергает подачку", mk("простолюдин", traits={"pride": .8}),
       cx("offered_gift", src=P, data={"charity": True}), expect={"refuse_charity"}),
    SC(67, "любопытный сам расспрашивает", mk("мудрец", traits={"curiosity": .85, "sociability": .55}),
       cx("meet_npc", src=P, data={"juicy": .2}), expect={"gossip", "greet"}),
    SC(68, "скорбящий замкнут", mk("простолюдин", mood={"grieving"}), cx("meet_npc", src=P),
       expect={"mourn_withdraw"}),
    SC(69, "трус-наёмник бежит при проигрыше", mk("наёмник", traits={"bravery": .3}),
       cx("attacked_in_combat", src="Враг", data={"losing": True, "threat": .8}, danger=.5),
       expect={"surrender", "flee"}, forbid={"attack"}),

    # ── К. Доверие, ложь, секреты ──
    SC("70a", "секрет: высокое доверие→раскрывает", mk("простолюдин", rel={P: R(trust=.9)}),
       cx("asked_secret", src=P, data={"sensitive": True}), expect={"reveal_secret"}),
    SC("70b", "секрет: низкое доверие→молчит", mk("простолюдин", rel={P: R(trust=.15)}),
       cx("asked_secret", src=P, data={"sensitive": True}), expect={"withhold_secret"}, forbid={"reveal_secret"}),
    SC(71, "лжёт когда правда против интересов", mk("осведомитель", traits={"honesty": .2}),
       cx("asked_lore", src=P, data={"knows": True, "interest": .9}), expect={"deceive"}),
    SC(72, "подкупленный→ложные показания", mk("простолюдин", traits={"honesty": .3}),
       cx("testimony", src="Стража", data={"interest": .8}), expect={"deceive"}),
    SC(73, "шпион лжёт под обвинением", mk("осведомитель", traits={"honesty": .2}),
       cx("accused", src=P, data={"interest": .8}), expect={"deceive", "threaten"}),
    SC(74, "доверяет секрет, просит молчать", mk("простолюдин", rel={P: R(trust=.85)}),
       cx("asked_secret", src=P, data={"sensitive": True}), expect={"reveal_secret"}),
    SC(75, "проверяет поручением до доверия", mk("простолюдин", rel={P: R(trust=.3)}),
       cx("faction_order", data={"delegate": True}), expect={"request_task"}),
    SC(76, "разоблачён→оправдывается/огрызается", mk("осведомитель", traits={"honesty": .3, "pride": .6}),
       cx("accused", src=P, data={"interest": .6}), expect={"deceive", "threaten"}),
    SC(77, "шантажирует чужим секретом", mk("осведомитель", traits={"greed": .6}),
       cx("blackmail_target", tgt="Жертва"), expect={"threaten"}),

    # ── Л. Конфликт, угроза, бой ──
    SC("78a", "угроза: трус уступает", mk("лавочник", traits={"pride": .2, "bravery": .2, "greed": .6}),
       cx("threatened", src="Бандит", data={"threat": .8, "demand_value": .2}, allies=0),
       expect={"yield_demand", "raise_alarm"}, forbid={"attack"}),
    SC("78b", "угроза: гордый стражник дерётся", mk("стражник", traits={"pride": .8, "bravery": .85}),
       cx("threatened", src="Бандит", data={"threat": .5, "my_strength": .8}),
       expect={"attack", "raise_alarm"}, forbid={"yield_demand", "surrender"}),
    SC(79, "Красные плащи вымогают", mk("redbrand", faction="faction:redbrands", traits={"greed": .7}),
       cx("tick", data={"victim": "Лавочник"}, time=1400, danger=.1), expect={"extort"}),
    SC(80, "защищает территорию/семью", mk("простолюдин", traits={"loyalty": .75, "bravery": .6}),
       cx("ally_threatened", src="Чужак"), expect={"defend"}),
    SC(81, "раненый отступает/сдаётся", mk("наёмник", traits={"bravery": .4}),
       cx("attacked_in_combat", src="Враг", data={"losing": True, "threat": .7}, danger=.5),
       expect={"surrender", "flee"}),
    SC(82, "патруль вступается за горожанина", mk("стражник", traits={"bravery": .75, "lawful": .8}),
       cx("theft_seen", src="Бандит", danger=.2),
       expect={"apprehend", "defend", "approach_help", "report_crime"}),
    SC(83, "мстит за обиду", mk("простолюдин", traits={"bravery": .6, "pride": .6},
       rel={"Обидчик": R(affinity=-.5)}), cx("insulted", src="Обидчик", data={"my_strength": .6, "threat": .4}),
       expect={"threaten", "attack"}),
    SC(84, "загнанный сдаётся за выкуп", mk("наёмник", traits={"bravery": .4, "pride": .3}),
       cx("cornered", src="Враг", data={}), expect={"surrender"}),

    # ── М. Преступление и закон ──
    SC(85, "пойман на краже→жертва реагирует", mk("простолюдин", traits={"lawful": .6}),
       cx("theft_seen", src=P, danger=.05), expect={"raise_alarm", "report_crime", "approach_help"}),
    SC(86, "зовёт стражу с приметами", mk("простолюдин", traits={"lawful": .7}),
       cx("witnessed_crime", src="Вор", data={"retaliation": .1}), expect={"report_crime"}),
    SC(87, "дознаватель допрашивает/улики", mk("дознаватель"), cx("case"), expect={"investigate"}),
    SC(88, "укрывает беглеца за плату", mk("простолюдин", traits={"lawful": .2, "greed": .5},
       rel={P: R(affinity=.5)}), cx("asked_to_hide", src=P, data={"bribe": .8}), expect={"conceal_fugitive"}),
    SC("89a", "свидетель даёт показания", mk("простолюдин", traits={"lawful": .6}),
       cx("asked_testify", data={"retaliation": .05}), expect={"testify"}),
    SC("89b", "свидетель боится мести→молчит", mk("простолюдин", traits={"lawful": .5}),
       cx("asked_testify", data={"retaliation": .9}), forbid={"testify"}),
    SC(90, "скупщик берёт горячий товар", mk("осведомитель", traits={"greed": .7, "lawful": .15}),
       cx("stolen_goods_offered", src=P, data={"stolen": True}), expect={"fence_goods"}),

    # ── Н. Фракции и политика ──
    SC(91, "вербовщик гильдии зовёт", mk("глава", traits={"ambition": .7, "sociability": .6}),
       cx("recruit_target", src=P), expect={"recruit"}),
    SC(92, "агент Арфистов прощупывает", mk("осведомитель", traits={"curiosity": .7, "ambition": .5}),
       cx("recruit_target", src=P), expect={"recruit"}),
    SC(93, "враждебная фракция→холоден/угроза", mk("стражник", traits={"lawful": .7},
       rel={P: R(affinity=-.3)}), cx("rival_present", tgt=P), expect={"threaten"}),
    SC(94, "глава даёт подручному задание", mk("глава", traits={"ambition": .8}),
       cx("faction_order", data={"delegate": True, "important": True}),
       expect={"request_task", "advance_agenda"}),
    SC(95, "доносит фракции об игроке", mk("осведомитель", traits={"ambition": .6}, agenda=["донести"]),
       cx("tick", data={"important": True}, time=1500), expect={"advance_agenda"}),

    # ── О. Цели, проактивность, память, мораль ──
    SC(96, "важный NPC ведёт тайную цель", mk("маг", traits={"ambition": .8}, agenda=["шаг1", "шаг2"]),
       cx("tick", time=1100), expect={"advance_agenda"}),
    SC(97, "сам разыскивает игрока со сделкой", mk("торговец", traits={"ambition": .6, "greed": .6}),
       cx("opportunity", src=P), expect={"seek_out"}),
    SC(98, "помнит долг→напоминает", mk("торговец", traits={"greed": .6}), cx("debtor_present", tgt=P),
       expect={"collect_debt"}),
    SC(99, "не сдал заказ→извиняется/залог", mk("кузнец", traits={"honesty": .6}),
       cx("commission_overdue", src=P), expect={"apologize_refund"}),
    SC("100a", "мораль: жадный доносит на соседа", mk("простолюдин", traits={"greed": .8, "loyalty": .2,
       "lawful": .6}, rel={"Сосед": R(affinity=.1)}),
       cx("moral_choice_report", tgt="Сосед", data={"reward": .9, "retaliation": .2}),
       expect={"report_neighbor"}),
    SC("100b", "мораль: верный молчит из солидарности", mk("простолюдин", traits={"greed": .2, "loyalty": .8},
       rel={"Сосед": R(affinity=.7)}),
       cx("moral_choice_report", tgt="Сосед", data={"reward": .4, "retaliation": .5}),
       expect={"stay_silent"}, forbid={"report_neighbor"}),
]


@pytest.mark.parametrize("s", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
def test_scenario_routes(s):
    cap, top = choose(s["state"], s["ctx"], random.Random(s["seed"]))
    assert cap is not None, f"#{s['id']} «{s['desc']}»: арбитр ничего не выбрал"
    short = {c.key for c, _ in top}
    if s["expect"]:
        assert cap.key in s["expect"], (
            f"#{s['id']} «{s['desc']}»: выбрал {cap.key}; ждали {s['expect']}; shortlist={short}")
    if s["expect_fam"]:
        assert cap.family in s["expect_fam"], (
            f"#{s['id']} «{s['desc']}»: семейство {cap.family} ({cap.key}) не в {s['expect_fam']}")
    if s["forbid"]:
        assert cap.key not in s["forbid"], f"#{s['id']} «{s['desc']}»: выбрал запрещённое {cap.key}"


def test_every_scenario_picks_something():
    """Ни один из 100 сценариев не оставляет NPC без действия (нет «дыр» покрытия)."""
    empty = [s["id"] for s in SCENARIOS if choose(s["state"], s["ctx"], random.Random(1))[0] is None]
    assert not empty, f"сценарии без выбора: {empty}"


def test_choice_is_probabilistic_not_argmax():
    """Тот же NPC в той же ситуации НЕ всегда повторяет действие (есть стохастика top-k)."""
    s = mk("лавочник", traits={"pride": .3, "bravery": .3, "greed": .5}, rel={"Бандит": R(fear=.5)})
    ctx = cx("threatened", src="Бандит", data={"threat": .7, "demand_value": .2})
    picks = {choose(s, ctx, random.Random(seed))[0].key for seed in range(200)}
    assert len(picks) >= 2, f"выбор детерминирован, вариативности нет: {picks}"


def test_probability_biased_to_higher_utility():
    """Среди правдоподобных лучший вариант выбирается ЧАЩЕ (взвешенность, а не равновероятность)."""
    s = mk("простолюдин", traits={"lawful": .7, "bravery": .45})
    ctx = cx("theft_seen", src="вор", danger=.1)
    dist = dict(distribution(s, ctx))
    best_key = max(dist, key=dist.get)
    counts = {}
    for seed in range(600):
        k = choose(s, ctx, random.Random(seed))[0].key
        counts[k] = counts.get(k, 0) + 1
    top_key = max(counts, key=counts.get)
    assert top_key == best_key, f"чаще всего выбран {top_key}, а лучший по полезности {best_key}: {counts}"


def test_traits_change_behavior_same_stimulus():
    """Одно событие (угроза) → разное поведение от ЧЕРТ: трус уступает, храбрец дерётся."""
    timid = mk("лавочник", traits={"bravery": .15, "pride": .2})
    bold = mk("стражник", traits={"bravery": .9, "pride": .85})
    ctx = cx("threatened", src="Бандит", data={"threat": .6, "my_strength": .7})
    timid_pick = choose(timid, ctx, random.Random(3))[0].key
    bold_pick = choose(bold, ctx, random.Random(3))[0].key
    assert timid_pick != "attack"
    assert bold_pick != "yield_demand"
