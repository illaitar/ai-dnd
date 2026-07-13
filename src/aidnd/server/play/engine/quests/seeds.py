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

# plain_need has no fixed pattern-tone — motivation follows the milestone kind instead (§ below)
_MOTIV_BY_DONE_TYPE = {"have": "equipment", "wealth": "wealth", "affinity": "reputation",
                       "dead": "conquest"}


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


def _revenge_summary(villain_name: str) -> str:
    """The grievance text (sim-authored, honest) used both as the seed's own summary AND — verbatim —
    as the inserted revenge Agenda's summary (pipeline._ensure_milestone), so the two never drift.
    Takes the villain's NAME (never his pid) — this text flows into the inserted Agenda, into
    pipeline._allowed, and into the framer prompt, so a raw pid here would leak straight into the
    player-facing pitch."""
    return f"расквитаться с {villain_name} за нарушенное слово"


def _seed(pattern, giver, people, done, villain=None, prize=None, evidence=None, twist=None,
          motivation=None, summary=None):
    p = people[giver]
    ag, m, cur = _open_milestone(p)
    goal = {"kind": (m.kind if m else "harm"), "target": (m.target if m else villain), "done": done}
    return {"pattern": pattern, "giver": giver, "giver_name": p.name, "goal": goal,
            "cast": {"villain": villain, "prize": prize}, "motivation": motivation or _MOTIV[pattern],
            "twist": twist, "evidence": list(evidence or []), "score": 0.0,
            # sim-authored truth (plan_agenda's own words) — never invented, widens the framer's allowed set
            "summary": summary if summary is not None else (getattr(ag, "summary", "") or "")}


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
                             evidence=[f"deed:{d['id']}", f"agenda:{gid}:{cur}"],
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
                         villain=promiser, prize=None, evidence=[f"deed:{d['id']}"],
                         twist=_twist_for(promiser, deeds, exclude={d["id"]}),
                         summary=_revenge_summary(people[promiser].name)))
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


def _kin_giver(victim: str, villain: str, people: dict):
    """A living kin/friend who can actually stand at the board and hire the party (spec: 'kin/friend
    of the victim present') — the victim is dead and cannot be the giver. Surname match first
    (reuses _fam, as kin_debt does); else affinity(candidate→victim) > 0.3; else None (abstain)."""
    surname = _fam(people[victim].name)
    for pid, p in people.items():
        if pid in (victim, villain):
            continue
        if _fam(p.name) == surname:
            return pid
    for pid, p in people.items():
        if pid in (victim, villain):
            continue
        if _aff(p, victim) > 0.3:
            return pid
    return None


def _blood_answered(villain: str, deeds: list, flag_get) -> bool:
    """Already answered iff an arrest deed NAMES the villain as its object (a clear deed's obj is a
    LAIR, not a person — never matches here) or the world already marked the villain dead."""
    if any(d["verb"] == "arrest" and d["obj"] == villain for d in deeds):
        return True
    if flag_get is not None and flag_get(f"dead|{villain}"):
        return True
    return False


def pat_unanswered_blood(people, deeds, gt, flag_get=None) -> list[dict]:
    """A witnessed murder/theft with no clearing answer → giver = a living kin/friend of the victim
    (the victim, being dead, cannot hire the party); villain = the deed actor; the victim becomes
    the cast prize (his memory). No kin/friend present → abstain."""
    out = []
    for d in deeds:
        if d["verb"] not in ("murder", "theft") or not d.get("witnesses"):
            continue
        villain, victim = d["actor"], d["obj"]
        if villain not in people or victim not in people:
            continue
        if _blood_answered(villain, deeds, flag_get):
            continue
        giver = _kin_giver(victim, villain, people)
        if giver is None:
            continue
        out.append(_seed("unanswered_blood", giver, people, {"type": "dead", "id": villain},
                         villain=villain, prize=victim, evidence=[f"deed:{d['id']}"],
                         twist=_twist_for(villain, deeds, exclude={d["id"]}),
                         summary=_revenge_summary(people[villain].name)))
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


def pat_plain_need(people, deeds, gt) -> list[dict]:
    """LAST-resort pattern: «Quest = delegated NPC need» (docs/quests.md) made literal — ANY giver
    with an open delegatable milestone binds, no villain/deed required. This is what keeps
    aspiration-only worlds (morning agenda seeding with no antagonist material) from producing
    zero seeds forever. Salience naturally keeps these from drowning the flavored patterns: peak's
    giver→villain edge is 0 (cast has no villain) and there is no deed-weight in evidence — only
    rarity/proximity contribute, so a plain seed scores well below any villain-anchored one under
    the same PB weights (see test_quest_salience.py dominance test)."""
    out = []
    for gid, g in people.items():
        ag, m, cur = _open_milestone(g)
        if not m:
            continue
        motivation = _MOTIV_BY_DONE_TYPE.get((m.done or {}).get("type"), "necessity")
        out.append(_seed("plain_need", gid, people, dict(m.done), motivation=motivation,
                         evidence=[f"agenda:{gid}:{cur}"], twist=_twist_for(None, deeds)))
    return out


PATTERNS = [pat_kin_debt, pat_broken_promise, pat_blocked_rival, pat_unanswered_blood,
            pat_courtship_wall, pat_plain_need]


def sift(people: dict, deeds: list, gt: int, flag_get=None) -> list[dict]:
    """Run all 6 patterns; dedup identical (pattern, giver, villain, goal-type). `flag_get`
    (optional, e.g. `lambda k: store.flag_get(wid, k)`) lets unanswered_blood see the world's
    `dead|<pid>` flags; omit it in pure/tests contexts — the arrest-deed check alone still applies.
    plain_need runs LAST and skips any giver a flavored pattern already bound this sift (its own
    dedup key never collides with a flavored seed's, since villain/goal-type usually differ — so
    this second guard is needed to avoid double-seeding the same giver/milestone)."""
    seen, out, bound_givers = set(), [], set()
    for pat in PATTERNS:
        if pat is pat_unanswered_blood:
            raw = pat(people, deeds, gt, flag_get)
        elif pat is pat_plain_need:
            raw = [s for s in pat(people, deeds, gt) if s["giver"] not in bound_givers]
        else:
            raw = pat(people, deeds, gt)
        for s in raw:
            key = (s["pattern"], s["giver"], s["cast"]["villain"], s["goal"]["done"].get("type"))
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
            bound_givers.add(s["giver"])
    return out
