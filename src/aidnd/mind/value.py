"""Слой ЦЕННОСТИ — сердце эмерджентного решения.

Поведение НЕ скриптуется. Есть ~5 ОБЩИХ членов utility и карта «черта→на что влияет»; любое
действие (move/attack/take/give/say/use/wait) скорится по этим членам относительно ЦЕЛИ
(желаемого исхода), а наблюдаемое поведение (бегство, преследование, засада, кража, запугивание,
торг, подкуп, защита, обход, расспрос, смена цели) — это какой примитив выиграл сейчас.

Общие члены:
  payoff(g)         — ценность достижения цели (× релевантная черта/эмоция)
  realize           — ps_now·payoff − p_caught·cost − moral        (действие РЕАЛИЗУЕТ цель сейчас)
  opportunity       — γ·payoff·proximity_after·ps_after − caught − moral − risk   (ПОЗИЦИОНИРУЕТ)
  p_caught          — ∝ числу свидетелей (третьих лиц)
  cost/moral        — наказание (×lawful) + внутренний моральный тормоз (×honesty)
Терпение γ и риск-толерантность выводятся из черт. Все коэффициенты — в BAL (это и есть то,
что калибруется к спеке-бенчу, а не 50 скриптов).
"""

from __future__ import annotations

from .world import ENEMY_FACTIONS

# ── единственный конфиг коэффициентов (то, что подбирается оптимизатором к спеке) ──
BAL = {
    "gamma_base": 0.55, "gamma_focus": 0.40,          # терпение γ = base + focus·(1−irritability)
    "eff_move": 0.04, "eff_say": 0.01,
    "caught_per_witness": 0.5, "caught_cap": 0.95,    # p_caught растёт со свидетелями
    "transgress": {"attack": 1.0, "take": 0.55, "threat": 0.45},
    "cost_lawbase": 0.4, "cost_lawful": 1.5,          # наказание = transgress·(lawbase + lawful·lawful)
    "moral": 1.0,                                     # внутр. тормоз = transgress·honesty·moral
    "selfrisk": 0.6,                                  # цена проигрыша драки
    "take_alert": 0.15, "take_distracted": 0.78, "take_down": 0.92,  # ps кражи по состоянию цели
    "flee_base": 0.5, "flee_gain": 2.2,
    "idle": 0.05,
    "need_urgency_coin": 0.5,                         # «синица в руках» — бедность ускоряет сделку
    "info_value": 0.6,
}


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def T(state, name: str) -> float:
    return state.config.traits.get(name, 0.5)


def proximity(d: int) -> float:
    return 1.0 / (1.0 + d)                 # 1.0 со-локация, 0.5 рядом, 0.33 через одно


def gamma(state) -> float:
    return BAL["gamma_base"] + BAL["gamma_focus"] * (1.0 - T(state, "irritability"))


def pwin(att, deff) -> float:
    return _clamp(att.power / (att.power + deff.power + 1e-9), 0.02, 0.98)


def hostility(state, me, b) -> float:
    """Насколько b опасен ДЛЯ МЕНЯ [0..1]: явная атака / враждебная фракция / запомненный страх.
    Если b занят атакой ДРУГОГО — прямая угроза мне ниже (он связан)."""
    if b.attacking == me.id:
        return pwin(b, me)
    rel = state.relationships.get(b.id) or {}
    h = float(rel.get("fear", 0.0))
    if b.faction in ENEMY_FACTIONS and b.faction != me.faction:
        h = max(h, pwin(b, me))
    if b.attacking and b.attacking != me.id:
        h *= 0.2                                  # враг занят другим — прямая угроза мне мала (даёт защиту, не бегство)
    return _clamp(h)


def _is_ally(state, b) -> bool:
    rel = state.relationships.get(b.id) or {}
    return rel.get("affinity", 0.0) > 0.2


def witnesses(percept, state, target_id: str) -> int:
    """Третьи лица рядом (не я, не цель, не союзник) — кто может донести/помешать."""
    return sum(1 for b in percept.present
               if b.id != target_id and not _is_ally(state, b))


def _caught(kind: str, n_wit: int) -> float:
    if BAL["transgress"].get(kind, 0.0) <= 0:
        return 0.0
    return min(BAL["caught_cap"], BAL["caught_per_witness"] * n_wit)


def _cost_caught(kind: str, state) -> float:
    tg = BAL["transgress"].get(kind, 0.0)
    return tg * (BAL["cost_lawbase"] + BAL["cost_lawful"] * T(state, "lawful"))


def _cost_moral(kind: str, state) -> float:
    tg = BAL["transgress"].get(kind, 0.0)
    return tg * T(state, "honesty") * BAL["moral"]


def _eff(a) -> float:
    if a.kind == "move":
        return BAL["eff_move"]
    if a.kind == "say":
        return BAL["eff_say"]
    return 0.0


def _risk(a, world, state) -> float:
    """Риск ВОЙТИ в место: базовый + враги/страж там + дурная память. Даёт обход без правила «avoid»."""
    if a.kind != "move":
        return 0.0
    r = world.risk.get(a.to, 0.0)
    me = world.bodies[state.config.id]
    for b in world.present_at(a.to, exclude=(me.id,)):
        r += hostility(state, me, b) * 0.6
    return r


def idle_floor(a) -> float:
    return BAL["idle"] if a.kind in ("wait", "move") else 0.0


def _approach(a, target_place, me, world):
    """proximity(after) для move/wait; None если действие не пространственное приближение."""
    if a.kind == "move":
        return proximity(world.dist(a.to, target_place))
    if a.kind == "wait":
        return proximity(world.dist(me.place, target_place))
    return None


# ── utility(action | goal): один диспетчер по ТИПУ цели (не по сценарию) ──
def utility(a, g, state, world, percept) -> float:
    me = percept.me
    fn = _GOAL.get(g.kind)
    return fn(a, g, state, world, percept, me) if fn else -_eff(a)


def _acq_pay(g, state) -> float:
    return g.value * (0.3 + T(state, "greed"))


def clean_acquire(g, state, world, me) -> float:
    """Ценность «чистого удара» — лучший РЕАЛИЗ при со-локации и БЕЗ свидетелей. К ней приводит
    позиционирование (сблизиться/выждать), дисконтируясь γ. Это убирает «вечное ожидание»:
    выждать = γ·(то, что сделаю в удобный миг) < сделать сейчас, когда миг настал."""
    tb = world.bodies.get(g.target)
    if not tb:
        return 0.0
    pay = _acq_pay(g, state)
    pw = pwin(me, tb)
    subdue = pw * 0.9 * pay - _cost_moral("attack", state) - (1 - pw) * BAL["selfrisk"]
    steal = (BAL["take_distracted"] if tb.attention < 0.4 else BAL["take_alert"]) * pay \
        - _cost_moral("take", state)
    comply = _clamp(pw - 0.1 + 0.3 * T(state, "pride"))
    extort = comply * pay - _cost_moral("threat", state)
    return max(0.0, subdue, steal, extort)


def _u_acquire(a, g, state, world, percept, me) -> float:
    """Завладеть богатством цели. РЕАЛИЗУЮТ (сейчас, с текущими свидетелями): say(threat)=вымогательство,
    take=кража, attack=сбить с ног→добить. ПОЗИЦИОНИРУЮТ (move/wait): γ·clean·reach — приблизиться/выждать
    удобный миг. Бегство/преследование/засада/кража/мугинг — это какой примитив выиграл."""
    tb = world.bodies.get(g.target)
    if not tb or tb.id == me.id:
        return -_eff(a)
    pay = _acq_pay(g, state)
    same = me.place == tb.place
    wit = witnesses(percept, state, g.target)

    if same and a.kind == "say" and a.say == "threat" and a.target == g.target:
        comply = _clamp(pwin(me, tb) - 0.1 + 0.3 * T(state, "pride")) / (1 + 0.8 * wit)
        return comply * pay - _caught("threat", wit) * _cost_caught("threat", state) \
            - _cost_moral("threat", state) - _eff(a)
    if same and a.kind == "take" and a.target == g.target:
        ps = (BAL["take_down"] if tb.down()
              else BAL["take_distracted"] if tb.attention < 0.4 else BAL["take_alert"])
        return ps * pay - _caught("take", wit) * _cost_caught("take", state) - _cost_moral("take", state)
    if same and a.kind == "attack" and a.target == g.target and not tb.down():
        pw = pwin(me, tb)
        return pw * 0.9 * pay - _caught("attack", wit) * _cost_caught("attack", state) \
            - _cost_moral("attack", state) - (1 - pw) * BAL["selfrisk"]

    reach = _approach(a, tb.place, me, world)        # move/wait → позиционирование
    if reach is not None:
        return gamma(state) * clean_acquire(g, state, world, me) * reach - _eff(a) - _risk(a, world, state)
    return -_eff(a)


def _u_harm(a, g, state, world, percept, me) -> float:
    """Лишить жизни цель (хищный импульс из malice, НЕ из жадности). Реализует: attack;
    позиционирует: move/wait (γ·clean·reach) — выследить и ударить в безлюдье. Свидетели гасят
    удар (p_caught), поэтому злонравный, как и грабитель, ждёт уединения — но хочет крови, не сделки."""
    tb = world.bodies.get(g.target)
    if not tb or tb.id == me.id:
        return -_eff(a)
    # оппортунистическая ненависть питается злонравием; ПЛАНОВАЯ (месть) — важностью цели, натура лишь модулирует
    pay = (0.5 + 0.5 * T(state, "malice") + 0.7 * g.value) if g.meta.get("agenda") else (0.8 + T(state, "malice"))
    same = me.place == tb.place
    wit = witnesses(percept, state, g.target)
    if same and a.kind == "attack" and a.target == g.target and not tb.down():
        pw = pwin(me, tb)
        return pw * pay - _caught("attack", wit) * _cost_caught("attack", state) \
            - _cost_moral("attack", state) - (1 - pw) * BAL["selfrisk"]
    reach = _approach(a, tb.place, me, world)
    if reach is not None:
        pw = pwin(me, tb)
        clean = pw * pay - _cost_moral("attack", state) - (1 - pw) * BAL["selfrisk"]
        return gamma(state) * max(0.0, clean) * reach - _eff(a) - _risk(a, world, state)
    return -_eff(a)


def _u_safe(a, g, state, world, percept, me) -> float:
    """Быть невредимым. Реализует: move ПРОЧЬ (рост дистанции) или attack угрозы, если силён."""
    tb = world.bodies.get(g.target)
    pay = g.value
    if not tb:
        return -_eff(a)
    if a.kind == "move":
        d0, d1 = world.dist(me.place, tb.place), world.dist(a.to, tb.place)
        gain = proximity(d0) - proximity(d1)            # >0 если отдаляюсь
        return pay * (BAL["flee_base"] + BAL["flee_gain"] * gain) - _eff(a) - _risk(a, world, state)
    if a.kind == "attack" and a.target == g.target and me.place == tb.place:
        pw = pwin(me, tb)
        return pw * pay - (1 - pw) * pay * 1.2          # победа снимает угрозу; проигрыш — вред
    if a.kind == "wait":
        return -pay * proximity(world.dist(me.place, tb.place)) * 0.3
    return -_eff(a)


def _u_trade(a, g, state, world, percept, me) -> float:
    """Сделка на лучших условиях. accept=взять текущее; counter=держать цену ради уступки.
    Бедность (нужда wealth) поднимает ценность «синицы в руках» → быстрее соглашаемся."""
    if a.target != g.target:
        return -_eff(a)
    surplus = g.value * (0.3 + T(state, "greed"))
    urgency = state.needs.get("wealth", 0.0) * BAL["need_urgency_coin"]
    if a.kind == "say" and a.say == "accept":
        return surplus + urgency * g.value
    if a.kind == "say" and a.say == "counter":
        concede = g.meta.get("concession", 0.25)
        prob = g.meta.get("prob_concede", 0.6)
        # стойкость держать цену = ЖАДНОСТЬ (хочу больше), гасится вспыльчивостью (нетерпёж)
        hold = _clamp(0.35 + 0.7 * T(state, "greed") - 0.2 * T(state, "irritability"), 0.2, 0.97)
        return hold * (surplus + prob * concede * (0.3 + T(state, "greed"))) - _eff(a)
    return -_eff(a)


def _u_affiliate(a, g, state, world, percept, me) -> float:
    """Нужна кооперация лица (ценность super-цели g.value). Подкуп give / лесть say(flatter)
    поднимают его расположение → разблокируют g.value. Скупость (greed) удорожает дар."""
    tb = world.bodies.get(g.target)
    if not tb or tb.id == me.id:
        return -_eff(a)
    recept = g.meta.get("flatter_recept", 1.0)               # дотошный страж глух к лести → нужно золото
    eff_flatter = (0.2 + 0.4 * T(state, "sociability")) * recept
    same = me.place == tb.place
    # РЕАЛИЗ (со-локально): подкуп/дар или лесть поднимают расположение
    if same and a.kind == "give" and a.target == g.target and a.item is not None:
        eff = _clamp(0.3 + 0.7 * a.item.value)
        return g.value * eff - a.item.value * (0.3 + T(state, "greed"))
    if same and a.kind == "say" and a.say == "flatter" and a.target == g.target:
        return g.value * eff_flatter - _eff(a)
    # ПОЗИЦИОНИРОВАНИЕ: подойти к нужному лицу (ухаживание — многотиково)
    reach = _approach(a, tb.place, me, world)
    if reach is not None:
        return gamma(state) * g.value * eff_flatter * reach - _eff(a) - _risk(a, world, state)
    return -_eff(a)


def _u_protect(a, g, state, world, percept, me) -> float:
    """Защитить союзника. Реализует: attack нападающего / move-перехват. Цена риска ↓ храбростью."""
    pay = g.value * (0.4 + T(state, "loyalty"))
    attacker = g.meta.get("attacker")
    ab = world.bodies.get(attacker)
    if not ab:
        return -_eff(a)
    pw = pwin(me, ab)
    clean = pw * pay - (1 - pw) * BAL["selfrisk"] * (1.3 - T(state, "bravery"))   # ценность вмешательства
    if a.kind == "attack" and a.target == attacker and me.place == ab.place:
        return clean                                  # реализация — сейчас, не дисконт
    reach = _approach(a, ab.place, me, world)          # позиционирование — γ·clean·reach (не «ждать вечно»)
    if reach is not None:
        return gamma(state) * max(0.0, clean) * reach - _eff(a) - _risk(a, world, state)
    return -_eff(a)


def _u_inform(a, g, state, world, percept, me) -> float:
    """Снять неопределённость о ценном. Реализует: say(ask) знающему; позиционирует: move к источнику.
    Действовать вслепую дорого (дисперсия) → расспрос/подход обгоняют, когда любопытство велико."""
    pay = g.value * (0.2 + T(state, "curiosity")) * BAL["info_value"]
    src = g.meta.get("source")
    if a.kind == "say" and a.say == "ask" and a.target == g.target \
            and (g.target in [b.id for b in percept.present]):
        return pay - _eff(a)
    if src is not None and a.kind == "move":
        return gamma(state) * pay * proximity(world.dist(a.to, src)) - _eff(a) - _risk(a, world, state)
    if src is not None and a.kind == "wait" and me.place == src:
        return gamma(state) * pay
    return -_eff(a)


def _u_converse(a, g, state, world, percept, me) -> float:
    """Поговорить с человеком (закрыть соц-нужду). Реализует: say(chat/flatter/ask) со-локально;
    позиционирует: move к нему. Так NPC ОСТАЁТСЯ и заговаривает, а не уходит к ресурсу-застолью."""
    tb = world.bodies.get(g.target)
    if not tb or tb.id == me.id:
        return -_eff(a)
    pay = g.value
    if me.place == tb.place and a.kind == "say" and a.target == g.target and a.say in ("chat", "flatter", "ask"):
        return pay - _eff(a)
    reach = _approach(a, tb.place, me, world)
    if reach is not None:
        return gamma(state) * pay * reach - _eff(a) - _risk(a, world, state)
    return -_eff(a)


def _u_need(a, g, state, world, percept, me) -> float:
    """Удовлетворить нужду (g.target=имя нужды, g.meta.source=место). РЕАЛИЗУЕТ: use ресурса,
    помеченного этой нуждой (очаг→comfort, горн→purpose, похлёбка→hunger); ПОЗИЦИОНИРУЕТ: move к месту.
    Так обычный горожанин ЖИВЁТ: голоден→в трактир→поел; устал→домой→лёг; дело→в мастерскую→работал."""
    pay = g.value
    src = g.meta.get("source")
    if a.kind == "use" and getattr(a.item, "satisfies", None) == g.target:
        return pay                                          # ресурс на месте (use есть только со-локально)
    if src is not None and a.kind == "move":
        return gamma(state) * pay * proximity(world.dist(a.to, src)) - _eff(a) - _risk(a, world, state)
    if src is not None and a.kind == "wait" and me.place == src:
        return gamma(state) * pay * 0.5
    return -_eff(a)


_GOAL = {
    "acquire": _u_acquire, "harm": _u_harm, "safe": _u_safe, "trade": _u_trade,
    "affiliate": _u_affiliate, "protect": _u_protect, "inform": _u_inform, "need": _u_need,
    "converse": _u_converse,
}
