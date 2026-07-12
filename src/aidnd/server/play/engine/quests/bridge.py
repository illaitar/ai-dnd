"""The honest bridge (Inc 1): a giver's real Milestone.done ↔ a contract completion predicate ↔
the writeback that advances the giver's Agenda when an emergent (src:"sift") contract completes.

Pure code — the only LLM touch is the existing plan_agenda call re-planning the giver's next
ambition. Reuses the real _met grammar (agenda.py:59) so the predicate never lies (spec §3b note).

Key functions
-------------
milestone_to_step(m) -> dict | None : Milestone.done → contract step per §4 table; None = not delegatable.
make_done_any(m) -> list[dict] : [dict(m.done)] — verbatim; [0] is always the milestone predicate.
done_any_met(ct, giver_state) -> bool : any done_any disjunct _met for the giver (giver-relative).
quest_writeback(ct, giver_state, manager=None) -> bool : on sift completion, advance cursor + re-plan.
"""

from __future__ import annotations

from aidnd.mind.agenda import _met
from aidnd.mind.llm_agent import plan_agenda


def milestone_to_step(m) -> dict | None:
    """Bridge table (spec §4): the 5 real _met kinds → a contract step, or None if not delegatable.
    For wealth/affinity the concrete `want` (a valuable / a gift) is chosen by casting (Inc 2), so it
    is omitted here — only the step KIND and closing trigger are fixed by the milestone."""
    done = getattr(m, "done", None) or {}
    ty = done.get("type")
    if ty == "have":
        return {"kind": "bring", "want": done.get("item")}
    if ty == "wealth":
        return {"kind": "bring"}                         # casting fills `want` with a real valuable
    if ty == "dead":
        return {"kind": "dead", "target": done.get("id")}
    if ty == "affinity":
        return {"kind": "deliver", "target": done.get("id")}   # casting fills `want` with the gift
    return None                                          # "at" (go himself) / "never" / unknown


def make_done_any(m) -> list[dict]:
    """[dict(m.done)] — a verbatim shallow copy. [0] is ALWAYS the milestone predicate; later
    disjuncts (twist, Inc 3) only ever APPEND, never mutating [0] (spec §3b, §6)."""
    return [dict(getattr(m, "done", None) or {})]


def done_any_met(ct: dict, giver_state) -> bool:
    """True iff ANY disjunct in ct['done_any'] is _met for the giver. giver_state = (state, world).
    'However obtained' (spec §3a): the predicate is checked on the giver's real state, regardless of
    which trigger/route produced it."""
    state, world = giver_state
    return any(_met(cond, state, world) for cond in (ct.get("done_any") or []))


def _anchor_idx(ct: dict, agendas: list, target: dict) -> int | None:
    """Which of the giver's agendas this quest anchors. Prefer the explicit seed evidence tag
    'agenda:<pid>:<idx>' (spec §4 data model); else fall back to the agenda whose CURRENT milestone
    IS this predicate (an unadvanced anchor)."""
    for ev in ((ct.get("seed") or {}).get("evidence") or []):
        if isinstance(ev, str) and ev.startswith("agenda:"):
            try:
                return int(ev.rsplit(":", 1)[1])
            except (ValueError, IndexError):
                pass
    for i, ag in enumerate(agendas):
        m = ag.current()
        if m is not None and dict(m.done) == dict(target):
            return i
    return None


def quest_writeback(ct: dict, giver_state, manager=None) -> bool:
    """Completion of a src:"sift" contract advances the giver's REAL agenda (spec §3b, §5 Step 5):
    verify done_any[0] still _met for the giver AND the anchored milestone still open/unadvanced,
    then cursor += 1; if the agenda is now exhausted, mark it done and (with a manager) plan_agenda
    the next ambition. Guard (§6 'milestone moot'): a no-op returning False if already advanced or the
    predicate no longer holds. Returns True iff the cursor advanced."""
    if ct.get("src") != "sift":                          # improvised contracts never write back
        return False
    state, world = giver_state
    done_any = ct.get("done_any") or []
    if not done_any or not _met(done_any[0], state, world):   # predicate must STILL hold
        return False
    agendas = getattr(state, "agendas", None) or []
    idx = _anchor_idx(ct, agendas, done_any[0])
    if idx is None or not (0 <= idx < len(agendas)):
        return False
    ag = agendas[idx]
    m = ag.current()
    if m is None or dict(m.done) != dict(done_any[0]):   # already advanced / different milestone
        return False
    ag.cursor += 1                                        # agenda.py:42 — the honest bridge fires
    if ag.cursor >= len(ag.milestones):                  # whole ambition reached → form a new one
        ag.status = "done"
        if manager is not None:
            ctx = {"roles": {state.config.id: getattr(state.config, "role", "")}}
            newag = plan_agenda(state, world, ctx, manager)
            if newag is not None:
                agendas.append(newag)
    return True
