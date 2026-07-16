"""project_event (МОЗГ Inc2): ONE kill signature, three worldview lenses — traced from
docs/superpowers/specs/2026-07-15-brain-design.md §5 Example A.

Two layers:
  * PRE-gain dims — project_event emits appraise-shaped dims BEFORE tick.appraise applies emotion_gain
    (harm/outrage/goal_impact). Deterministic; asserted tightly.
  * DEFINITIVE end-to-end — load the REAL enriched worldview of Мерек pool:0225 / Сельма pool:0645 /
    Освин pool:0102 from data/worlds.db, project the kill, pipe the dims through tick.appraise, and
    assert the resulting emotion table matches spec §5A. One signature row, three lands, delivered
    purely by the worldview slice — zero LLM.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from aidnd.mind import NpcConfig, NpcState, appraise
from aidnd.mind.event import Event
from aidnd.mind.project import project_event

_DB = Path(__file__).resolve().parents[2] / "data" / "worlds.db"

KILL = Event("pc", "npc:beggar", intensity=0.9, physical_threat=0.7, target_harm=1.0,
             tags=["убийство", "насилие", "смерть"], zone="стол у очага")


def _witness(name, traits, worldview):
    cfg = NpcConfig(id="npc:" + name, name=name, role="x", traits=traits, worldview=worldview)
    return NpcState.from_config(cfg)


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Layer 1 — PRE-gain dims (deterministic, worldview typed inline)
# ─────────────────────────────────────────────────────────────────────────────────────────────
def test_cultist_barely_stirred_faintly_glad():
    """Мерек pool:0225: morals.death +0.84, violence +0.83, empathy 0.16 — visceral fear damped by
    his approval of violence; no outrage (he approves); faint grim satisfaction."""
    m = _witness("merek", {"empathy": 0.16, "bravery": 0.78, "pride": 0.45},
                 {"morals": {"death": 0.84, "violence": 0.83}, "taboos": []})
    d = project_event(KILL, m, perc=1.0, affinity_target=0.0)["dims"]
    assert d["harm"] == pytest.approx(0.246, abs=0.01)   # 0.42 × (1−0.5·0.83)
    assert d["fear"] == pytest.approx(0.246, abs=0.01)   # alias of harm (pre-gain)
    assert d["revulsion"] == pytest.approx(0.0, abs=0.01)  # approves → no outrage
    assert d["goal_impact"] > 0                            # grim satisfaction → joy
    assert d["desert"] == pytest.approx(0.84, abs=0.01)


def test_shopkeeper_recoils_fear_disgust():
    """Сельма pool:0645: morals.death −0.23, violence −0.18, empathy 0.49, NO убийство taboo →
    outrage present but un-multiplied; distress from care-for-target."""
    s = _witness("selma", {"empathy": 0.49, "bravery": 0.52, "pride": 0.5},
                 {"morals": {"death": -0.23, "violence": -0.18},
                  "taboos": ["кощунство", "людоедство"]})
    d = project_event(KILL, s, perc=1.0, affinity_target=0.0)["dims"]
    assert d["harm"] == pytest.approx(0.42, abs=0.01)     # violence damp is max(0,−0.18)=0
    assert d["revulsion"] == pytest.approx(0.207, abs=0.01)  # 0.23×0.9, no taboo mult
    assert d["goal_impact"] < 0                            # distress


def test_priest_recoils_hardest_taboo_multiplied():
    """Освин pool:0102: morals.death −0.5, taboos∋убийство → outrage ×1.6."""
    o = _witness("osvin", {"empathy": 0.93, "bravery": 0.48, "pride": 0.5},
                 {"morals": {"death": -0.5, "violence": -1.0},
                  "taboos": ["убийство", "кощунство"]})
    d = project_event(KILL, o, perc=1.0, affinity_target=0.0)["dims"]
    assert d["revulsion"] == pytest.approx(0.72, abs=0.01)  # 0.5×0.9×1.6
    assert d["revulsion"] > 0.6


def test_unenriched_lens_noop_visceral_fires():
    """worldview={} → morals.get → 0 → moral channel silent; visceral still fires."""
    n = _witness("legacy", {"bravery": 0.5}, {})
    d = project_event(KILL, n, perc=1.0)["dims"]
    assert d["revulsion"] == 0.0     # moral channel silent
    assert d["goal_impact"] <= 0.0   # no approval joy
    assert d["harm"] > 0.0           # visceral still fires
    assert d["fear"] > 0.0


def test_no_perceive_no_delta():
    """perc=0 (witness didn't hear/see) → every dim numerically 0, no rel delta."""
    m = _witness("merek", {"bravery": 0.78}, {"morals": {"death": 0.84}})
    out = project_event(KILL, m, perc=0.0)
    assert all(v == 0.0 for v in out["dims"].values())
    assert out["rel"]["actor_fear"] == 0.0
    assert out["rel"]["target_warmth"] == 0.0


def test_self_harm_anchors_bystander_loose():
    """A witness who IS the target → anchored True (self-harm becomes a lasting grudge, Inc1 slow
    decay); a mere bystander stays loose (fast fade)."""
    victim = _witness("beggar", {"bravery": 0.5}, {})
    victim.config.id = "npc:beggar"
    assert project_event(KILL, victim, perc=1.0)["rel"]["anchored"] is True
    bystander = _witness("other", {"bravery": 0.5}, {})
    out = project_event(KILL, bystander, perc=1.0)["rel"]
    assert out["anchored"] is False
    assert out["actor_fear"] == pytest.approx(0.21, abs=0.02)  # harm 0.42 × ev_rel_fear 0.5


def test_control_emitted_from_bravery_dampens_fear():
    """control was never emitted anywhere (only sim.py's testbed set it) — appraise's
    fear = harm×(1−control) always saw control≡0. project_event now emits
    control = ev_control_brave(0.6) × bravery. Two witnesses, identical except bravery,
    diverge sharply in the resulting fear once piped through tick.appraise:

    harm = physical_threat(0.7) × (ev_harm_base 0.6 + ev_harm_familiar 0.4 × fear_prior 0)
           × perc(1.0) × (1 − ev_viol_damp 0.5 × viol_approval 0) = 0.7×0.6 = 0.42
    coward (bravery 0.1): control = 0.6×0.1 = 0.06 → fear_pre = 0.42×(1−0.06) = 0.3948
       × emotion_gain('fear') = 0.6+(1−0.1) = 1.5  → fear = 0.3948×1.5 = 0.5922
    brave  (bravery 0.9): control = 0.6×0.9 = 0.54 → fear_pre = 0.42×(1−0.54) = 0.1932
       × emotion_gain('fear') = 0.6+(1−0.9) = 0.7  → fear = 0.1932×0.7 = 0.13524
    """
    def _make(bravery):
        cfg = NpcConfig(id="npc:w", name="w", role="x",
                        traits={"bravery": bravery, "empathy": 0.5}, worldview={})
        return NpcState.from_config(cfg)

    coward, brave = _make(0.1), _make(0.9)
    d_coward = project_event(KILL, coward, perc=1.0)["dims"]
    d_brave = project_event(KILL, brave, perc=1.0)["dims"]
    assert d_coward["control"] == pytest.approx(0.06, abs=0.001)
    assert d_brave["control"] == pytest.approx(0.54, abs=0.001)

    appraise(coward, d_coward, source="pc")
    appraise(brave, d_brave, source="pc")
    assert coward.emotion["fear"] == pytest.approx(0.5922, abs=0.001)
    assert brave.emotion["fear"] == pytest.approx(0.13524, abs=0.001)
    assert brave.emotion["fear"] < coward.emotion["fear"] * 0.3   # substantially lower


def test_gift_warmth_only_no_fear():
    """A gift (target_harm 0, no threat) → warmth-to-target, no fear/outrage."""
    gift = Event("npc:0301", "npc:0142", intensity=0.2, physical_threat=0.0, target_harm=0.0,
                 tags=["дар"])
    w = _witness("w", {"empathy": 0.6}, {})
    out = project_event(gift, w, perc=1.0, affinity_target=0.3)
    assert out["dims"]["harm"] == 0.0
    assert out["dims"]["revulsion"] == 0.0
    assert out["rel"]["target_warmth"] > 0.0


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Layer 2 — DEFINITIVE: real DB worldview → project → tick.appraise → spec §5A emotion table
# ─────────────────────────────────────────────────────────────────────────────────────────────
def _real_state(pool_id: str) -> NpcState:
    if not _DB.exists():
        pytest.skip(f"worlds.db not present at {_DB}")
    con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT name, mech FROM people WHERE id=?", (pool_id,)).fetchone()
    finally:
        con.close()
    if row is None:
        pytest.skip(f"{pool_id} not in worlds.db (pool changed)")
    name, mech_json = row
    mech = json.loads(mech_json)
    cfg = NpcConfig(id=pool_id, name=name, role=mech.get("role", "x"),
                    traits=mech["traits"], worldview=mech["worldview"])
    return NpcState.from_config(cfg)


def _project_and_appraise(pool_id: str) -> dict:
    """The full Inc2→appraise pipeline on a real enriched NPC, returning its post-gain emotions."""
    st = _real_state(pool_id)
    dims = project_event(KILL, st, perc=1.0, affinity_target=0.0)["dims"]
    appraise(st, dims, source="pc")
    return {k: round(v, 3) for k, v in st.emotion.items()}


def test_specA_merek_cultist_calm_and_glad():
    """§5A Мерек pool:0225 (Багровый): joy ≈0.11, disgust 0 — barely stirred, faintly glad.

    control now emits from bravery (0.6·0.78=0.468, was 0 pre-fix), so fear drops from the old
    ≈0.20 to fear_pre(0.246)×(1−0.468)=0.131 × gain(0.6+(1−0.78)=0.82) ≈0.107; goal_impact/joy/
    disgust are untouched — control only enters fear/distress, not joy/disgust/anger."""
    e = _project_and_appraise("pool:0225")
    assert e["fear"] == pytest.approx(0.107, abs=0.03)
    assert e["joy"] == pytest.approx(0.11, abs=0.03)
    assert e["disgust"] == pytest.approx(0.0, abs=0.02)
    assert e["distress"] == pytest.approx(0.0, abs=0.02)


def test_specA_selma_shopkeeper_fear_and_disgust():
    """§5A Сельма pool:0645 (Светлая-Мать, no убийство taboo): disgust ≈0.22, anger ≈0.06 (both
    untouched by control). fear/distress drop with control=0.6·0.524=0.314 (was 0):
    fear_pre(0.42)×(1−0.314)=0.288 × gain(0.6+(1−0.524)=1.076) ≈0.31 (was ≈0.45);
    distress_pre(0.245)×(1−0.314)=0.168 × gain(0.6+(1−0.524)·0.5=0.838) ≈0.14 (was ≈0.21)."""
    e = _project_and_appraise("pool:0645")
    assert e["fear"] == pytest.approx(0.31, abs=0.03)
    assert e["disgust"] == pytest.approx(0.22, abs=0.03)
    assert e["distress"] == pytest.approx(0.14, abs=0.03)
    assert e["anger"] == pytest.approx(0.06, abs=0.03)
    assert e["joy"] == pytest.approx(0.0, abs=0.02)


def test_specA_osvin_priest_recoils_hardest():
    """§5A Освин pool:0102 (жрец, taboos∋убийство → ×1.6): disgust highest, anger at the killer —
    both untouched by control (disgust/anger derive from revulsion/desert, not harm/goal_impact).
    Real traits give disgust ≈0.79 / anger ≈0.24 (spec's 0.76/0.26 used rounded pride/irritability
    0.5 — see report drift note). control=0.6·0.478=0.287 (bravery 0.48, was 0) now damps
    fear/distress: fear_pre(0.42)×(1−0.287)=0.30 × gain(0.6+(1−0.478)=1.122) ≈0.336 (was ≈0.47);
    distress_pre(0.465)×(1−0.287)=0.332 × gain(0.6+(1−0.478)·0.5=0.861) ≈0.286 (was ≈0.40)."""
    e = _project_and_appraise("pool:0102")
    assert e["disgust"] == pytest.approx(0.79, abs=0.03)
    assert e["disgust"] > 0.6                              # taboo ×1.6 pushes it highest
    assert e["anger"] == pytest.approx(0.25, abs=0.03)
    assert e["distress"] == pytest.approx(0.286, abs=0.03)
    assert e["fear"] == pytest.approx(0.336, abs=0.03)
