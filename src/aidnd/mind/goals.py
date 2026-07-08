"""Goals = DESIRED OUTCOMES with value (not plans, not steps). Each tick formed from perception:
standing (needs) + opportunities (rich goal nearby → acquire; threat → survive; ally in trouble →
protect; uncertainty about valuable → learn). Payoff for each calculated in value.py from traits/emotions.

No behavior scripts here — only 'what is valuable now'. How to achieve — decided by utility over
common primitives. Formation of NEW situational goal — place for LLM (marked), but basic
set derived mechanically so system is deterministic and verifiable.

Key functions
--------------
Goal : desired outcome with kind, target, value, and metadata.
standing_needs(state) -> list : generate standing goals from NPC needs.
propose_goals(state, world, percept) -> list : compile all goal candidates for tick.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .value import _is_ally, hostility
from .world import Item  # noqa: F401  (used by calling scenarios)

# need weight = how much an NPC is driven by this need (trait amplifies)
NEED_WEIGHT = {"social": "sociability", "purpose": "ambition",
               "wealth": "greed", "novelty": "curiosity"}


@dataclass
class Goal:
    kind: str                       # acquire | safe | trade | affiliate | protect | inform | need
    target: str | None = None       # body id / need name / topic
    value: float = 0.0              # raw payoff before scaling by trait (in value.py)
    meta: dict = field(default_factory=dict)

    def label(self) -> str:
        return f"{self.kind}:{self.target}={round(self.value, 2)}"


def standing_needs(state) -> list:
    """Standing goals from needs — payoff = level × trait weight."""
    out = []
    for nd, lvl in state.needs.items():
        w = state.config.traits.get(NEED_WEIGHT[nd], 0.5) + 0.5 if nd in NEED_WEIGHT else 1.0
        val = lvl * w
        if val > 0.08:
            meta = dict(state.needs_sources.get(nd, {})) if hasattr(state, "needs_sources") else {}
            out.append(Goal("need", nd, val, meta))
    return out


def _agenda_goals(state) -> list:
    """Long-term goals → mechanical goal of CURRENT milestone (its core drives reactively). Formation
    gates do not apply: planner already decided this is a goal (peaceful can seek revenge, modest can hoard)."""
    out = []
    for ag in getattr(state, "agendas", None) or []:
        if getattr(ag, "status", "") != "active":
            continue
        m = ag.current()
        if not m:
            continue
        meta = dict(m.meta)
        meta["agenda"] = ag.summary
        out.append(Goal(m.kind, m.target, ag.importance, meta))
    return out


def propose_goals(state, world, percept) -> list:
    """Complete set of goal candidates for this tick. Does not 'choose' anything — utility does the choosing."""
    me = percept.me
    goals = list(getattr(state, "extra_goals", []))      # scenarios may inject trade/affiliate/inform
    goals += _agenda_goals(state)                        # long-term goals (planner)
    goals += standing_needs(state)

    # ACUTE threat — co-location only (enemy face-to-face → flee); distant enemy avoided (risk node)
    danger, threat_id = 0.0, None
    for b in percept.present:
        h = hostility(state, me, b)
        if h > danger:
            danger, threat_id = h, b.id
    safe_val = max(state.emotion.get("fear", 0.0), danger)
    if safe_val > 0.08 and threat_id:
        goals.append(Goal("safe", threat_id, safe_val))

    # opportunity to acquire — NOT for everyone: only with predatory INCLINATION and for truly worthy target.
    # Common citizen (honest/lawful) does not 'consider robbing' neighbor — goal does not arise.
    tr = state.config.traits
    predatory = tr.get("greed", 0.5) * (1 - tr.get("honesty", 0.5)) * (1 - 0.5 * tr.get("lawful", 0.5))
    malice = tr.get("malice", 0.5)
    for b in percept.present + percept.nearby:
        if b.id == me.id or _is_ally(state, b):
            continue
        if predatory > 0.30 and b.appearance > 0.25:        # ← LLM value appraisal connects here
            goals.append(Goal("acquire", b.id, b.appearance))
        if malice > 0.6 and not b.down():                   # predation — separate goal, not from greed
            goals.append(Goal("harm", b.id, malice))

    # social approach: talk to present — close social need THROUGH person (not resource).
    # Driven by sociability × social-need × (affinity + target's CHARISMA). Beauty (charisma) ≠ wealth (appearance).
    # CROWD around target dilutes pull (all clung to 'star' → others seek talk partner nearby),
    # RECIPROCITY (they're talking to ME now) amplifies — stable talk pairs form this way.
    soc = state.needs.get("social", 0.0)
    socbl = tr.get("sociability", 0.5)
    if soc > 0.12:
        for b in percept.present:
            if b.id == me.id or hostility(state, me, b) > 0.3 or b.down():
                continue
            aff = (state.relationships.get(b.id) or {}).get("affinity", 0.0)
            draw = soc * (0.3 + socbl) * (0.3 + 0.5 * max(0.0, aff) + 0.6 * getattr(b, "charisma", 0.3))
            suitors = sum(1 for ob in percept.present
                          if ob.id not in (me.id, b.id) and getattr(ob, "talking_to", None) == b.id)
            if getattr(b, "talking_to", None) == me.id:
                draw *= 1.6
            draw /= (1.0 + 0.5 * suitors)
            if draw > 0.12:
                goals.append(Goal("converse", b.id, min(1.0, draw)))

    # ally protection: co-location — nearby ally under attack
    for b in percept.present:
        if not _is_ally(state, b):
            continue
        attacker = next((x for x in percept.present if x.attacking == b.id), None)
        if attacker:
            peril = attacker.power / (b.hp + 1e-9)
            goals.append(Goal("protect", b.id, min(1.1, 0.5 + 0.3 * peril),
                              {"attacker": attacker.id}))
    return goals
