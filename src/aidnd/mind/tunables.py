"""Единый реестр brain-affect настроек (U4). ONE source of truth for every knob the affective
contour reads — decay, Event projection (incl. the U1 victim tier), self-regulation, self_regard,
familiarity/greet, attention. Pure module (stdlib only) so mind/ stays import-clean of the play
layer. decay.py / project.py / value.py import BRAIN directly; session/config.py:PB does
PB.update(BRAIN) so every existing PB[...] read is unchanged (zero call-site churn). Spec §4b/§4c.

value.BAL keeps its DECISION-layer knobs (gamma_base, transgress, caught_per_witness, …) — those are
NOT brain-affect knobs and are out of BRAIN by design.
"""

from __future__ import annotations

BRAIN = {
    # ── two-speed lazy affect decay (Inc1; was mind.decay._K + PB) ───────────────────────────────
    "decay_emo_days": 0.5,            # emotion half-life (days) → mood_baseline (FAST)
    "decay_rel_anchored_days": 14.0,  # anchored-rel half-life (days) → faint prior (SLOW); ×(1+veng)
    "decay_rel_loose_days": 2.0,      # unanchored-rel half-life (days) → 0 (LOOSE)
    "rel_faint_prior": 0.10,          # anchored affinity relaxes toward sign×this, not 0
    # ── Event projection: visceral + moral-lens channels (Inc2; was mind.project._K + PB) ────────
    "ev_perc_l2": 0.6, "ev_perc_l3": 0.3,          # perception weight at audibility tier L2 / L3
    "ev_harm_base": 0.6, "ev_harm_familiar": 0.4,  # visceral fear base + familiarity-with-actor lift
    "ev_viol_damp": 0.5,                           # positive morals.violence damps witnessed-fear
    "ev_empathy_care": 0.5,                        # empathy → care-for-target (distress for a stranger)
    "ev_taboo_mult": 1.6,                          # outrage × when a tag ∈ witness taboos
    "ev_approval_k": 0.25,                         # positive-stance → grim-satisfaction joy scale
    "ev_rel_fear": 0.5, "ev_rel_aff": 0.4, "ev_warmth": 0.2,  # bystander rel-delta scales
    "ev_control_brave": 0.6,                       # смелость свидетеля гасит страх — control=к·bravery
    # ── NEW victim tier (U1, §4b) — chosen to reproduce both raw victim blocks within ±0.1 ───────
    "ev_victim_harm_mult": 1.8,   # visceral harm ×this for the one struck (0 stays 0 → no fear on threatless crime)
    "ev_victim_gi": 0.8,          # victim goal_impact floor (drives distress + couples anger)
    "ev_victim_desert": 0.75,     # victim desert floor (guarantees deserved-anger fires)
    "ev_victim_aff": 0.4,         # grudge affinity ceiling: affinity = min(cur, −0.4)
    "ev_victim_rel_fear": 0.85,   # grudge rel-fear when the event carried physical threat (>0)
    # ── self-regulation (was value.BAL + PB) ─────────────────────────────────────────────────────
    "feel_nudge_cap": 0.25,       # max ±delta a feel/need tool may move a channel per call
    # ── self_regard (was value.BAL + PB) ─────────────────────────────────────────────────────────
    "sr_pride": 0.35, "sr_brave": 0.35, "sr_amb": 0.30,   # self_regard trait weights
    "sr_span": 1.5,                                        # perceived-pwin bias span around 0.5
    # ── familiarity accrual + newcomer greet (Inc3; was PB only) ─────────────────────────────────
    "familiarity_k": 4,              # co-presence ticks before a faint unanchored tie seeds
    "familiarity_affinity": 0.05,    # faint warmth/trust of the seeded acquaintance tie
    "greet_sociability_base": 1.4,   # newcomer-greet impulse = base × max(0, sociability−0.5)
    # ── attention Pillar 2 (Inc6; was PB only) ───────────────────────────────────────────────────
    "att_asleep": 0.2, "att_drunk": 0.4, "att_absorbed": 0.6, "att_alert": 1.3,
}
