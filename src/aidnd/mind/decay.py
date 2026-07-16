"""Two-speed lazy affect decay (МОЗГ Inc1). Pure. Relaxes an NPC's affect toward its floor keyed
on elapsed game-time since the last pass — emotions FAST toward mood_baseline, anchored
relationships SLOW toward a faint prior (scaled by vengefulness, spec §10), unanchored ties LOOSE
toward 0. Applied on scene entry (never a 1354-wide tick). See
docs/superpowers/specs/2026-07-15-brain-design.md §4.4/§5B.
"""

from __future__ import annotations

from .model import EMOTIONS, NpcState

# mirror of the PB knobs (§4.6) — mind/ is import-clean of the play layer, matching value.BAL.
_K = {
    "decay_emo_days": 0.5,
    "decay_rel_anchored_days": 14.0,
    "decay_rel_loose_days": 2.0,
    "rel_faint_prior": 0.10,
}


def _relax(cur: float, target: float, dt_days: float, half_life_days: float) -> float:
    if half_life_days <= 0:
        return target
    return target + (cur - target) * (0.5 ** (dt_days / half_life_days))


def decay_lazy(state: NpcState, now_gt: int) -> None:
    """Relax affect toward its floor for the elapsed game-time. Idempotent within a gt; a rewound
    clock (now_gt < last_decay_gt) is a no-op that only resets the clock — never amplifies affect.
    """
    dt_days = max(0.0, (now_gt - state.last_decay_gt) / 1440.0)
    state.last_decay_gt = now_gt
    if dt_days <= 0.0:
        return

    # FAST — emotions toward each channel's mood_baseline
    for e in EMOTIONS:
        base = state.emotion_baseline(e)
        state.emotion[e] = _relax(state.emotion.get(e, 0.0), base, dt_days, _K["decay_emo_days"])
        if state.emotion[e] <= base + 1e-3:
            state.emotion_target.pop(e, None)

    # relationships — anchored SLOW (×vengefulness) → faint prior; unanchored LOOSE → 0
    veng = float(state.config.traits.get("vengefulness", 0.5))
    for rel in state.relationships.values():
        if rel.get("anchored"):
            hl = _K["decay_rel_anchored_days"] * (1.0 + veng)          # §10 LOCKED
            aff = rel.get("affinity", 0.0)
            tgt = (1.0 if aff >= 0 else -1.0) * _K["rel_faint_prior"] if aff else 0.0
            rel["affinity"] = _relax(aff, tgt, dt_days, hl)
            rel["fear"] = _relax(rel.get("fear", 0.0), 0.0, dt_days, hl)
            rel["trust"] = _relax(rel.get("trust", 0.0), 0.0, dt_days, hl)
        else:
            hl = _K["decay_rel_loose_days"]
            for k in ("affinity", "fear", "trust"):
                rel[k] = _relax(rel.get(k, 0.0), 0.0, dt_days, hl)


def decay_scene_entrants(states: dict, here, prev_who, now_gt: int) -> list:
    """Apply ``decay_lazy`` exactly ONCE to each scene ENTRANT — a mind present in ``here`` now but
    absent from ``prev_who`` (the previous tick's settled set). This is THE integration split:

    * an entrant catches up its whole out-of-scene gap here (emotions AND relationships) in one pass,
      then keeps relaxing its *emotions* per-tick via ``tick._decay_emotion`` while it stays in scene;
    * a mind that was already in scene last tick is SKIPPED — re-running ``decay_lazy`` each tick
      would double-apply against the per-tick emotion decay, and relationships have no per-tick
      carrier, so ``decay_lazy`` on entry is their sole (and one-time) decay event.

    Returns the ids that were decayed (present entrants with a live mind). See spec §4.4/§5B.
    """
    entered = []
    prev = set(prev_who)
    for pid in here:
        if pid in prev:
            continue
        st = states.get(pid)
        if st is not None:
            decay_lazy(st, now_gt)
            entered.append(pid)
    return entered
