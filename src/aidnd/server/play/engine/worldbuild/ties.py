"""Weaving persona ties and workplace acquaintances into NPC minds.

Key functions
-------------
_weave_ties(people) -> None : Bind persona ties ('owes cutthroats', 'feuds with elder') to real pool people.
_weave_locals(people) -> None : Colleagues at the same venue become mild mutual acquaintances.
"""

from __future__ import annotations

import random

from ..session.time import _mt

_TIE_ROLES = {
    "головорез": "головорез",
    "шайк": "головорез",
    "стражн": "стражник",
    "лавочн": "лавочник",
    "куп": "лавочник",
    "трактир": "трактирщик",
    "жрец": "жрец",
    "знахар": "знахарка",
    "кузнец": "кузнец",
    "мельник": "мельник",
    "бард": "бард",
    "бродя": "бродяга",
    "сапожн": "сапожник",
    "дубильщ": "дубильщик",
    "стар": "жрец",
}


def _weave_ties(people) -> None:
    """Person ties ('owes cutthroats', 'feuds with elder') are BOUND to real pool people:
    mutual relations in mind + memory with real name. Graph 'who knows whom' becomes real;
    deterministic, idempotent (by memory mark)."""
    rng = random.Random("ties|1")
    byrole: dict = {}
    for oid, o in sorted(people.items()):
        byrole.setdefault(o.role, []).append(oid)
    for pid, p in sorted(people.items()):
        st = p.state
        if any("— это про" in m.text for m in st.memory.items):
            continue  # already bound (incl. restored from npc_state)
        for tie in ((p.persona or {}).get("ties") or [])[:2]:
            tl = tie.lower()
            role = next((r for w, r in _TIE_ROLES.items() if w in tl), None)
            cands = [x for x in byrole.get(role, []) if x != pid]
            if not cands:
                continue
            oid = rng.choice(cands)
            o = people[oid]
            ar, br = st.rel(oid), o.state.rel(pid)
            hostile = any(w in tl for w in ("вражд", "подозр", "ненавид", "угрож", "презир"))
            debt = any(w in tl for w in ("должен", "долг", "задолж"))
            fear = any(w in tl for w in ("боит", "страш", "опаса"))
            if hostile:  # real feud — mutual negative
                ar["fear"] = max(ar["fear"], 0.3)
                ar["affinity"] = min(ar["affinity"], -0.2)
                br["affinity"] = min(br["affinity"], -0.1)
            elif debt:  # debt — obligation, NOT hatred
                ar["fear"] = max(ar["fear"], 0.2)  # debtor slightly fears creditor
            elif fear:  # fear without feud — affinity neutral
                ar["fear"] = max(ar["fear"], 0.35)
            else:  # good acquaintance/kinship
                ar["affinity"] = max(ar["affinity"], 0.4)
                ar["trust"] = max(ar["trust"], 0.3)
                br["affinity"] = max(br["affinity"], 0.3)
            st.memory.add(f"{tie} — это про {o.name}", _mt(), 0.5, kind="fact", about=[oid])
            o.state.memory.add(
                f"{p.name}: {tie[:90]} — нас связывает", _mt(), 0.4, kind="fact", about=[pid]
            )


def _weave_locals(people) -> None:
    """Colleagues at the same venue know each other — mild MUTUAL acquaintance. A venue's on-shift
    crowd (a tavern's staff, a workshop's hands) are then familiar faces who converse rather than
    strangers who sit apart. Small tight groups that are reliably co-present. Idempotent by mark."""
    bywork: dict = {}
    for pid in sorted(people):
        if people[pid].work:
            bywork.setdefault(people[pid].work, []).append(pid)
    for members in bywork.values():
        if len(members) < 2:
            continue
        for pid in members:
            st = people[pid].state
            if any("здесь все свои — лица знакомы" in m.text for m in st.memory.items):
                continue                                 # already woven (idempotent)
            for oid in members:
                if oid == pid:
                    continue
                ar, br = st.rel(oid), people[oid].state.rel(pid)
                ar["affinity"], ar["trust"] = max(ar["affinity"], 0.3), max(ar["trust"], 0.15)
                br["affinity"], br["trust"] = max(br["affinity"], 0.3), max(br["trust"], 0.15)
            st.memory.add("здесь все свои — лица знакомы", _mt(), 0.3, kind="fact")
