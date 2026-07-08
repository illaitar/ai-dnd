"""VALUE LAYER — heart of emergent decision-making.

Behavior is NOT scripted. There are ~5 COMMON utility terms and a map "trait → what it affects"; any
action (move/attack/take/give/say/use/wait) is scored by these terms relative to the GOAL
(desired outcome), and observed behavior (flight, pursuit, ambush, theft, intimidation,
haggling, bribery, protection, evasion, interrogation, goal-switching) — this is which primitive won right now.

Common terms:
  payoff(g)         — value of achieving the goal (× relevant trait/emotion)
  realize           — ps_now·payoff − p_caught·cost − moral        (action REALIZES the goal now)
  opportunity       — γ·payoff·proximity_after·ps_after − caught − moral − risk   (POSITIONS)
  p_caught          — ∝ number of witnesses (third parties)
  cost/moral        — punishment (×lawful) + internal moral brake (×honesty)
Patience γ and risk tolerance are derived from traits. All coefficients are in BAL (this is what
is calibrated to the spec-bench, not 50 scripts).

Key functions
-------------
utility(a, g, state, world, percept) -> float : Main dispatcher for action utility by goal type.
T(state, name: str) -> float : Gets trait value from NPC config.
proximity(d: int) -> float : Proximity factor (1.0/(1.0+d)) for distance decay.
gamma(state) -> float : Opportunity discount factor derived from irritability.
pwin(att, deff) -> float : Combat win probability clamped to [0.02, 0.98].
hostility(state, me, b) -> float : Threat level [0..1] of entity to self.
witnesses(percept, state, target_id: str) -> int : Count third-party observers.
"""

from __future__ import annotations

from .world import ENEMY_FACTIONS

# the only config for coefficients (what is tuned by the optimizer to spec)
BAL = {
    "gamma_base": 0.55, "gamma_focus": 0.40,          # patience γ = base + focus·(1−irritability)
    "eff_move": 0.04, "eff_say": 0.01,
    "caught_per_witness": 0.5, "caught_cap": 0.95,    # p_caught grows with witnesses
    "transgress": {"attack": 1.0, "take": 0.55, "threat": 0.45},
    "cost_lawbase": 0.4, "cost_lawful": 1.5,          # punishment = transgress·(lawbase + lawful·lawful)
    "moral": 1.0,                                     # internal brake = transgress·honesty·moral
    "selfrisk": 0.6,                                  # cost of losing a fight
    "take_alert": 0.15, "take_distracted": 0.78, "take_down": 0.92,  # ps of theft by target state
    "flee_base": 0.5, "flee_gain": 2.2,
    "idle": 0.05,
    "need_urgency_coin": 0.5,                         # bird in hand — poverty accelerates the deal
    "info_value": 0.6,
    "proxemics": 0.2,                                 # social distance pull: small, never overrides needs/safety
}


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def T(state, name: str) -> float:
    return state.config.traits.get(name, 0.5)


def proximity(d: int) -> float:
    return 1.0 / (1.0 + d)                 # 1.0 co-located, 0.5 next to, 0.33 one away


def gamma(state) -> float:
    return BAL["gamma_base"] + BAL["gamma_focus"] * (1.0 - T(state, "irritability"))


def pwin(att, deff) -> float:
    return _clamp(att.power / (att.power + deff.power + 1e-9), 0.02, 0.98)


def hostility(state, me, b) -> float:
    """How dangerous b is TO ME [0..1]: explicit attack / enemy faction / remembered fear.
    If b is attacking ANOTHER — direct threat to me is lower (occupied)."""
    if b.attacking == me.id:
        return pwin(b, me)
    rel = state.relationships.get(b.id) or {}
    h = float(rel.get("fear", 0.0))
    if b.faction in ENEMY_FACTIONS and b.faction != me.faction:
        h = max(h, pwin(b, me))
    if b.attacking and b.attacking != me.id:
        h *= 0.2                                  # enemy occupied with other — direct threat to me is low (gives protection, not flight)
    return _clamp(h)


def _is_ally(state, b) -> bool:
    rel = state.relationships.get(b.id) or {}
    return rel.get("affinity", 0.0) > 0.2


def witnesses(percept, state, target_id: str) -> int:
    """Third parties nearby (not me, not target, not ally) — who can report/interfere."""
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
    """Risk of ENTERING a place: base + enemies/guards there + bad memory. Gives evasion without 'avoid' rule."""
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
    """proximity(after) for move/wait; None if action is not spatial approach."""
    if a.kind == "move":
        return proximity(world.dist(a.to, target_place))
    if a.kind == "wait":
        return proximity(world.dist(me.place, target_place))
    return None


def _proxemics(a, state, world, percept, me) -> float:
    """Social distance pull for a move: Σ affinity(other) × proximity(dest, other), over everyone
    in the scene (present + nearby, excluding me). Disliked other (affinity<0) near the destination
    lowers utility (avoid them); liked other near the destination raises it (approach them). Scaled
    small (BAL['proxemics']) so it nudges positioning without overriding needs/safety terms."""
    if a.kind != "move":
        return 0.0
    others = [b for b in (percept.present + percept.nearby) if b.id != me.id]
    social = sum(
        state.relationships.get(b.id, {}).get("affinity", 0.0) * proximity(world.dist(a.to, b.place))
        for b in others
    )
    return BAL["proxemics"] * social


# utility(action | goal): single dispatcher by goal TYPE (not by script)
def utility(a, g, state, world, percept) -> float:
    me = percept.me
    fn = _GOAL.get(g.kind)
    base = fn(a, g, state, world, percept, me) if fn else -_eff(a)
    return base + _proxemics(a, state, world, percept, me)


def _acq_pay(g, state) -> float:
    return g.value * (0.3 + T(state, "greed"))


def clean_acquire(g, state, world, me) -> float:
    """Value of "clean strike" — best REALIZE at co-location and WITHOUT witnesses. It leads to
    positioning (close/wait), discounted by γ. This removes "eternal waiting":
    wait = γ·(what I'll do at convenient moment) < do now, when the moment came."""
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
    """Seize target's wealth. REALIZE (now, with current witnesses): say(threat)=extortion,
    take=theft, attack=knock down→finish. POSITION (move/wait): γ·clean·reach — close/wait
    for the right moment. Flight/pursuit/ambush/theft/mugging — this is which primitive won."""
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

    reach = _approach(a, tb.place, me, world)        # move/wait → positioning
    if reach is not None:
        return gamma(state) * clean_acquire(g, state, world, me) * reach - _eff(a) - _risk(a, world, state)
    return -_eff(a)


def _u_harm(a, g, state, world, percept, me) -> float:
    """Deprive target of life (predatory impulse from malice, NOT greed). Realizes: attack;
    positions: move/wait (γ·clean·reach) — stalk and strike in solitude. Witnesses dampen
    blow (p_caught), so malicious one, like thief, waits for privacy — but wants blood, not a deal."""
    tb = world.bodies.get(g.target)
    if not tb or tb.id == me.id:
        return -_eff(a)
    # opportunistic hatred feeds on malice; PLANNED (vengeance) — on goal importance, nature only modulates
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
    """Be unharmed. Realizes: move AWAY (growing distance) or attack the threat, if strong."""
    tb = world.bodies.get(g.target)
    pay = g.value
    if not tb:
        return -_eff(a)
    if a.kind == "move":
        d0, d1 = world.dist(me.place, tb.place), world.dist(a.to, tb.place)
        gain = proximity(d0) - proximity(d1)            # >0 if I'm fleeing
        return pay * (BAL["flee_base"] + BAL["flee_gain"] * gain) - _eff(a) - _risk(a, world, state)
    if a.kind == "attack" and a.target == g.target and me.place == tb.place:
        pw = pwin(me, tb)
        return pw * pay - (1 - pw) * pay * 1.2          # victory removes threat; defeat — harm
    if a.kind == "wait":
        return -pay * proximity(world.dist(me.place, tb.place)) * 0.3
    return -_eff(a)


def _u_trade(a, g, state, world, percept, me) -> float:
    """Deal at better terms. accept=take current; counter=hold price for concession.
    Poverty (wealth need) raises "bird in hand" value → faster agreement."""
    if a.target != g.target:
        return -_eff(a)
    surplus = g.value * (0.3 + T(state, "greed"))
    urgency = state.needs.get("wealth", 0.0) * BAL["need_urgency_coin"]
    if a.kind == "say" and a.say == "accept":
        return surplus + urgency * g.value
    if a.kind == "say" and a.say == "counter":
        concede = g.meta.get("concession", 0.25)
        prob = g.meta.get("prob_concede", 0.6)
        # firmness to hold price = GREED (want more), dampened by irritability (impatience)
        hold = _clamp(0.35 + 0.7 * T(state, "greed") - 0.2 * T(state, "irritability"), 0.2, 0.97)
        return hold * (surplus + prob * concede * (0.3 + T(state, "greed"))) - _eff(a)
    return -_eff(a)


def _u_affiliate(a, g, state, world, percept, me) -> float:
    """Need cooperation from target (value of super-goal g.value). Bribe give / flattery say(flatter)
    raise affinity → unlock g.value. Avarice (greed) makes gift costly."""
    tb = world.bodies.get(g.target)
    if not tb or tb.id == me.id:
        return -_eff(a)
    recept = g.meta.get("flatter_recept", 1.0)               # meticulous guard deaf to flattery → need gold
    eff_flatter = (0.2 + 0.4 * T(state, "sociability")) * recept
    same = me.place == tb.place
    # REALIZE (co-located): bribe/gift or flattery raise affinity
    if same and a.kind == "give" and a.target == g.target and a.item is not None:
        eff = _clamp(0.3 + 0.7 * a.item.value)
        return g.value * eff - a.item.value * (0.3 + T(state, "greed"))
    if same and a.kind == "say" and a.say == "flatter" and a.target == g.target:
        return g.value * eff_flatter - _eff(a)
    # POSITIONING: approach needed target (courtship — multi-tick)
    reach = _approach(a, tb.place, me, world)
    if reach is not None:
        return gamma(state) * g.value * eff_flatter * reach - _eff(a) - _risk(a, world, state)
    return -_eff(a)


def _u_protect(a, g, state, world, percept, me) -> float:
    """Protect ally. Realizes: attack attacker / move-intercept. Cost of risk ↓ by bravery."""
    pay = g.value * (0.4 + T(state, "loyalty"))
    attacker = g.meta.get("attacker")
    ab = world.bodies.get(attacker)
    if not ab:
        return -_eff(a)
    pw = pwin(me, ab)
    clean = pw * pay - (1 - pw) * BAL["selfrisk"] * (1.3 - T(state, "bravery"))   # value of intervention
    if a.kind == "attack" and a.target == attacker and me.place == ab.place:
        return clean                                  # realization — now, not discounted
    reach = _approach(a, ab.place, me, world)          # positioning — γ·clean·reach (not 'wait forever')
    if reach is not None:
        return gamma(state) * max(0.0, clean) * reach - _eff(a) - _risk(a, world, state)
    return -_eff(a)


def _u_inform(a, g, state, world, percept, me) -> float:
    """Remove uncertainty about something valuable. Realizes: say(ask) to knower; positions: move to source.
    Acting blind is costly (variance) → interrogation/approach beat it, when curiosity is high."""
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
    """Talk to a person (close social need). Realizes: say(chat/flatter/ask) co-locally;
    positions: move to them. Thus NPC STAYS and converses, not leaves to a resource/feast."""
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
    """Satisfy a need (g.target=need name, g.meta.source=place). REALIZES: use resource,
    marked with this need (hearth→comfort, forge→purpose, soup→hunger); POSITIONS: move to place.
    Thus a normal townsperson LIVES: hungry→tavern→ate; tired→home→slept; job→workshop→worked."""
    pay = g.value
    src = g.meta.get("source")
    if a.kind == "use" and getattr(a.item, "satisfies", None) == g.target:
        return pay                                          # resource in place (use only co-locally)
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
