"""DIRECTOR — the tiny persisted FSM that paces the TELLING only (spec §3a note 2). It never touches
minds: quest_active_max caps offers-in-flight; quest_interrupt_k lets a much stronger seed jump the
window; quest_offer_days expires stale offers to compost. Queue state IS the persisted contract rows."""

from __future__ import annotations

from aidnd.server.play.engine.core import PB, _store, _wid

_LIVE_BEATS = {"foreshadow", "offered"}


def _emergent(status: str) -> list:
    return [c for c in _store().contracts(_wid(), status) if c.get("src") == "sift"]


def active_count() -> int:
    n = 0
    for status in ("queued", "offered", "board"):
        n += sum(1 for c in _emergent(status) if (c.get("arc") or {}).get("beat") in _LIVE_BEATS)
    return n


def _live_contracts() -> list:
    out = []
    for status in ("queued", "offered", "board"):
        for c in _emergent(status):
            if (c.get("arc") or {}).get("beat") in _LIVE_BEATS:
                out.append(c)
    return out


def _window_scores() -> list:
    return [(c.get("seed") or {}).get("score", 0.0) for c in _live_contracts()]


def window_occupied() -> bool:
    """Beat-aware occupancy (unlike pipeline's old crude status-only check): a bumped/waiting
    contract (arc.beat='foreshadow-pending') does NOT hold the window — only a truly live
    (foreshadow/offered) emergent contract does."""
    return active_count() >= PB["quest_active_max"]


def would_interrupt(score: float) -> bool:
    """True iff `score` clears quest_interrupt_k× the weakest LIVE occupant. Window-empty callers
    don't need this (admit() short-circuits before it); it exists standalone so pipeline can gate
    the (LLM) judge call itself on the same threshold, without spending it on a hopeless morning."""
    weakest = min(_window_scores(), default=0.0)
    return score >= PB["quest_interrupt_k"] * weakest


def admit(new_seeds_scored: list) -> dict | None:
    """Return the seed to persist-and-surface this morning, or None. new_seeds_scored is judge-kept,
    salience-sorted (desc). Window free → top seed; window full → only a seed scoring ≥ k× the
    weakest live offer interrupts (the bumped one stays queued and is re-scored next morning)."""
    if not new_seeds_scored:
        return None
    top = new_seeds_scored[0]
    if active_count() < PB["quest_active_max"]:
        return top
    if would_interrupt(top.get("score", 0.0)):
        return top
    return None


def bump_weakest() -> dict | None:
    """Interrupt fired: demote the weakest LIVE occupant back to waiting — status='queued',
    arc.beat='foreshadow-pending' (distinct from the pre-surface 'foreshadow' beat so it reads as
    'was offered, bumped' rather than 'brand new'). NOT composted, NOT lost: it simply drops out of
    active_count()'s window-holding beats, so the next free morning it re-enters normally (the
    ordinary sift/queue path — see pipeline._recheck_overtaken/Task 14 for a true queue-rebuild read
    of these rows). Returns the demoted contract dict, or None if nothing was live to bump."""
    live = _live_contracts()
    if not live:
        return None
    victim = min(live, key=lambda c: (c.get("seed") or {}).get("score", 0.0))
    data = {k: v for k, v in victim.items() if k not in ("id", "status")}
    data["arc"] = {"beat": "foreshadow-pending"}
    _store().save_contract(_wid(), victim["id"], "queued", data)
    return victim


def tick_morning() -> list:
    """Morning maintenance: expire stale offers to compost + close 'overtaken' live seeds."""
    from aidnd.server.play.engine.quests.pipeline import _expire_stale, _recheck_overtaken
    return _expire_stale() + _recheck_overtaken()
