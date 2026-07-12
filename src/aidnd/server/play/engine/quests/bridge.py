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
