"""Two-channel Event projection (МОЗГ Inc2). Data-driven tag→axis tables (NOT code branches): the
same signature row lands as horror or grim satisfaction depending only on the witness's worldview
morals sign. Un-enriched rows → morals 0 → the moral lens is a no-op; the visceral channel still
fires. Emits appraise-shaped `dims` (PRE-gain — tick.appraise multiplies by emotion_gain downstream)
plus bystander relationship deltas. Zero new LLM. See
docs/superpowers/specs/2026-07-15-brain-design.md §3b/§4.2/§5-ExampleA.
"""

from __future__ import annotations

from .event import Event
from .model import NpcState
from .tunables import BRAIN  # the single brain-affect knob registry (U4) — one source for ev_*

TAG_AXIS = {                       # which worldview.morals axis a tag is scored against
    "убийство": "death", "смерть": "death", "осквернение-мёртвых": "death", "людоедство": "death",
    "насилие": "violence", "избиение": "violence",
    "воровство": "theft", "грабёж": "theft", "кража": "theft",
    "колдовство": "magic", "кощунство": "magic",
    "клятвопреступление": "authority", "вероломство": "authority",
    "чужак-насилие": "outsiders",
}
TABOO_KEYS = {"убийство", "воровство", "кощунство", "людоедство",
              "клятвопреступление", "осквернение-мёртвых", "кровосмешение"}



def _zero() -> dict:
    """A no-delta projection — every dim numerically 0.0 (intent False so `all(v==0.0)` holds)."""
    return {"dims": {"goal_impact": 0.0, "desert": 0.0, "harm": 0.0, "fear": 0.0,
                     "revulsion": 0.0, "intent": False},
            "rel": {"actor_fear": 0.0, "target_warmth": 0.0, "anchored": False}}


def _dominant(tags: list[str]) -> tuple[str, str] | None:
    """First tag present in TAG_AXIS (list is severity-ordered, §10) → (tag, axis)."""
    for t in tags:
        axis = TAG_AXIS.get(t)
        if axis is not None:
            return t, axis
    return None


def project_event(event: Event, witness_state: NpcState, perc: float,
                  affinity_target: float = 0.0) -> dict:
    """Land one Event on one witness through both channels.

    ``perc`` = audibility/sight tier weight in [0..1] (0 → the witness didn't perceive → no delta).
    Returns ``{"dims": {…}, "rel": {…}}``:
      * ``dims`` — appraise-shaped, PRE-gain (goal_impact/desert/harm/fear/revulsion/intent). Feed
        straight into ``tick.appraise`` (Task 2.2); it applies each channel's emotion_gain.
      * ``rel`` — bystander relationship deltas: fear-of-actor, warmth-to-target, and the ``anchored``
        flag (True only when the witness IS the target — self-harm anchors; a bystander stays loose).

    VISCERAL: physical_threat × (base + familiar·fear_prior) × perc, damped by the witness's own
    approval of violence; care-for-target = affinity_target + empathy → distress/grief.
    MORAL LENS: dominant tag → worldview.morals[axis]. Negative stance → outrage (× taboo mult if the
    tag is a personal taboo); positive stance → grim-satisfaction joy. Un-enriched → both zero.
    """
    if perc <= 0.0:
        return _zero()

    wv = witness_state.config.worldview or {}
    morals = wv.get("morals") or {}
    taboos = set(wv.get("taboos") or [])
    traits = witness_state.config.traits or {}

    # ── VISCERAL ──────────────────────────────────────────────────────────────────────────────
    fear_prior = 0.0
    if event.actor:
        fear_prior = float(witness_state.rel(event.actor).get("fear", 0.0))
    viol_approval = max(0.0, float(morals.get("violence", 0.0)))
    harm = (event.physical_threat
            * (BRAIN["ev_harm_base"] + BRAIN["ev_harm_familiar"] * fear_prior)
            * perc
            * (1.0 - BRAIN["ev_viol_damp"] * viol_approval))
    care = affinity_target + BRAIN["ev_empathy_care"] * float(traits.get("empathy", 0.5))

    # ── MORAL LENS ────────────────────────────────────────────────────────────────────────────
    desert = outrage = approval = 0.0
    dom = _dominant(event.tags)
    if dom is not None:
        tag, axis = dom
        stance = float(morals.get(axis, 0.0))
        desert = stance
        outrage = max(0.0, -stance) * event.intensity * perc
        if tag in taboos:
            outrage *= BRAIN["ev_taboo_mult"]
        approval = max(0.0, stance) * event.intensity * perc * BRAIN["ev_approval_k"]

    goal_impact = -event.target_harm * care + approval
    control = BRAIN["ev_control_brave"] * float(traits.get("bravery", 0.5))

    # is_victim requires an actual violation signal (mapped tag or physical threat), not merely
    # target==witness — a bare structural match also covers gift recipients ("дар", untagged in
    # TAG_AXIS) and self-directed co-presence reads ("видит"), which must stay unharmed/no-op.
    is_victim = bool(event.target and event.target == witness_state.config.id
                     and (dom is not None or event.physical_threat > 0.0))

    if is_victim:                                    # VICTIM branch (U1, §3b) — the one struck
        harm = harm * BRAIN["ev_victim_harm_mult"]   # 0 stays 0 → no fear on a threatless crime
        goal_impact = min(goal_impact, -BRAIN["ev_victim_gi"])    # floor → distress + couples anger
        desert = min(desert, -BRAIN["ev_victim_desert"])          # floor → deserved-anger fires
        control = 0.0                                # no bravery agency-dampening under the blow

    dims = {
        "goal_impact": goal_impact,     # >0 grim satisfaction → joy; <0 distress/grief
        "desert": desert,               # stance sign gates anger in appraise (deserved → no anger)
        "harm": harm,                   # visceral danger → fear (appraise: harm×(1−control))
        "fear": harm,                   # NB: appraise derives fear from `harm`; this key is NOT read
        "revulsion": outrage,           # → disgust in appraise
        "intent": True,                 # a witnessed act is deliberate
        "control": control,             # agency dampens fear/distress in appraise (0 for the victim)
    }
    rel = {
        "actor_fear": ((BRAIN["ev_victim_rel_fear"] if is_victim and event.physical_threat > 0.0
                        else harm * BRAIN["ev_rel_fear"]) if event.actor else 0.0),
        "target_warmth": (BRAIN["ev_warmth"] * care
                          if event.target and event.target_harm <= 0.0 else 0.0),
        "anchored": is_victim,
        # NEW (U1): the grudge affinity ceiling the raw block wrote by hand; applied in the apply loop
        "victim_affinity": (-BRAIN["ev_victim_aff"] if is_victim else None),
        # NEW: gates gift-warmth to the beneficiary only (was the apply-loop `w == event.target` check)
        # `not is_victim` keeps a victim's grudge from being watered down by warmth on a threatless
        # crime (theft: target_harm==0 too) — a real victim event never also counts as a gift.
        "beneficiary": bool(event.target and event.target == witness_state.config.id
                            and event.target_harm <= 0.0 and not is_victim),
    }
    return {"dims": dims, "rel": rel}


def project_and_apply(event: Event, witnesses, perceive) -> None:
    """Land one Event on every witness who perceived it — the fan-out (МОЗГ Inc2, spec §3b).

    ``perceive(witness_state) -> perc[0..1]`` maps a witness to its perception tier weight from the
    audibility/sight machinery (same-zone/co-present → 1.0, farther → ev_perc_l2/l3, unperceived →
    0). For each perceiving witness (the actor never appraises its own act here): project the
    signature, apply the PRE-gain ``dims`` through ``tick.appraise`` (which multiplies each channel
    by the witness's ``emotion_gain``), then write the bystander relationship deltas onto the Inc1
    floor — fear-of-actor (loose unless the witness IS the target → anchored grudge), and, for a
    non-harmful act (a gift), warmth from the *beneficiary* toward the *giver* (gratitude; bystanders
    unmoved). Zero LLM — pure arithmetic per witness. Not every tick carries an Event; cost is bounded
    to the co-present crowd of a real act."""
    from .tick import appraise  # local import: mind/tick imports model → avoid a load cycle

    for w in witnesses:
        if event.actor and w.config.id == event.actor:
            continue
        perc = float(perceive(w) or 0.0)
        if perc <= 0.0:
            continue                                        # didn't hear/see → no delta at all
        aff_t = float(w.rel(event.target).get("affinity", 0.0)) if event.target else 0.0
        out = project_event(event, w, perc, affinity_target=aff_t)
        appraise(w, out["dims"], source=event.actor)
        r = out["rel"]
        if r["actor_fear"] > 0.0 and event.actor:
            rel = w.rel(event.actor)
            rel["fear"] = max(rel.get("fear", 0.0), r["actor_fear"])
            rel["anchored"] = rel.get("anchored", False) or r["anchored"]
        if r.get("victim_affinity") is not None and event.actor:   # U1: the victim's anchored grudge
            rel = w.rel(event.actor)
            rel["affinity"] = min(rel.get("affinity", 0.0), r["victim_affinity"])
            rel["anchored"] = True
        if r["target_warmth"] > 0.0 and event.actor and r.get("beneficiary"):
            rt = w.rel(event.actor)                         # beneficiary warms toward the giver
            rt["affinity"] = max(-1.0, min(1.0, rt.get("affinity", 0.0) + r["target_warmth"]))
            rt["anchored"] = True                            # gift acceptance is a real interaction
