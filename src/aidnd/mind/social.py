"""Familiarity accrual + newcomer greet (Inc3) — the brain's own social bookkeeping, back in mind/
(U5). Pure: reads only aidnd.mind.tunables.BRAIN and duck-typed NpcState/world objects, never the
play layer. world.py keeps thin call-throughs. Spec §5-U5.

Familiarity is BOOKKEEPING, not an Event (§5-U2): "we have shared a room K times" has no actor,
no salience, no moral-axis tag — wrapping it as an Event would be content-free ceremony. So the
counter stays a counter; at the K-th tick it seeds a faint acquaintance tie directly.
"""

from __future__ import annotations

from .tunables import BRAIN


def _greet_impulse(sociability: float) -> float:
    """Pull to approach a fresh face — sociability-gated: an unsociable NPC (≤0.5) feels none."""
    return round(BRAIN["greet_sociability_base"] * max(0.0, sociability - 0.5), 2)


def _accrue_familiarity(st, other_id: str) -> None:
    """One co-presence tick toward acquaintance. Below familiarity_k the counter just grows and the
    other stays mechanically a STRANGER (no rel row). At the K-th tick a FAINT UNANCHORED tie appears
    (small affinity/trust; anchored=False → loose Inc1 decay), flipping `other ∈ relationships` true
    so greetings warm. A person already known accrues nothing — the counter is pre-acquaintance only."""
    if other_id in st.relationships:
        return
    fam = st.familiarity
    fam[other_id] = fam.get(other_id, 0) + 1
    if fam[other_id] >= BRAIN["familiarity_k"]:
        aff = BRAIN["familiarity_affinity"]
        rel = st.rel(other_id)                           # setdefault → the faint tie now exists
        rel["affinity"] = max(rel.get("affinity", 0.0), aff)
        rel["trust"] = max(rel.get("trust", 0.0), aff)
        rel["anchored"] = False                          # loose — not earned by a real interaction


def _greeted_toward(d: dict, newcomer: str, w) -> bool:
    """Did this decision actually GREET the newcomer — a say directed at them, or a move ONTO their
    spot (an approach)? The ≤1-greeter lock keys on THIS, not on mere selection: a drawn NPC that
    instead ate/worked/waited leaves the slot open for another to greet."""
    for a in (d.get("actions") or []):
        if not isinstance(a, dict):
            continue
        tool = a.get("tool")
        if tool == "say" and str(a.get("text") or "").strip():
            tgt = str(a.get("to") or "").strip()
            if (getattr(w, "aliases", None) or {}).get(tgt.lower(), tgt) == newcomer:
                return True
        elif tool == "move" and a.get("to"):
            if newcomer in w.bodies and str(a["to"]) == w.bodies[newcomer].place:
                return True
    return False


def _pick_newcomer(st, others, greeted: set) -> str | None:
    """First co-present body this NPC has NEVER met (no rel row) and nobody has greeted yet — a fresh
    face that can pull a sociable NPC to approach. A known person or an already-greeted newcomer is
    not a candidate (≤1 greeter/scene)."""
    for other in others:
        if other not in st.relationships and other not in greeted:
            return other
    return None
