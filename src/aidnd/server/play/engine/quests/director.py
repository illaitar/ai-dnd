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


def _window_scores() -> list:
    scores = []
    for status in ("queued", "offered", "board"):
        for c in _emergent(status):
            if (c.get("arc") or {}).get("beat") in _LIVE_BEATS:
                scores.append((c.get("seed") or {}).get("score", 0.0))
    return scores


def admit(new_seeds_scored: list) -> dict | None:
    """Return the seed to persist-and-surface this morning, or None. new_seeds_scored is judge-kept,
    salience-sorted (desc). Window free → top seed; window full → only a seed scoring ≥ k× the
    weakest live offer interrupts (the bumped one stays queued and is re-scored next morning)."""
    if not new_seeds_scored:
        return None
    top = new_seeds_scored[0]
    if active_count() < PB["quest_active_max"]:
        return top
    weakest = min(_window_scores(), default=0.0)
    if top.get("score", 0.0) >= PB["quest_interrupt_k"] * weakest:
        return top
    return None


def tick_morning() -> list:
    """Morning maintenance: expire stale offers to compost + close 'overtaken' live seeds."""
    from aidnd.server.play.engine.quests.pipeline import _expire_stale, _recheck_overtaken
    return _expire_stale() + _recheck_overtaken()
