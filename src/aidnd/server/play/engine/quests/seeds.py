"""SIFTER — the 5 launch patterns (spec §4 table + §5 Step 1). Pure code over pool agendas,
the deeds journal and affinity edges → fully-bound QuestSeed dicts (twist candidate attached).

A seed's goal.done is ALWAYS a real _met dict (agenda.py:59-76). Milestone-anchored patterns
(kin_debt, blocked_rival, courtship_wall) lift the giver's live Milestone.done VERBATIM →
completing the quest advances that giver's cursor (the honest bridge). Deed-grievance patterns
(broken_promise, unanswered_blood) name the INTENDED revenge predicate {type:'dead', id:villain}
as goal.done; the giver has no pre-existing milestone for it, so at seed-CHOICE time the pipeline
INSERTS a real revenge Agenda into the giver's live state whose only Milestone.done IS this
predicate (pipeline._ensure_milestone, Task 7) — after which done_any[0] lifts verbatim from that
milestone and quest_writeback advances a real cursor exactly like every other pattern (no special
no-op case). Sift itself never mutates giver state — it only names the predicate.
"""

from __future__ import annotations

DELEGATABLE = {"have", "dead", "wealth", "affinity"}   # "at" is never sifted (§4 table)

# Doran motivation per pattern (drives casting.py kind/reward tone, not the predicate)
_MOTIV = {"kin_debt": "serenity", "broken_promise": "justice", "blocked_rival": "recognition",
          "unanswered_blood": "justice", "courtship_wall": "protection"}


def _fam(name: str) -> str:
    return (name or "").split()[-1]


def _aff(person, other: str) -> float:
    return (person.state.relationships.get(other) or {}).get("affinity", 0.0)


def _open_milestone(person):
    """Current, delegatable milestone of the giver's first active agenda (or None)."""
    for ag in person.state.agendas or []:
        if getattr(ag, "status", "active") != "active":
            continue
        m = ag.current() if hasattr(ag, "current") else None
        if m and (m.done or {}).get("type") in DELEGATABLE:
            return ag, m, ag.cursor
    return None, None, None


def _twist_for(villain: str | None, deeds: list, exclude=()) -> dict | None:
    """A SECOND real fact by the villain → optional OR-disjunct (spec §4/§5 Step 5).
    The predicate is code-authored (neutralise the villain). `exclude` skips the anchor deed(s)
    already spent as evidence, so the twist is a genuinely fresh fact touching the cast."""
    if not villain:
        return None
    for d in deeds:
        if d["id"] in exclude:
            continue
        if d["actor"] == villain and d["verb"] in ("promise", "theft", "murder"):
            what = d["data"].get("what") or d["verb"]
            return {"fact": f"{d['id']}: {what}", "reveal_on": f"visit:{villain}",
                    "adds": {"type": "dead", "id": villain}}
    return None


def _seed(pattern, giver, people, done, villain=None, prize=None, evidence=None, twist=None):
    p = people[giver]
    m = _open_milestone(p)[1]
    goal = {"kind": (m.kind if m else "harm"), "target": (m.target if m else villain), "done": done}
    return {"pattern": pattern, "giver": giver, "giver_name": p.name, "goal": goal,
            "cast": {"villain": villain, "prize": prize}, "motivation": _MOTIV[pattern],
            "twist": twist, "evidence": list(evidence or []), "score": 0.0}


def pat_kin_debt(people, deeds, gt) -> list[dict]:
    """Blocked delegatable acquire/have milestone + a promise deed naming the giver's kin,
    made by a creditor the giver dislikes (affinity giver→creditor < 0)."""
    out = []
    for gid, g in people.items():
        ag, m, cur = _open_milestone(g)
        if not m:
            continue
        for d in deeds:
            if d["verb"] != "promise":
                continue
            creditor, victim = d["actor"], d["obj"]
            if creditor == gid or creditor not in people or victim not in people:
                continue
            if _fam(people[victim].name) != _fam(g.name) or _aff(g, creditor) >= 0:
                continue
            out.append(_seed("kin_debt", gid, people, dict(m.done), villain=creditor, prize=victim,
                             evidence=[d["id"], f"agenda:{gid}:{cur}"],
                             twist=_twist_for(creditor, deeds, exclude={d["id"]})))
    return out


def pat_broken_promise(people, deeds, gt) -> list[dict]:
    """A broken promise + promiser alive + victim holds a grudge (affinity victim→promiser < 0).
    Giver = the aggrieved victim; goal names the intended revenge predicate {dead, villain}. The giver
    has no milestone for it yet — pipeline._ensure_milestone materializes a real revenge Agenda at
    seed-choice time so done_any[0] lifts from a real milestone and the writeback works uniformly."""
    out = []
    for d in deeds:
        if d["verb"] != "promise" or d["status"] != "broken":
            continue
        promiser, victim = d["actor"], d["obj"]
        if promiser not in people or victim not in people:
            continue
        if _aff(people[victim], promiser) >= 0:
            continue
        out.append(_seed("broken_promise", victim, people, {"type": "dead", "id": promiser},
                         villain=promiser, prize=None, evidence=[d["id"]],
                         twist=_twist_for(promiser, deeds, exclude={d["id"]})))
    return out


def pat_blocked_rival(people, deeds, gt) -> list[dict]:
    """Giver's delegatable milestone is blocked by a rival with MUTUAL enmity (< −0.2 both ways)."""
    out = []
    for gid, g in people.items():
        ag, m, cur = _open_milestone(g)
        if not m:
            continue
        for rid, r in people.items():
            if rid == gid:
                continue
            if _aff(g, rid) < -0.2 and _aff(r, gid) < -0.2:   # mutual only
                out.append(_seed("blocked_rival", gid, people, dict(m.done), villain=rid,
                                 evidence=[f"agenda:{gid}:{cur}"],
                                 twist=_twist_for(rid, deeds)))
    return out


def pat_unanswered_blood(people, deeds, gt) -> list[dict]:
    """A witnessed murder/theft with no clearing answer → giver = the aggrieved victim's kin."""
    out = []
    cleared = {d["obj"] for d in deeds if d["verb"] in ("clear", "arrest")}
    for d in deeds:
        if d["verb"] not in ("murder", "theft") or not d.get("witnesses"):
            continue
        villain, victim = d["actor"], d["obj"]
        if villain in cleared or villain not in people or victim not in people:
            continue
        out.append(_seed("unanswered_blood", victim, people, {"type": "dead", "id": villain},
                         villain=villain, evidence=[d["id"]],
                         twist=_twist_for(villain, deeds, exclude={d["id"]})))
    return out


def pat_courtship_wall(people, deeds, gt) -> list[dict]:
    """A stalled courtship: giver's open milestone is an affinity goal toward a beloved."""
    out = []
    for gid, g in people.items():
        ag, m, cur = _open_milestone(g)
        if not m or (m.done or {}).get("type") != "affinity":
            continue
        beloved = m.done.get("id")
        out.append(_seed("courtship_wall", gid, people, dict(m.done), prize=beloved,
                         evidence=[f"agenda:{gid}:{cur}"], twist=None))
    return out


PATTERNS = [pat_kin_debt, pat_broken_promise, pat_blocked_rival, pat_unanswered_blood,
            pat_courtship_wall]


def sift(people: dict, deeds: list, gt: int) -> list[dict]:
    """Run all 5 patterns; dedup identical (pattern, giver, villain, goal-type)."""
    seen, out = set(), []
    for pat in PATTERNS:
        for s in pat(people, deeds, gt):
            key = (s["pattern"], s["giver"], s["cast"]["villain"], s["goal"]["done"].get("type"))
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
    return out
