"""PHASE 1-2 graph-brain (MODULARBRAIN): vector of URGES over needs + MODULATOR BUS.

Urge (Bach/PSI): urge_d = |set−cur| (for us set=0 → "want low" → urge = need level), urgency
grows toward critical. Modulators — 6 global knobs from urges+emotions+traits (arousal/valence/
dominance/resolution/selection_threshold/securing). This is SYSTEMNESS MECHANISM: one knob permeates
all nodes, so hunger recolors even trading without a rule "if hungry while trading".

NEUTRAL at baseline state (needs≈0.2, emotions 0, traits 0.5 → arousal≈valence≈…≈0.5), so
connecting to score (brain.modulate) doesn't shift behavior normally — only under pressure.

Key functions
-------------
urges(state) -> dict : Calculate urge intensity, urgency, and priority for each need.
modulators(state) -> dict : Compute 6 global behavioral modulators from state and traits.
"""

from __future__ import annotations

from .goals import NEED_WEIGHT


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def urges(state) -> dict:
    """For each need: urge (how unsatisfied) + urgency (proximity to critical) + priority."""
    out = {}
    for nd, cur in state.needs.items():
        urgency = _clamp(cur / (1.05 - cur), 0.0, 1.5)          # as cur→1 urgency skyrockets
        w = state.config.traits.get(NEED_WEIGHT[nd], 0.5) + 0.5 if nd in NEED_WEIGHT else 1.0
        out[nd] = {"urge": cur, "urgency": urgency, "priority": cur * w}
    return out


def _lead(urg: dict) -> dict:
    return max(urg.values(), key=lambda u: u["priority"]) if urg else {"urge": 0, "urgency": 0, "priority": 0}


def modulators(state) -> dict:
    """6 global modulators + service fields (leading motive, max urgency)."""
    t, e, urg = state.config.traits, state.emotion, urges(state)
    lead = _lead(urg)
    max_urgency = min(1.0, max((u["urgency"] for u in urg.values()), default=0.0))
    mean_urge = sum(u["urge"] for u in urg.values()) / max(1, len(urg))
    anger, fear = e.get("anger", 0.0), e.get("fear", 0.0)
    joy, distress = e.get("joy", 0.0), e.get("distress", 0.0)
    irr = t.get("irritability", 0.5)

    arousal = _clamp(0.15 + 0.5 * irr + 0.45 * max_urgency + 0.4 * (anger + fear))
    valence = _clamp(0.55 + 0.5 * (joy - distress) - 0.3 * mean_urge)
    dominance = _clamp(0.5 + 0.5 * (t.get("bravery", .5) - .5) + 0.25 * (t.get("pride", .5) - .5)
                       + 0.3 * anger - 0.35 * fear)
    resolution = _clamp(0.62 - 0.4 * max_urgency + 0.2 * (t.get("curiosity", .5) - .5))
    selection_threshold = _clamp(0.3 + 0.4 * min(1.0, lead["priority"] / 1.5)
                                 + 0.2 * ((t.get("pride", .5) + t.get("ambition", .5)) / 2 - .5)
                                 - 0.2 * (irr - .5))
    securing = _clamp(0.4 + 0.6 * (t.get("curiosity", .5) - .5) + 0.3 * urg.get("novelty", {}).get("urge", 0)
                      - 0.3 * min(1.0, lead["priority"] / 1.5))
    return {"arousal": arousal, "valence": valence, "dominance": dominance,
            "resolution": resolution, "selection_threshold": selection_threshold, "securing": securing,
            "_lead": lead, "_max_urgency": max_urgency}


# what drove the modulator (for the "influence arrows" panel in debug)
DRIVERS = {
    "arousal": "нужды(срочность) + гнев/страх + вспыльчивость",
    "valence": "радость−подавленность − давление нужд",
    "dominance": "храбрость + гордость + гнев − страх / (сила vs цель)",
    "resolution": "падает под срочностью (спешка = грубее счёт)",
    "selection_threshold": "сила ведущего мотива + гордость/амбиции (упорство)",
    "securing": "любопытство + новизна − фокус на мотиве (внимание наружу)",
}
