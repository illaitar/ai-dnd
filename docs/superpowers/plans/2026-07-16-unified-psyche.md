# Единый контур психики (Unified Psyche) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** route every mutation of NPC psyche (emotion / emotion_target / relationship deltas) through ONE door (`Event`) and ONE apply sink (`_land`), deleting the five differently-shaped writers that mutate that state today — with pure-witness (bystander) paths byte-identical and today's victim outcomes reproduced within a ±0.1 band.

**Architecture:** Five entry adapters become five thin builders onto the existing `Event → project_event → tick.appraise` pipeline. U4 first stands up one knob registry (`mind/tunables.py`) so U1–U3 add victim/self knobs there. U1 folds the victim into a signature-driven branch of `project_event`. U2 extracts the per-witness apply into `_land()` and routes co-presence through it. U3 makes feel/need self-events entering `_land`. U5 moves the remaining brain logic (familiarity/greet/attention) back into `mind/` as pure moves.

**Tech Stack:** Python 3.14, pytest (`.venv/bin/pytest`), FastAPI play layer. No new dependencies. No LLM anywhere on this contour — pure arithmetic over `NpcState`.

## Global Constraints

Copied verbatim from spec §8 — every task's requirements implicitly include these:

- **No LLM fallback** — zero LLM on the whole contour; nothing to fall back from. An un-enriched witness → zeroed moral lens, never a canned stub.
- **No mechanical gates** — nothing is capped or cooled down; the victim branch models the missing world piece (the victim IS a witness) and feeds signature into the same prompt-agnostic arithmetic.
- **`mind/` cannot import the play layer** — `mind/tunables.py` is pure (stdlib only); `decay.py`/`project.py`/`value.py`/`social.py`/`attention.py` import it directly (same package); the play layer (`config.py`, `world.py`) imports FROM `mind/`, never the reverse.
- **Bystander projections byte-identical; victim tiers within ±0.10** — all pure-witness numbers, feel/need clamp results, co-presence emotion+seed, familiarity counter+seed, attention/greet/self_regard outputs, and all knob VALUES must not change. Only the U1 victim branch may move (attack victim anger 0.6→0.66, fear 0.6→0.59, rel-fear 0.85 exact, affinity −0.3→−0.40; theft victim anger 0.7→0.66, affinity −0.5→−0.40, no fear).
- **Suite stays green** — the full suite (772 tests today) is green after every task; each task ends green and is independently shippable.

**Run the full suite with:** `.venv/bin/pytest tests/ -q`

---

## File Structure (locked before tasks)

| File | Responsibility | Touched by |
|---|---|---|
| `src/aidnd/mind/tunables.py` (NEW) | `BRAIN` dict — the single brain-affect knob registry | U4 |
| `src/aidnd/mind/project.py` | Event projection + NEW victim branch + NEW `_land` sink + NEW `_nudge`/self-feeling arm | U4, U1, U2, U3 |
| `src/aidnd/mind/decay.py` | two-speed decay — reads `BRAIN` (was `_K`) | U4 |
| `src/aidnd/mind/value.py` | decision utilities — reads `BRAIN` for `sr_*`/`feel_nudge_cap` (was `BAL`) | U4 |
| `src/aidnd/mind/appraisal.py` | co-presence read (`impression`) unchanged; `appraise_present` routes through `_land` | U2 |
| `src/aidnd/mind/llm_agent.py` | act sites build Events; victim raw block DELETED; feel/need → self-event | U1, U3, U4 |
| `src/aidnd/mind/social.py` (NEW) | familiarity/greet pure logic (moved from `world.py`) | U5 |
| `src/aidnd/mind/attention.py` (NEW) | attention pure logic (moved from `world.py`) | U5 |
| `src/aidnd/server/play/engine/core.py` | `_witness_crime` victim raw block DELETED; victim joins the fan-out | U1 |
| `src/aidnd/server/play/engine/session/config.py` | `PB.update(BRAIN)` splice; brain-key literals removed | U4 |
| `src/aidnd/server/play/engine/world.py` | thin call-throughs to `social`/`attention` | U5 |
| `tests/mind/test_knob_sync.py` | 4 sync tests → 1 splice-guard | U4 |
| `tests/mind/test_victim_branch.py` (NEW) | victim tier acceptance (§4b/§5) | U1 |
| `tests/mind/test_anchored.py` | one victim-tier assertion updated (fear 0.6→0.59) | U1 |

**Task order (each independently green + shippable):** U4 → U1 → U2 → U3 → U5. U4 is FIRST so U1–U3 add their new knobs into `tunables.py`, not into the old mirror dicts. U2 (the `_land` extraction) precedes U3 (which adds the self-feeling arm to `_land`). U5 is last (pure moves) and depends on U4 for the knob source.

---

## Task 1 (U4): One knob registry — `mind/tunables.py`

**Files:**
- Create: `src/aidnd/mind/tunables.py`
- Modify: `src/aidnd/mind/project.py:25-33` (delete `_K`, import `BRAIN`, rename reads)
- Modify: `src/aidnd/mind/decay.py:12-18` (delete `_K`, import `BRAIN`, rename reads)
- Modify: `src/aidnd/mind/value.py:34-56` (drop `sr_*`/`feel_nudge_cap` from `BAL`, read `BRAIN`)
- Modify: `src/aidnd/mind/llm_agent.py:30,33-37` (`_nudge` reads `BRAIN`, drop `BAL` import)
- Modify: `src/aidnd/server/play/engine/session/config.py:14-50,270` (splice `PB.update(BRAIN)`)
- Test: `tests/mind/test_knob_sync.py` (rewrite: 4 tests → 1 splice-guard)

**Interfaces:**
- **Produces:** `aidnd.mind.tunables.BRAIN: dict` — the single brain-affect knob registry. Keys and values enumerated in Step 1. Later tasks import `from .tunables import BRAIN` (same-package) and read `BRAIN[...]`. `BRAIN` already carries the five NEW victim knobs (`ev_victim_*`), unused until Task 2.
- **Produces:** after `PB.update(BRAIN)`, every existing `PB["ev_…"]`/`PB["att_…"]`/`PB["sr_…"]`/`PB["decay_…"]`/`PB["familiarity_…"]`/`PB["greet_…"]`/`PB["feel_nudge_cap"]`/`PB["rel_faint_prior"]` read (in `world.py`, `voice.py`, tests) is unchanged and additionally sees the victim knobs.
- **Consumes:** nothing (this is the base task).

- [ ] **Step 1: Write the failing splice-guard test** (rewrite `tests/mind/test_knob_sync.py` in full)

```python
"""U4: ONE brain-knob registry — mind/tunables.BRAIN is the single source for every brain-affect
knob. PB splices it (PB.update(BRAIN)); decay/project/value read BRAIN directly. This one
splice-guard replaces the four per-mirror sync tests (decay/project/feel_nudge/self_regard): if the
splice ever drops or overrides a brain key, PB[k] != BRAIN[k] and this fails. Spec §4c/§5-U4/§10."""
from aidnd.mind.tunables import BRAIN
from aidnd.server.play.engine.session.config import PB


def test_pb_reexports_brain_tunables():
    # every brain knob is present in PB with the same value — the splice dropped/overrode nothing
    for k in BRAIN:
        assert PB[k] == BRAIN[k], f"PB[{k!r}] ({PB[k]!r}) != BRAIN[{k!r}] ({BRAIN[k]!r})"


def test_pb_carries_new_victim_knobs():
    # the five NEW U1 victim knobs are born in tunables and reach PB through the splice
    for k in ("ev_victim_harm_mult", "ev_victim_gi", "ev_victim_desert",
              "ev_victim_aff", "ev_victim_rel_fear"):
        assert k in PB and PB[k] == BRAIN[k]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/mind/test_knob_sync.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'aidnd.mind.tunables'`

- [ ] **Step 3: Create `src/aidnd/mind/tunables.py`**

```python
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
```

- [ ] **Step 4: Rewire `src/aidnd/mind/project.py`** — replace the `_K = {…}` block (lines 25-33) with a `BRAIN` import, and change every `_K[` read to `BRAIN[`.

Replace lines 25-33:

```python
# mirror of the ev_* PB knobs (§4.6) — mind/ is import-clean of the play layer, matching value.BAL
# and mind.decay._K. session/config.py:PB is the canonical source; keep the two in sync.
_K = {
    "ev_perc_l2": 0.6, "ev_perc_l3": 0.3,
    "ev_harm_base": 0.6, "ev_harm_familiar": 0.4, "ev_viol_damp": 0.5,
    "ev_empathy_care": 0.5, "ev_taboo_mult": 1.6, "ev_approval_k": 0.25,
    "ev_rel_fear": 0.5, "ev_rel_aff": 0.4, "ev_warmth": 0.2,
    "ev_control_brave": 0.6,  # смелость свидетеля гасит страх/дистресс — control=к·bravery
}
```

with:

```python
from .tunables import BRAIN  # the single brain-affect knob registry (U4) — one source for ev_*
```

Then change the four `_K[` reads inside `project_event` (lines 82, 84, 85, 95, 97, 110, 116, 117) to `BRAIN[`. The exact reads to rename: `_K["ev_harm_base"]`, `_K["ev_harm_familiar"]`, `_K["ev_viol_damp"]`, `_K["ev_empathy_care"]`, `_K["ev_taboo_mult"]`, `_K["ev_approval_k"]`, `_K["ev_control_brave"]`, `_K["ev_rel_fear"]`, `_K["ev_warmth"]` → each becomes `BRAIN["…"]`. (Use `sed -i '' 's/_K\["ev_/BRAIN["ev_/g' src/aidnd/mind/project.py` after the `_K` dict is deleted, then verify no `_K[` remains.)

- [ ] **Step 5: Rewire `src/aidnd/mind/decay.py`** — replace the `_K = {…}` block (lines 12-18) with a `BRAIN` import and rename reads.

Replace lines 12-18:

```python
# mirror of the PB knobs (§4.6) — mind/ is import-clean of the play layer, matching value.BAL.
_K = {
    "decay_emo_days": 0.5,
    "decay_rel_anchored_days": 14.0,
    "decay_rel_loose_days": 2.0,
    "rel_faint_prior": 0.10,
}
```

with:

```python
from .tunables import BRAIN  # the single brain-affect knob registry (U4) — one source for decay_*
```

Then change the four `_K[` reads inside `decay_lazy` (lines 48, 56, 58, 63) to `BRAIN[`: `_K["decay_emo_days"]`, `_K["decay_rel_anchored_days"]`, `_K["rel_faint_prior"]`, `_K["decay_rel_loose_days"]`.

- [ ] **Step 6: Rewire `src/aidnd/mind/value.py`** — drop `feel_nudge_cap`/`sr_*` from the `BAL` literal and read them from `BRAIN`.

Add the import after line 32 (`from .world import ENEMY_FACTIONS`):

```python
from .tunables import BRAIN  # sr_*, feel_nudge_cap now single-sourced (U4)
```

Delete these lines from the `BAL` dict literal (lines 49-55):

```python
    "feel_nudge_cap": 0.25,   # mirrors PB["feel_nudge_cap"] (session/config.py) — mind-internal
                              # consumer (llm_agent.py) can't import play-layer PB (import cycle)
    # self_regard (§4.5/§4.6) — derived over/under-confidence biasing the PERCEIVED pwin the
    # DECISION reads. Mirrors PB["sr_*"]; voice.py's boast beat uses the same PB weights (import
    # cycle keeps them separate — guarded by tests/mind/test_knob_sync.py).
    "sr_pride": 0.35, "sr_brave": 0.35, "sr_amb": 0.30,   # self_regard trait weights
    "sr_span": 1.5,                                        # perceived-pwin bias span around 0.5
```

Change `self_regard` (lines 84-86) to read `BRAIN`:

```python
    return _clamp(BRAIN["sr_pride"] * T(state, "pride")
                  + BRAIN["sr_brave"] * T(state, "bravery")
                  + BRAIN["sr_amb"] * T(state, "ambition"))
```

Change `perceived_pwin` (line 95) to read `BRAIN`:

```python
    bias = 1.0 + BRAIN["sr_span"] * (self_regard(state) - 0.5)
```

- [ ] **Step 7: Rewire `src/aidnd/mind/llm_agent.py` `_nudge`** — read `BRAIN["feel_nudge_cap"]`, drop the `BAL` import.

Replace line 30:

```python
from .value import BAL  # feel_nudge_cap (mirrors PB — importing PB here cycles play↔mind)
```

with:

```python
from .tunables import BRAIN  # feel_nudge_cap single-sourced (U4); play-layer PB would cycle
```

Replace the `_nudge` body (line 36):

```python
    cap = BAL["feel_nudge_cap"]
```

with:

```python
    cap = BRAIN["feel_nudge_cap"]
```

- [ ] **Step 8: Splice `BRAIN` into `PB`** — `src/aidnd/server/play/engine/session/config.py`.

Add the import after line 12 (`PLAYER = "pc"`):

```python
from aidnd.mind.tunables import BRAIN  # brain-affect knobs single-sourced in mind/ (U4); spliced below
```

Delete the brain-key block from the `PB` literal — replace lines 20-50 (from the `# МОЗГ — affect two-speed lazy decay…` comment through the `"att_asleep": … "att_alert": 1.3,` line) with a single pointer comment:

```python
    # МОЗГ brain-affect knobs (decay/ev_*/familiarity/greet/feel_nudge/sr_*/att_*) live in ONE
    # registry — aidnd.mind.tunables.BRAIN — and are spliced into PB below (U4). See tunables.py.
```

Then, immediately after the `PB = { … }` dict closes (the `}` at line 270) and BEFORE `_GT0 = PB["start_gt"]`, insert:

```python
PB.update(BRAIN)  # U4: single-source the brain-affect knobs; guarded by tests/mind/test_knob_sync.py
```

- [ ] **Step 9: Run the splice-guard + the mind suite to verify green**

Run: `.venv/bin/pytest tests/mind/test_knob_sync.py tests/mind/ tests/play/ -q`
Expected: PASS. The rewritten `test_knob_sync.py` (2 tests) passes; every existing decay/project/feel/self_regard/attention/greet test still passes (values byte-identical through the splice).

- [ ] **Step 10: Verify no stray `_K` reference remains and run the full suite**

Run: `grep -rn '\b_K\b\|_PK\|BAL\["feel_nudge\|BAL\["sr_' src/aidnd/mind/ tests/mind/test_knob_sync.py`
Expected: no output (all `_K`/`_PK` references removed; `feel_nudge_cap`/`sr_*` no longer read from `BAL`).

Run: `.venv/bin/pytest tests/ -q`
Expected: PASS, 772 tests (same count — 4 sync tests removed, 2 added, net still green suite).

- [ ] **Step 11: Commit**

```bash
git add src/aidnd/mind/tunables.py src/aidnd/mind/project.py src/aidnd/mind/decay.py \
        src/aidnd/mind/value.py src/aidnd/mind/llm_agent.py \
        src/aidnd/server/play/engine/session/config.py tests/mind/test_knob_sync.py
git commit -m "refactor(mind): один реестр настроек tunables.BRAIN — PB.update сплайс, 4 sync-теста → 1 сплайс-гард"
```

---

## Task 2 (U1): Victim = a signature-driven branch of `project_event`

**Files:**
- Modify: `src/aidnd/mind/project.py` (`project_event` NEW victim branch; `project_and_apply` NEW victim-affinity apply arm)
- Modify: `src/aidnd/mind/llm_agent.py:415-432` (DELETE the raw victim affect block, keep memory line; `exclude=(tb.id,)` → `exclude=()`)
- Modify: `src/aidnd/server/play/engine/core.py:397-418` (`_witness_crime`: DELETE the raw victim affect block, keep memory line; include the victim in the fanned witnesses)
- Test: `tests/mind/test_victim_branch.py` (NEW — victim tier acceptance)
- Test: `tests/mind/test_anchored.py:65` (update the one victim-tier assertion 0.6→0.59)

**Interfaces:**
- **Consumes:** `aidnd.mind.tunables.BRAIN` (Task 1) — reads `ev_victim_harm_mult`, `ev_victim_gi`, `ev_victim_desert`, `ev_victim_aff`, `ev_victim_rel_fear`, plus the existing `ev_*`.
- **Produces:** `project_event(event, witness_state, perc, affinity_target=0.0) -> {"dims": dict, "rel": dict}` — unchanged signature. When `event.target == witness_state.config.id` the `dims` carry the victim tier and `rel` gains `"victim_affinity": float|None` and `"beneficiary": bool`. Bystander (`event.target != witness.id`) output is byte-identical to today.
- **Produces:** `project_and_apply(event, witnesses, perceive) -> None` — unchanged signature; the apply loop now also writes the victim's anchored grudge (`affinity = min(cur, victim_affinity)`) and gates gift-warmth on `rel["beneficiary"]`. Later tasks (U2) extract this loop body into `_land`.

- [ ] **Step 1: Write the failing victim-branch test** — `tests/mind/test_victim_branch.py`

```python
"""U1: the victim = a signature-driven branch of project_event (event.target == witness.id). ONE
formula reproduces both raw victim blocks (attack + theft) within ±0.1. The whole affect lands
through project_and_apply (the same door as bystanders); the act sites keep only their memory line.
Bystander numbers are byte-identical (branch not taken — guarded in test_project_event.py). Spec
§3b/§4b/§5-U1."""
from __future__ import annotations

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.mind.event import Event
from aidnd.mind.project import project_and_apply, project_event


def _victim(vid, morals):
    cfg = NpcConfig(id=vid, name=vid, role="x", worldview={"morals": morals})
    return NpcState.from_config(cfg)   # NpcConfig defaults every trait to 0.5


def test_attack_victim_dims_reproduce_today_within_band():
    """A attacks B (12→6 hp): Event(A,B, intensity 0.6, threat 0.5, harm 0.5, [«насилие»]).
    Victim branch: visceral harm 0.30×1.8=0.54, gi floor −0.8, desert floor −0.75, control 0."""
    ev = Event("npc:att", "npc:vic", 0.6, 0.5, 0.5, ["насилие"])
    b = _victim("npc:vic", {"violence": -0.3})
    d = project_event(ev, b, perc=1.0, affinity_target=0.0)["dims"]
    assert d["harm"] == pytest.approx(0.54, abs=0.01)
    assert d["goal_impact"] == pytest.approx(-0.8, abs=0.01)
    assert d["desert"] == pytest.approx(-0.75, abs=0.01)
    assert d["control"] == pytest.approx(0.0, abs=0.001)


def test_attack_victim_end_to_end_grudge_and_emotion():
    """Through the real door (project_and_apply): B's tier reproduces today's 0.6/0.6/0.85/−0.3
    within ±0.1 → anger 0.66, fear 0.59, rel-fear 0.85, affinity −0.40, anchored."""
    ev = Event("npc:att", "npc:vic", 0.6, 0.5, 0.5, ["насилие"])
    b = _victim("npc:vic", {"violence": -0.3})
    project_and_apply(ev, [b], perceive=lambda w: 1.0)
    assert b.emotion["anger"] == pytest.approx(0.66, abs=0.02)
    assert b.emotion["fear"] == pytest.approx(0.59, abs=0.02)
    assert b.emotion["distress"] == pytest.approx(0.68, abs=0.03)   # in-band addition (being attacked IS distressing)
    assert b.emotion["disgust"] == pytest.approx(0.20, abs=0.03)    # in-band addition
    assert b.emotion_target["anger"] == "npc:att"
    r = b.rel("npc:att")
    assert r["affinity"] == pytest.approx(-0.40, abs=0.001)
    assert r["fear"] == pytest.approx(0.85, abs=0.001)
    assert r["anchored"] is True


def test_theft_victim_no_fear_anger_from_desert_floor():
    """Pickpocket: Event(PLAYER,npc, intensity 0.4, threat 0, harm 0, [«воровство»]). Threatless →
    visceral harm 0×1.8=0 → NO fear (matches today). Anger still fires from the desert floor;
    grudge affinity −0.40, anchored."""
    ev = Event("pc", "npc:vic", 0.4, 0.0, 0.0, ["воровство"])
    v = _victim("npc:vic", {"theft": -0.5})
    project_and_apply(ev, [v], perceive=lambda w: 1.0)
    assert v.emotion["fear"] == pytest.approx(0.0, abs=0.001)       # no fear on a pickpocket (exact)
    assert v.emotion["anger"] == pytest.approx(0.66, abs=0.02)
    r = v.rel("pc")
    assert r["affinity"] == pytest.approx(-0.40, abs=0.001)
    assert r["fear"] == pytest.approx(0.0, abs=0.001)               # threat 0 → rel-fear NOT set
    assert r["anchored"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/mind/test_victim_branch.py -q`
Expected: FAIL — today `project_event` has no victim branch (`d["harm"]` is 0.30 not 0.54; `project_and_apply` writes no grudge affinity).

- [ ] **Step 3: Add the victim branch to `project_event`** — `src/aidnd/mind/project.py`.

Replace the body of `project_event` FROM the `# ── VISCERAL ──` comment THROUGH the `return {"dims": dims, "rel": rel}` line with the version below (adds `is_victim`, the victim tier, and the `victim_affinity`/`beneficiary` rel keys; the bystander path is unchanged arithmetic):

```python
    is_victim = bool(event.target and event.target == witness_state.config.id)

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
        "beneficiary": bool(event.target and event.target == witness_state.config.id
                            and event.target_harm <= 0.0),
    }
    return {"dims": dims, "rel": rel}
```

(Note: the local `traits = witness_state.config.traits or {}` line above `# ── VISCERAL ──` and the `wv`/`morals`/`taboos` lines and the `if perc <= 0.0: return _zero()` gate all stay unchanged, above this replaced block.)

- [ ] **Step 4: Add the victim-affinity apply arm to `project_and_apply`** — `src/aidnd/mind/project.py`.

Replace the apply loop body (the `for w in witnesses:` block, from `appraise(w, out["dims"], source=event.actor)` through the gift-warmth arm) with:

```python
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
```

(The gift-warmth gate moved from `w.config.id == event.target` to the projected `r["beneficiary"]` flag — byte-identical: `beneficiary` is exactly `event.target == witness.id and target_harm <= 0`, and a bystander to a gift got `target_warmth` skipped before and now gets `beneficiary` False.)

- [ ] **Step 5: Run the victim test — verify it passes**

Run: `.venv/bin/pytest tests/mind/test_victim_branch.py -q`
Expected: PASS (all 3 tests).

- [ ] **Step 6: Delete the raw victim block in `apply_actions`** — `src/aidnd/mind/llm_agent.py`.

Replace lines 415-425 (the `vs = …` through `vs.memory.add(…)` block) and line 432 (`exclude=(tb.id,)`) as follows.

Replace:

```python
                vs = world.npc_minds.get(tb.id) if hasattr(world, "npc_minds") else None
                if vs is not None:
                    r = vs.rel(me.id)
                    r["fear"] = max(r["fear"], 0.85)
                    r["affinity"] = min(r["affinity"], -0.3)
                    r["anchored"] = True                 # прямое насилие → стойкая обида (медленный спад)
                    vs.emotion["fear"] = min(1.0, vs.emotion.get("fear", 0.0) + 0.6)
                    vs.emotion_target["fear"] = me.id
                    vs.emotion["anger"] = min(1.0, vs.emotion.get("anger", 0.0) + 0.6)
                    vs.emotion_target["anger"] = me.id
                    vs.memory.add(f"{me.id} напал на меня", clock, importance=0.9, kind="event", about=[me.id])
                killed = tb.down()
```

with (keep ONLY the first-person memory line; affect is now owned by the victim branch of the fan-out):

```python
                vs = world.npc_minds.get(tb.id) if hasattr(world, "npc_minds") else None
                if vs is not None:                       # U1: affect owned by project_event's victim
                    vs.memory.add(f"{me.id} напал на меня", clock, importance=0.9,  # branch now; keep
                                  kind="event", about=[me.id])                        # the memory line
                killed = tb.down()
```

And change the fan-out (line 432) to STOP excluding the victim:

```python
                        me.place, exclude=())            # U1: victim included → hits the victim branch
```

- [ ] **Step 7: Delete the raw victim block in `_witness_crime`** — `src/aidnd/server/play/engine/core.py`.

Replace lines 400-408 (the `p = people[npc]` through `_crime_affect(…)` block):

```python
    p = people[npc]
    rel = p.state.rel(PLAYER)
    rel["affinity"] = min(rel["affinity"], -0.5)
    rel["anchored"] = True                               # обида жертвы — медленный носитель (§4.3)
    p.state.emotion["anger"] = min(1.0, p.state.emotion.get("anger", 0) + 0.7)
    p.state.emotion_target["anger"] = PLAYER
    p.state.memory.add(f"чужак {what} — я этого не забуду!", _mt(), 0.9, about=[PLAYER])
    wit = [w for w in _here(loc, crof) if w != npc]
    _crime_affect(people, wit, npc, what, loc)               # МОЗГ Inc2: bystanders FEEL it, not only remember
```

with (keep the first-person memory line; the victim now rides the fan-out via the victim branch):

```python
    p = people[npc]
    p.state.memory.add(f"чужак {what} — я этого не забуду!", _mt(), 0.9, about=[PLAYER])
    wit = [w for w in _here(loc, crof) if w != npc]         # bystanders (memory + wanted below)
    # U1: the victim rides the SAME fan-out — target=npc hits project_event's victim branch; affect
    # (grudge + anger/fear) is owned there now, no hand-write. Bystanders still only remember.
    _crime_affect(people, [npc] + wit, npc, what, loc)
```

- [ ] **Step 8: Update the one victim-tier assertion in `test_anchored.py`** — `tests/mind/test_anchored.py:65`.

The attack victim's fear moves from the raw block's 0.6 to the branch's 0.59 (in-band, §7). Replace line 65:

```python
    assert victim.emotion["fear"] >= 0.6
```

with:

```python
    assert victim.emotion["fear"] == pytest.approx(0.59, abs=0.02)  # U1 victim tier (was raw 0.6)
```

(The next assertion `victim.emotion["anger"] >= 0.6` still holds — the branch gives 0.66. Add `import pytest` at the top of the file if not already present — it is imported at line 12.)

- [ ] **Step 9: Run the affected suites — verify green**

Run: `.venv/bin/pytest tests/mind/test_victim_branch.py tests/mind/test_anchored.py tests/mind/test_project_event.py tests/play/test_event_bus.py tests/play/test_menace_brandish.py tests/play/test_crime_signature.py -q`
Expected: PASS. Victim tiers reproduce today within ±0.1; every bystander test (`test_project_event`, `test_event_bus`, `test_menace_brandish`, `test_crime_signature`) is byte-identical (bystander branch untouched).

- [ ] **Step 10: Run the full suite**

Run: `.venv/bin/pytest tests/ -q`
Expected: PASS, 775 tests (3 added in `test_victim_branch.py`).

- [ ] **Step 11: Commit**

```bash
git add src/aidnd/mind/project.py src/aidnd/mind/llm_agent.py \
        src/aidnd/server/play/engine/core.py tests/mind/test_victim_branch.py \
        tests/mind/test_anchored.py
git commit -m "feat(mind): жертва — ветвь project_event по сигнатуре; удалены оба сырых блока аффекта жертвы"
```

---

## Task 3 (U2): Co-presence through the shared `_land` sink

**Files:**
- Modify: `src/aidnd/mind/project.py` (extract `_land(state, dims, rel, source=None, seed=None)` from the `project_and_apply` loop body; `project_and_apply` calls it)
- Modify: `src/aidnd/mind/appraisal.py:105-133` (`appraise_present` routes each present other through `_land` instead of poking `appraise` + `state.relationships` directly)
- Test: `tests/mind/test_land_sink.py` (NEW — the sink + co-presence parity)

**Interfaces:**
- **Consumes:** `project_event` + the victim/gift `rel` shape from Task 2; `BRAIN` from Task 1.
- **Produces:** `_land(state, dims, rel, source=None, seed=None) -> None` — the ONE apply sink. Applies `dims` through `tick.appraise(state, dims, source)`, then the `rel` writes (`actor_fear`, `victim_affinity`, `target_warmth`/`beneficiary`, all keyed on `source`), then, if `seed` is not None, the once-only relationship prior + memory note. `seed` shape: `{"prior": dict, "remember": str|None, "clock": int, "once": bool}`. Later tasks (U3) add a `feel=` keyword to `_land`.
- **Produces:** `project_and_apply` unchanged externally; its loop body is now one `_land(w, out["dims"], out["rel"], source=event.actor)` call.

- [ ] **Step 1: Write the failing `_land` test** — `tests/mind/test_land_sink.py`

```python
"""U2: ONE apply sink — _land(state, dims, rel, source, seed). Co-presence, the fan-out, and (U3)
self-feeling all write NpcState through it, so there is exactly one place emotion/emotion_target/
relationships get mutated. Co-presence emotion + the once-seed are byte-identical to the old
appraise_present (same impression → same appraise, same prior, same skip rules). Spec §3/§5-U2."""
from __future__ import annotations

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.mind.project import _land


def _st(sid):
    return NpcState.from_config(NpcConfig(id=sid, name=sid, role="x"))


def test_land_appraises_and_writes_actor_fear():
    st = _st("npc:w")
    dims = {"goal_impact": 0.0, "desert": 0.0, "harm": 0.4, "fear": 0.4,
            "revulsion": 0.0, "intent": True, "control": 0.0}
    rel = {"actor_fear": 0.2, "target_warmth": 0.0, "anchored": False,
           "victim_affinity": None, "beneficiary": False}
    _land(st, dims, rel, source="npc:a")
    assert st.emotion["fear"] > 0.0
    assert st.emotion_target["fear"] == "npc:a"
    assert st.rel("npc:a")["fear"] == pytest.approx(0.2, abs=0.001)
    assert st.rel("npc:a")["anchored"] is False


def test_land_seed_arm_seeds_prior_once():
    st = _st("npc:w")
    dims = {"goal_impact": 0.1, "desert": 0.0, "harm": 0.0, "fear": 0.0,
            "revulsion": 0.0, "intent": False, "control": 0.0}
    rel = {}
    seed = {"prior": {"affinity": 0.3, "fear": 0.0, "trust": 0.2}, "remember": "приятный тип",
            "clock": 5, "once": True}
    _land(st, dims, rel, source="npc:o", seed=seed)
    assert st.rel("npc:o")["affinity"] == pytest.approx(0.3, abs=0.001)   # seeded
    # a SECOND land with a different prior must NOT overwrite (once-guard: already known)
    seed2 = {"prior": {"affinity": -0.9, "fear": 0.0, "trust": 0.0}, "remember": None,
             "clock": 6, "once": True}
    _land(st, dims, rel, source="npc:o", seed=seed2)
    assert st.rel("npc:o")["affinity"] == pytest.approx(0.3, abs=0.001)   # unchanged — once only
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/mind/test_land_sink.py -q`
Expected: FAIL with `ImportError: cannot import name '_land'`.

- [ ] **Step 3: Extract `_land` and rewire `project_and_apply`** — `src/aidnd/mind/project.py`.

Add `_land` immediately ABOVE `project_and_apply` (after `project_event` returns):

```python
def _land(state, dims, rel, source=None, seed=None) -> None:
    """THE apply sink (U2). Every writer — the fan-out, co-presence, (U3) self-feeling — lands its
    already-projected `dims`/`rel` on ONE witness through here, so emotion/emotion_target/relationships
    are mutated in exactly one place. `dims` → tick.appraise (×emotion_gain); `rel` → the bystander/
    victim/beneficiary relationship writes (keyed on `source`); `seed` (co-presence only) → the
    once-only relationship prior + memory note. Zero LLM. Spec §3b/§5-U2."""
    from .tick import appraise  # local import: mind/tick imports model → avoid a load cycle

    appraise(state, dims, source=source)
    if source:
        if rel.get("actor_fear", 0.0) > 0.0:
            r = state.rel(source)
            r["fear"] = max(r.get("fear", 0.0), rel["actor_fear"])
            r["anchored"] = r.get("anchored", False) or rel.get("anchored", False)
        if rel.get("victim_affinity") is not None:               # the victim's anchored grudge (U1)
            r = state.rel(source)
            r["affinity"] = min(r.get("affinity", 0.0), rel["victim_affinity"])
            r["anchored"] = True
        if rel.get("target_warmth", 0.0) > 0.0 and rel.get("beneficiary"):
            r = state.rel(source)                                # beneficiary warms toward the giver
            r["affinity"] = max(-1.0, min(1.0, r.get("affinity", 0.0) + rel["target_warmth"]))
            r["anchored"] = True
    if seed is not None and source:                              # co-presence once-seed (U2)
        if seed.get("once") and source in state.relationships:
            return                                               # already know them — no re-seed
        prior = seed.get("prior")
        if prior is not None:
            state.relationships[source] = dict(prior)
            remember = seed.get("remember")
            if remember:
                state.memory.add(remember, seed.get("clock", 0), importance=0.4, about=[source])
```

Then replace the ENTIRE `for w in witnesses:` loop body inside `project_and_apply` with a single `_land` call:

```python
    for w in witnesses:
        if event.actor and w.config.id == event.actor:
            continue
        perc = float(perceive(w) or 0.0)
        if perc <= 0.0:
            continue                                        # didn't hear/see → no delta at all
        aff_t = float(w.rel(event.target).get("affinity", 0.0)) if event.target else 0.0
        out = project_event(event, w, perc, affinity_target=aff_t)
        _land(w, out["dims"], out["rel"], source=event.actor)
```

(Remove the now-obsolete `from .tick import appraise` line at the top of `project_and_apply` — `_land` owns the import.)

- [ ] **Step 4: Run `_land` + the fan-out regression suites — verify green**

Run: `.venv/bin/pytest tests/mind/test_land_sink.py tests/mind/test_victim_branch.py tests/mind/test_anchored.py tests/play/test_event_bus.py tests/play/test_menace_brandish.py -q`
Expected: PASS. The fan-out lands exactly as before (same `dims`/`rel`, same writes) — every victim/bystander test byte-identical.

- [ ] **Step 5: Write the failing co-presence-parity test** — append to `tests/mind/test_land_sink.py`

```python
def test_appraise_present_routes_through_land_byte_identical():
    """appraise_present now calls _land, but co-presence emotion + the once-seed are byte-identical:
    an ordinary NPC seeing a neutral stranger seeds a relationship prior once and moves emotion."""
    from types import SimpleNamespace

    from aidnd.mind.appraisal import _race_rel, appraise_present
    from aidnd.mind.world import Body

    st = _st("npc:me")
    other = Body("npc:you", "площадь", appearance=0.6, charisma=0.5)
    percept = SimpleNamespace(present=[other])
    world = SimpleNamespace(clock=3)
    appraise_present(st, world, percept, _race_rel(), skip_seed_id=None)
    assert "npc:you" in st.relationships          # a stranger got a prior seeded (once)
    prior = dict(st.relationships["npc:you"])
    # a second pass must NOT re-seed (already known) — the once-guard survives the _land move
    appraise_present(st, world, percept, _race_rel(), skip_seed_id=None)
    assert st.relationships["npc:you"] == prior


def test_appraise_present_never_seeds_the_player():
    from types import SimpleNamespace

    from aidnd.mind.appraisal import _race_rel, appraise_present
    from aidnd.mind.world import Body

    st = _st("npc:me")
    pc = Body("pc", "площадь", appearance=0.6, charisma=0.5)
    percept = SimpleNamespace(present=[pc])
    world = SimpleNamespace(clock=3)
    appraise_present(st, world, percept, _race_rel(), skip_seed_id="pc")
    assert "pc" not in st.relationships           # stranger stays a stranger from mere sight
```

- [ ] **Step 6: Run to verify the parity test fails on the second-pass / behavior only if appraise_present not yet routed**

Run: `.venv/bin/pytest tests/mind/test_land_sink.py::test_appraise_present_routes_through_land_byte_identical -q`
Expected: PASS already (the CURRENT `appraise_present` also seeds once) — this test is a *guard* that the U2 rewrite in Step 7 keeps it byte-identical. If it passes now, that's fine; proceed to Step 7 and re-run to confirm it still passes after the rewrite.

- [ ] **Step 7: Route `appraise_present` through `_land`** — `src/aidnd/mind/appraisal.py`.

Replace the `for other in percept.present:` loop body (lines 122-133) with:

```python
    from .project import _land  # local import: project imports tick → keep it lazy, no load cycle

    clock = getattr(world, "clock", 0)
    for other in percept.present:
        if other.id == state.config.id:
            continue
        imp = impression(state, other, race_rel)
        seed = None
        if other.id not in state.relationships and other.id != skip_seed_id:
            seed = {"prior": imp.prior, "remember": imp.remember, "clock": clock, "once": True}
        # the flat presence read is the payload (a bare Event carries no appearance/armed/charisma →
        # would DESTROY the tier-a/b/c content); _land is the ONE sink for the mutation (§5-U2).
        _land(state, imp.emo, rel={}, source=other.id, seed=seed)
```

(Delete the old `from .tick import appraise` local import at the top of the function and the direct `appraise(...)` + `state.relationships[...] =` + `state.memory.add(...)` pokes — `_land` owns them now. The `clock = getattr(...)` line moves into the block above as shown.)

- [ ] **Step 8: Run the co-presence + appraisal suites — verify green**

Run: `.venv/bin/pytest tests/mind/test_land_sink.py tests/mind/test_appraisal.py -q`
Expected: PASS. Co-presence emotion + once-seed byte-identical; the player is never auto-seeded.

- [ ] **Step 9: Run the full suite**

Run: `.venv/bin/pytest tests/ -q`
Expected: PASS, 780 tests (5 added in `test_land_sink.py`).

- [ ] **Step 10: Commit**

```bash
git add src/aidnd/mind/project.py src/aidnd/mind/appraisal.py tests/mind/test_land_sink.py
git commit -m "refactor(mind): единый sink _land — фан-аут и со-присутствие пишут состояние через одну дверь"
```

---

## Task 4 (U3): feel / need = self-event through the same door

**Files:**
- Modify: `src/aidnd/mind/project.py` (move `_nudge` here beside `_land`; add the self-feeling arm to `_land` via a `feel=` keyword)
- Modify: `src/aidnd/mind/llm_agent.py:33-37,492-501` (delete the local `_nudge`; feel/need handlers build a self-event and route through `_land`)
- Test: `tests/mind/test_self_feel.py` (NEW — self-event boundary + emotion-target)

**Interfaces:**
- **Consumes:** `_land` (Task 2), `BRAIN` (Task 1), `aidnd.mind.event.Event`.
- **Produces:** `_nudge(cur: float, want: float) -> float` in `project.py` (moved from `llm_agent.py`) — `round(clamp01(cur + clamp(want − cur, ±feel_nudge_cap)), 6)`.
- **Produces:** `_land(state, dims, rel, source=None, seed=None, feel=None) -> None` — when `feel` is not None (`{"channel": str, "want": float, "need": bool}`), `_land` takes the self-feeling arm: nudge the named channel in `state.emotion` (or `state.needs` if `feel["need"]`) via `_nudge`, set `emotion_target[channel] = source` for an emotion channel, and skip appraise/rel entirely. Byte-identical clamp result to today's `_nudge` write.

- [ ] **Step 1: Write the failing self-feel test** — `tests/mind/test_self_feel.py`

```python
"""U3: feel/need = a deliberate self-event through the SAME door. actor==target==me → the sink's
self-feeling arm NUDGES the named channel by ±feel_nudge_cap (self-regulation, NOT an appraisal of
an external act), preserving the grudge/hunger the model cannot erase in one call. Clamp result is
byte-identical to the old _nudge; the emotion channel now also self-targets. Spec §5-U3."""
from __future__ import annotations

from aidnd.mind import NpcConfig, NpcState
from aidnd.mind.llm_agent import apply_actions
from aidnd.mind.world import Body


class _World:
    def __init__(self, me):
        self.bodies = {me.id: me}
        self.ground = {}


def _st():
    return NpcState.from_config(NpcConfig(id="npc:x", name="Икс", role="страж"))


def test_feel_over_nudge_capped_and_self_targeted():
    st = _st()
    st.emotion["anger"] = 0.2
    apply_actions([{"tool": "feel", "emotion": "anger", "value": 0.9}],
                  st, _World(Body(id="npc:x", place="sq")), clock=1)
    assert st.emotion["anger"] == 0.45                 # 0.2 + clamp(0.7, ±0.25) = 0.45 (byte-identical)
    assert st.emotion_target["anger"] == "npc:x"       # self-event self-targets (new, in-band)


def test_need_self_event_nudges_no_target():
    st = _st()
    st.needs["hunger"] = 0.9
    apply_actions([{"tool": "need", "need": "hunger", "value": 0.0}],
                  st, _World(Body(id="npc:x", place="sq")), clock=1)
    assert st.needs["hunger"] == 0.65                  # 0.9 − 0.25 (byte-identical)
    assert "hunger" not in st.emotion_target           # needs are not emotions — no target
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/mind/test_self_feel.py -q`
Expected: FAIL — today the feel handler sets no `emotion_target["anger"]` (the second assertion fails).

- [ ] **Step 3: Move `_nudge` into `project.py` and add the self-feeling arm to `_land`** — `src/aidnd/mind/project.py`.

Add `_nudge` immediately ABOVE `_land`:

```python
def _nudge(cur: float, want: float) -> float:
    """A feel/need tool NUDGES a channel by at most ±feel_nudge_cap, never overwrites it (spec §5-U3)
    — a model reply cannot erase a justified grudge or hunger in one call."""
    cap = BRAIN["feel_nudge_cap"]
    return round(max(0.0, min(1.0, cur + max(-cap, min(cap, want - cur)))), 6)
```

Add the `feel=None` keyword and the self-feeling arm at the TOP of `_land` (before the `appraise` call):

```python
def _land(state, dims, rel, source=None, seed=None, feel=None) -> None:
    """THE apply sink (U2/U3). … (keep the existing docstring, then add:)
    `feel` (U3): a self-feeling self-event {"channel","want","need"} — nudge the named channel by
    ±feel_nudge_cap and self-target it, NOT an appraisal of an external act."""
    from .tick import appraise  # local import: mind/tick imports model → avoid a load cycle

    if feel is not None:                                 # SELF-FEELING arm (U3) — nudge, not appraise
        channel, want = feel["channel"], feel["want"]
        pool = state.needs if feel.get("need") else state.emotion
        pool[channel] = _nudge(pool.get(channel, 0.0), want)
        if not feel.get("need") and source:
            state.emotion_target[channel] = source       # an emotion self-targets (channel = me)
        return

    appraise(state, dims, source=source)
    # … (the rest of _land — actor_fear / victim_affinity / target_warmth / seed — unchanged)
```

- [ ] **Step 4: Route feel/need through the door and delete the local `_nudge`** — `src/aidnd/mind/llm_agent.py`.

Delete the local `_nudge` definition (lines 33-37):

```python
def _nudge(cur: float, want: float) -> float:
    """feel/need tools NUDGE a channel by at most ±feel_nudge_cap, never overwrite it outright
    (spec §5 E) — a model reply can no longer erase a justified grudge or hunger in one call."""
    cap = BRAIN["feel_nudge_cap"]
    return round(max(0.0, min(1.0, cur + max(-cap, min(cap, want - cur)))), 6)
```

Delete the now-unused `from .tunables import BRAIN` line added in Task 1 (line 30) IF `BRAIN` is no longer referenced elsewhere in `llm_agent.py` (verify with `grep -n 'BRAIN' src/aidnd/mind/llm_agent.py` — if the only use was `_nudge`, remove the import).

Replace the feel handler (lines 492-496):

```python
        elif tool == "feel":
            e, v = a.get("emotion"), a.get("value")
            if e in state.emotion and isinstance(v, (int, float)):
                state.emotion[e] = _nudge(state.emotion.get(e, 0.0), float(v))
                log.append(f"~{EMO_RU.get(e, e)}={v}")
```

with:

```python
        elif tool == "feel":
            e, v = a.get("emotion"), a.get("value")
            if e in state.emotion and isinstance(v, (int, float)):
                ev = Event(state.config.id, state.config.id,          # self-event (U3): actor==target==me
                           abs(float(v) - state.emotion.get(e, 0.0)), 0.0, 0.0, ["чувство"])
                _land(state, {}, {}, source=ev.actor, feel={"channel": e, "want": float(v)})
                log.append(f"~{EMO_RU.get(e, e)}={v}")
```

Replace the need handler (lines 497-501):

```python
        elif tool == "need":
            n, v = a.get("need"), a.get("value")
            if n in state.needs and isinstance(v, (int, float)):
                state.needs[n] = _nudge(state.needs.get(n, 0.0), float(v))
                log.append(f"~{NEED_RU.get(n, n)}={v}")
```

with:

```python
        elif tool == "need":
            n, v = a.get("need"), a.get("value")
            if n in state.needs and isinstance(v, (int, float)):
                ev = Event(state.config.id, state.config.id,          # self-event (U3): a felt need
                           abs(float(v) - state.needs.get(n, 0.0)), 0.0, 0.0, ["нужда"])
                _land(state, {}, {}, source=ev.actor, feel={"channel": n, "want": float(v), "need": True})
                log.append(f"~{NEED_RU.get(n, n)}={v}")
```

Add the `_land` import at the top of `llm_agent.py` (near the other local imports, e.g. beside line 29 `from .appraisal import _race_rel, appraise_present`):

```python
from .project import _land  # U3: feel/need self-events land through the one sink
```

(`Event` is already imported locally inside `apply_actions` at line 391-393 — it is in scope where the handlers run.)

- [ ] **Step 5: Run the self-feel + feel-clamp suites — verify green**

Run: `.venv/bin/pytest tests/mind/test_self_feel.py tests/mind/test_feel_clamp.py -q`
Expected: PASS. `test_feel_clamp` (0.45 / 0.35 / 0.65) is byte-identical — the nudge math is unchanged, only its home and the added self-target moved.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest tests/ -q`
Expected: PASS, 782 tests (2 added in `test_self_feel.py`).

- [ ] **Step 7: Commit**

```bash
git add src/aidnd/mind/project.py src/aidnd/mind/llm_agent.py tests/mind/test_self_feel.py
git commit -m "feat(mind): feel/need — само-событие через ту же дверь (self-feeling arm _land), клапан сохранён"
```

---

## Task 5 (U5): Brain logic reassembles in `mind/`

**Files:**
- Create: `src/aidnd/mind/social.py` (`_accrue_familiarity`, `_greet_impulse`, `_pick_newcomer`, `_greeted_toward` moved from `world.py`)
- Create: `src/aidnd/mind/attention.py` (`_body_attention`, `_activity_of`, `_ATT_MULT`, `_phase` moved from `world.py`)
- Modify: `src/aidnd/server/play/engine/world.py:101-128,763-817` (delete the moved bodies; keep thin call-throughs)
- Test: `tests/mind/test_brain_moves.py` (NEW — import-clean + moved-logic parity)

**Interfaces:**
- **Consumes:** `BRAIN` (Task 1) — `social.py` reads `familiarity_k`, `familiarity_affinity`, `greet_sociability_base`; `attention.py` reads `att_asleep`/`att_drunk`/`att_absorbed`/`att_alert`.
- **Produces (`mind/social.py`):**
  - `_accrue_familiarity(st, other_id: str) -> None`
  - `_greet_impulse(sociability: float) -> float`
  - `_pick_newcomer(st, others, greeted: set) -> str | None`
  - `_greeted_toward(d: dict, newcomer: str, w) -> bool`
- **Produces (`mind/attention.py`):**
  - `_ATT_MULT: dict`
  - `_phase(gt: int) -> str` (pure; mind-local copy of the day-phase arithmetic for the activity label)
  - `_activity_of(state, gt: int, phase: str | None = None) -> str`
  - `_body_attention(cfg, state=None, _activity=None, gt=None, phase=None) -> float`
- **Produces (`world.py` call-throughs, names unchanged so existing tests hold):** `world._accrue_familiarity`, `world._greet_impulse`, `world._pick_newcomer`, `world._greeted_toward`, `world._activity_of(state, gt)`, `world._body_attention(cfg, state=None, _activity=None)` — thin wrappers that supply the play clock (`_gt()`/`_phase()`) where the moved logic now takes it as a parameter.

- [ ] **Step 1: Write the failing import-clean + parity test** — `tests/mind/test_brain_moves.py`

```python
"""U5: familiarity/greet → mind/social.py, attention → mind/attention.py — PURE moves (behavior
unchanged; the world.py tests are the guard). The moved modules are import-clean of the play layer
(only aidnd.mind.tunables), and the clock/knob dependencies are threaded as parameters. Spec §5-U5."""
from __future__ import annotations

import pytest

from aidnd.mind import NpcConfig, NpcState


def test_social_module_is_import_clean_of_play():
    import aidnd.mind.social as social
    src = social.__file__
    with open(src, encoding="utf-8") as f:
        text = f.read()
    assert "aidnd.server" not in text and "engine" not in text   # no play-layer import


def test_attention_module_is_import_clean_of_play():
    import aidnd.mind.attention as attention
    src = attention.__file__
    with open(src, encoding="utf-8") as f:
        text = f.read()
    assert "aidnd.server" not in text and "engine" not in text


def test_activity_of_takes_gt_and_phase():
    from aidnd.mind.attention import _activity_of
    st = NpcState.from_config(NpcConfig(id="npc:t", role="горожанин", perception={"vigilance": 0.7}))
    st.mode = "routine"
    assert _activity_of(st, gt=3 * 60, phase="night") == "asleep"     # abed in the dark
    assert _activity_of(st, gt=12 * 60, phase="day") == "alert"       # up and about by day


def test_greet_impulse_moved_logic_parity():
    from aidnd.mind.social import _greet_impulse
    from aidnd.mind.tunables import BRAIN
    assert _greet_impulse(0.9) == pytest.approx(BRAIN["greet_sociability_base"] * 0.4, abs=1e-6)
    assert _greet_impulse(0.4) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/mind/test_brain_moves.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'aidnd.mind.social'`.

- [ ] **Step 3: Create `src/aidnd/mind/social.py`** (bodies moved verbatim from `world.py:763-817`; `PB[...]` → `BRAIN[...]`)

```python
"""Familiarity accrual + newcomer greet (Inc3) — the brain's own social bookkeeping, back in mind/
(U5). Pure: reads only aidnd.mind.tunables.BRAIN and duck-typed NpcState/world objects, never the
play layer. world.py keeps thin call-throughs. Spec §5-U5.

Familiarity is BOOKKEEPING, not an Event (§5-U2): "we have shared a room K times" has no actor,
no salience, no moral-axis tag — wrapping it as an Event would be content-free ceremony. So the
counter stays a counter; at the K-th tick it seeds a faint acquaintance tie directly.
"""

from __future__ import annotations

from .tunables import BRAIN


def _greet_impulse(sociability: float) -> float:
    """Pull to approach a fresh face — sociability-gated: an unsociable NPC (≤0.5) feels none."""
    return round(BRAIN["greet_sociability_base"] * max(0.0, sociability - 0.5), 2)


def _accrue_familiarity(st, other_id: str) -> None:
    """One co-presence tick toward acquaintance. Below familiarity_k the counter just grows and the
    other stays mechanically a STRANGER (no rel row). At the K-th tick a FAINT UNANCHORED tie appears
    (small affinity/trust; anchored=False → loose Inc1 decay), flipping `other ∈ relationships` true
    so greetings warm. A person already known accrues nothing — the counter is pre-acquaintance only."""
    if other_id in st.relationships:
        return
    fam = st.familiarity
    fam[other_id] = fam.get(other_id, 0) + 1
    if fam[other_id] >= BRAIN["familiarity_k"]:
        aff = BRAIN["familiarity_affinity"]
        rel = st.rel(other_id)                           # setdefault → the faint tie now exists
        rel["affinity"] = max(rel.get("affinity", 0.0), aff)
        rel["trust"] = max(rel.get("trust", 0.0), aff)
        rel["anchored"] = False                          # loose — not earned by a real interaction


def _greeted_toward(d: dict, newcomer: str, w) -> bool:
    """Did this decision actually GREET the newcomer — a say directed at them, or a move ONTO their
    spot (an approach)? The ≤1-greeter lock keys on THIS, not on mere selection: a drawn NPC that
    instead ate/worked/waited leaves the slot open for another to greet."""
    for a in (d.get("actions") or []):
        if not isinstance(a, dict):
            continue
        tool = a.get("tool")
        if tool == "say" and str(a.get("text") or "").strip():
            tgt = str(a.get("to") or "").strip()
            if (getattr(w, "aliases", None) or {}).get(tgt.lower(), tgt) == newcomer:
                return True
        elif tool == "move" and a.get("to"):
            if newcomer in w.bodies and str(a["to"]) == w.bodies[newcomer].place:
                return True
    return False


def _pick_newcomer(st, others, greeted: set) -> str | None:
    """First co-present body this NPC has NEVER met (no rel row) and nobody has greeted yet — a fresh
    face that can pull a sociable NPC to approach. A known person or an already-greeted newcomer is
    not a candidate (≤1 greeter/scene)."""
    for other in others:
        if other not in st.relationships and other not in greeted:
            return other
    return None
```

- [ ] **Step 4: Create `src/aidnd/mind/attention.py`** (bodies moved from `world.py:101-128`; `PB[...]` → `BRAIN[...]`; `_phase(gt)` copied pure; `_gt()` dependency threaded as a param)

```python
"""Attention Pillar 2 (Inc6): Body.attention = perception.vigilance × current-activity multiplier,
clamped [0.05, 1.0], back in mind/ (U5). Pure: reads only aidnd.mind.tunables.BRAIN; the play clock
(gt / day-phase) is threaded in as parameters so mind/ stays import-clean of play. world.py's
call-through supplies _gt()/_phase(). Spec §5-U5/§6/§3c."""

from __future__ import annotations

from .tunables import BRAIN

_ATT_MULT = {"asleep": "att_asleep", "drunk": "att_drunk",
             "absorbed": "att_absorbed", "alert": "att_alert"}


def _phase(gt: int) -> str:
    """Day phase for the activity label — pure arithmetic (mind-local copy of the play clock's phase
    thresholds; identical boundaries). Used only when the caller does not pass a resolved `phase`."""
    h = (gt // 60) % 24
    return ("night" if h < 6 else "morning" if h < 11 else "day"
            if h < 17 else "evening" if h < 22 else "night")


def _activity_of(state, gt: int, phase: str | None = None) -> str:
    """Coarse current-activity label driving the attention multiplier (§6/§3c). Derived from the REAL
    runtime signals on NpcState — mode / on_shift / the day phase / current fear / role. `phase` may
    be supplied (world.py passes _phase(gt)); else it is derived from `gt`. No drunkenness signal yet,
    so the 'drunk' arm is unreachable (knob kept for the set + the _activity= unit seam)."""
    ph = phase if phase is not None else _phase(gt)
    mode = getattr(state, "mode", "leisure")
    if mode == "routine" and ph == "night":                        # abed at home in the dark
        return "asleep"
    if (mode == "threat" or state.emotion.get("fear", 0.0) >= 0.6  # frightened / on-guard / watchman
            or state.config.role == "стражник"):
        return "alert"
    if mode == "converse" or getattr(state, "on_shift", 0.0) > 0.0:  # deep in talk / heads-down at bench
        return "absorbed"
    return "alert"                                                  # up-and-about, ordinary watchfulness


def _body_attention(cfg, state=None, _activity=None, gt=None, phase=None) -> float:
    """Vigilance (§3.9 → C11) × current-activity multiplier (§6, Pillar 2), clamped [0.05, 1.0]. A
    sleeping/absorbed target dips below the value.py 0.4 theft window; an alert guard caps at 1.0.
    `_activity` overrides the derivation (unit seam); `gt`/`phase` feed the runtime derivation when a
    live `state` is given (world.py supplies them). Un-enriched vig → 0.5."""
    vig = float((getattr(cfg, "perception", None) or {}).get("vigilance", 0.5))
    act = _activity or (_activity_of(state, gt if gt is not None else 0, phase)
                        if state is not None else "alert")
    return max(0.05, min(1.0, vig * BRAIN[_ATT_MULT.get(act, "att_alert")]))
```

- [ ] **Step 5: Replace the moved bodies in `world.py` with call-throughs** — `src/aidnd/server/play/engine/world.py`.

Add the module imports near the top of `world.py` (beside the other `aidnd.mind` imports):

```python
from aidnd.mind import attention as _attn
from aidnd.mind import social as _social
```

Replace `_activity_of` + `_body_attention` (lines 101-128) with thin wrappers:

```python
def _activity_of(state, gt: int) -> str:
    """Play-side call-through (U5): resolves the day phase from the play clock and delegates to
    aidnd.mind.attention._activity_of. Kept as world._activity_of so existing tests/callers hold."""
    return _attn._activity_of(state, gt, _phase(gt))


def _body_attention(cfg, state=None, _activity=None) -> float:
    """Play-side call-through (U5): supplies the play clock (_gt/_phase) to the moved
    aidnd.mind.attention._body_attention only when the runtime derivation is actually needed."""
    if _activity is None and state is not None:
        gt = _gt()
        return _attn._body_attention(cfg, state, gt=gt, phase=_phase(gt))
    return _attn._body_attention(cfg, state, _activity=_activity)
```

(Delete the old `_ATT_MULT = {...}` at lines 101-102 — it now lives in `mind/attention.py`. Verify nothing else in `world.py` reads `_ATT_MULT` with `grep -n '_ATT_MULT' src/aidnd/server/play/engine/world.py`; if a stray reference remains, point it at `_attn._ATT_MULT`.)

Replace `_greet_impulse`, `_accrue_familiarity`, `_greeted_toward`, `_pick_newcomer` (lines 763-817) with call-throughs (keep the `_MUST_WHY` frozenset and its comment block above them untouched):

```python
def _greet_impulse(sociability: float) -> float:
    return _social._greet_impulse(sociability)


def _accrue_familiarity(st, other_id: str) -> None:
    _social._accrue_familiarity(st, other_id)


def _greeted_toward(d: dict, newcomer: str, w) -> bool:
    return _social._greeted_toward(d, newcomer, w)


def _pick_newcomer(st, others, greeted: set) -> str | None:
    return _social._pick_newcomer(st, others, greeted)
```

- [ ] **Step 6: Run the moved-logic guard suites — verify green**

Run: `.venv/bin/pytest tests/mind/test_brain_moves.py tests/mind/test_attention_activity.py tests/play/test_greet_familiarity.py -q`
Expected: PASS. `test_attention_activity` (which calls `W._body_attention` / `W._activity_of`) and `test_greet_familiarity` (which calls `W._greet_impulse` / `W._accrue_familiarity` / `W._pick_newcomer`) are byte-identical through the call-throughs; the new import-clean test passes.

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/pytest tests/ -q`
Expected: PASS, 786 tests (4 added in `test_brain_moves.py`).

- [ ] **Step 8: Commit**

```bash
git add src/aidnd/mind/social.py src/aidnd/mind/attention.py \
        src/aidnd/server/play/engine/world.py tests/mind/test_brain_moves.py
git commit -m "refactor(mind): мозг возвращается в mind/ — social.py (знакомство/приветствие) + attention.py, world.py тонкие проброски"
```

---

## Self-Review (run against the spec with fresh eyes)

**1. Spec coverage:**
- U1 victim branch (§3b/§5-U1) → Task 2 (branch + raw-block deletion + un-exclude victim). ✓
- U2 co-presence via `_land` + familiarity-as-bookkeeping decision (§5-U2) → Task 3 (`_land` extraction + `appraise_present` routing). Familiarity accrual stays a counter (moved in Task 5, not wrapped as an Event) — the `_menace_affect` memory line (§5-U2) is intentionally NOT moved (memory ≠ affect) and is left in `core.py` untouched. ✓
- U3 feel/need self-event (§5-U3, boundary example 0.2+0.9→0.45) → Task 4 (`_land` self-feeling arm + `_nudge` moved). ✓
- U4 tunables registry (§5-U4, splice-guard) → Task 1 (FIRST, so U1's victim knobs are born in tunables). ✓
- U5 brain moves (§5-U5, `_activity_of` param seam) → Task 5 (pure moves + call-throughs). ✓
- Non-goals honored: no new phenomena, no LLM, no DB, decision side untouched except the deleted victim writes. Testbed quarantine (§9) correctly OUT. ✓

**2. Placeholder scan:** No TBD/TODO/"similar to Task N"/"add error handling". Every code step carries complete code copied from the verified seams and the spec's formulas/knob values. ✓

**3. Type consistency across tasks:**
- `BRAIN` (Task 1) is read as `BRAIN[...]` in Tasks 2/3/5 — consistent dict. ✓
- `project_event` returns `{"dims", "rel"}` with `rel` gaining `victim_affinity`/`beneficiary` (Task 2), consumed by `_land` (Task 3 imports/reads exactly those keys). ✓
- `_land(state, dims, rel, source=None, seed=None)` (Task 3/U2) → extended to `_land(..., feel=None)` (Task 4/U3) — additive keyword, back-compatible with the Task-3 call sites. ✓
- `_nudge(cur, want)` moved from `llm_agent` (Task 1 rewired it to `BRAIN`; Task 4 relocates it to `project.py`) — same signature throughout. ✓
- `social._accrue_familiarity`/`_greet_impulse`/`_pick_newcomer`/`_greeted_toward` and `attention._activity_of(state, gt, phase=None)`/`_body_attention(cfg, state, _activity, gt, phase)` (Task 5) match the world.py call-through arities and the existing test call sites (`W._activity_of(state, gt)`, `W._body_attention(cfg, _activity=…)`). ✓
