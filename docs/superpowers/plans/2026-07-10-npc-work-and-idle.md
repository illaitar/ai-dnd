# NPC Work & Idle Life — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make on-shift NPCs actually work (a smith smiths, a keeper tends bar) instead of drinking ale, by feeding "on the clock" into the mind and lifting the `purpose` need — the designed "keep working" duty (Pillar 2 Increment 6).

**Architecture:** Mirror the proven `venue_social` lift. The live scene sets a per-NPC `on_shift` lift on `NpcState`; `standing_needs` adds it to the `purpose` goal so work out-competes idle hunger; the live builder guarantees a work-affording object at post zones so the duty has a `use`-target. No new goal type, no caps.

**Tech Stack:** Python 3.14, pytest, `uv run pytest`. Pure mind package (`src/aidnd/mind`) + server live scene (`src/aidnd/server/play/engine`).

## Global Constraints

- **No mechanical gates on NPC behaviour** — model the world, don't cap ([README principle 6](../../README.md)). This change adds a *drive*, never a cap.
- **No hardcoded gameplay numbers in code** — tunables go in the `PB` table (`session/config.py`). The lift magnitude is a `PB` key.
- **Mind package stays pure** — `src/aidnd/mind` must not import server/DB/city. The `on_shift` magnitude is decided server-side and set as a float on `NpcState`; the mind only reads it.
- **Full suite green before deploy:** `uv run pytest /Users/nik/Desktop/dnd-ai/tests` (run with absolute path; the shell CWD may not be repo root).
- **Deploy after each green increment** via the `/deploy` flow (commit with NO Claude co-author trailer, push origin main, VPS git-reset + restart `aidnd`).
- Run pytest from an absolute path: `uv run pytest /Users/nik/Desktop/dnd-ai/tests`.

---

## Scope

> **Increment 1 — ✔ shipped to prod (commit b0b0df7).** Playtest-confirmed: on-shift smith works (forge/bellows/orders) instead of drinking; balanced pull holds. 264 tests green. Final review: SHIP.

This plan covers **Increment 1 — "workers work"** (spec Units 1, 2, and the minimal slice of Unit 3 needed to demonstrate it). Increments 2–4 (pool-wide work affordances, idle repertoire + satiety, shop customers) are outlined at the end and get their own detailed plans after Increment 1 ships and the live playtest informs tuning.

Spec: [docs/superpowers/specs/2026-07-10-npc-work-and-idle-design.md](../specs/2026-07-10-npc-work-and-idle-design.md).

---

### Task 1: `on_shift` lift on NpcState + `purpose` lift in `standing_needs` (mind, pure)

**Files:**
- Modify: `src/aidnd/mind/model.py` (NpcState dataclass, ~line 72 beside `venue_social`)
- Modify: `src/aidnd/mind/goals.py` (`standing_needs`, lines 40-49)
- Test: `tests/mind/test_work_duty.py` (create)

**Interfaces:**
- Produces: `NpcState.on_shift: float` (default `0.0`) — the additive lift to the `purpose` need's goal value while the NPC is on the clock. Set by the live scene (Task 2). Read only in `standing_needs`.

- [ ] **Step 1: Write the failing test**

```python
# tests/mind/test_work_duty.py
from aidnd.mind.model import NpcState, NpcConfig


def _state(**needs):
    cfg = NpcConfig(id="w1", name="Смит", traits={})
    st = NpcState.from_config(cfg)
    st.needs.update({"purpose": 0.2, "hunger": 0.5})
    st.needs.update(needs)
    return st


def _goal_val(goals, need):
    g = next((g for g in goals if g.kind == "need" and g.target == need), None)
    return g.value if g else 0.0


def test_off_shift_hunger_beats_purpose():
    from aidnd.mind.goals import standing_needs
    st = _state()
    st.on_shift = 0.0
    goals = standing_needs(st)
    assert _goal_val(goals, "hunger") > _goal_val(goals, "purpose")


def test_on_shift_purpose_beats_hunger():
    from aidnd.mind.goals import standing_needs
    st = _state()
    st.on_shift = 0.6              # on the clock
    goals = standing_needs(st)
    assert _goal_val(goals, "purpose") > _goal_val(goals, "hunger")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/mind/test_work_duty.py -v`
Expected: FAIL — `NpcState` has no `on_shift` attribute (AttributeError) or `test_on_shift_purpose_beats_hunger` fails because purpose is not lifted.

- [ ] **Step 3: Add the field to NpcState**

In `src/aidnd/mind/model.py`, add beside `venue_social` (line 72):

```python
    on_shift: float = 0.0                                # workplace 'keep working' purpose lift (set by live scene)
```

- [ ] **Step 4: Lift purpose in `standing_needs`**

In `src/aidnd/mind/goals.py`, inside the `standing_needs` loop (lines 43-48), after `val = lvl * w`:

```python
    for nd, lvl in state.needs.items():
        w = state.config.traits.get(NEED_WEIGHT[nd], 0.5) + 0.5 if nd in NEED_WEIGHT else 1.0
        val = lvl * w
        if nd == "purpose":
            val += getattr(state, "on_shift", 0.0)       # on the clock → work out-competes idle needs
        if val > 0.08:
            meta = dict(state.needs_sources.get(nd, {})) if hasattr(state, "needs_sources") else {}
            out.append(Goal("need", nd, val, meta))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/mind/test_work_duty.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Run the mind suite to check no regression**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/mind -q`
Expected: PASS (all).

- [ ] **Step 7: Commit**

```bash
git add src/aidnd/mind/model.py src/aidnd/mind/goals.py tests/mind/test_work_duty.py
git commit -m "feat(mind): on_shift purpose lift — on-clock workers value work over idle needs [work-duty]"
```

---

### Task 2: Set `on_shift` in the live scene (server) + PB lift key

**Files:**
- Modify: `src/aidnd/server/play/engine/session/config.py` (PB table, near `leisure_social_lift` line 102)
- Modify: `src/aidnd/server/play/engine/world.py` (`_live_build`, the loop at lines 333-336 where `venue_social`/`workers` are set)
- Test: `tests/play/test_work_shift.py` (create)

**Interfaces:**
- Consumes: `NpcState.on_shift` (Task 1), `open_hours.is_open(info: str, gt: int) -> bool`, `PB`.
- Produces: `_work_lift(pid, workers, info, gt) -> float` — pure helper in `world.py`, returns `PB["workplace_purpose_lift"]` when `pid in workers and open_hours.is_open(info, gt)`, else `0.0`. Used inside `_live_build` to set each present NPC's `state.on_shift`.

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_work_shift.py
from aidnd.server.play.engine.world import _work_lift
from aidnd.server.play.engine.session.config import PB


def test_worker_on_shift_gets_lift():
    # кузница open 7-18 (open_hours canonical); 10:00 = 600 min
    lift = _work_lift("smith", {"smith"}, "Кузница «Железный зуб»", 10 * 60)
    assert lift == PB["workplace_purpose_lift"] > 0


def test_worker_off_hours_no_lift():
    # 03:00 = 180 min — smithy closed
    assert _work_lift("smith", {"smith"}, "Кузница «Железный зуб»", 3 * 60) == 0.0


def test_non_worker_no_lift():
    assert _work_lift("guest", {"smith"}, "Кузница «Железный зуб»", 10 * 60) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/play/test_work_shift.py -v`
Expected: FAIL — `_work_lift` not defined (ImportError).

- [ ] **Step 3: Add the PB key**

In `src/aidnd/server/play/engine/session/config.py`, near line 102 (`"leisure_social_lift": 3.0,`):

```python
    "workplace_purpose_lift": 0.6,   # on-shift worker's purpose lift (additive to purpose goal; tune in playtest)
```

- [ ] **Step 4: Add the `_work_lift` helper and set `on_shift` in `_live_build`**

In `src/aidnd/server/play/engine/world.py`, add a module-level helper (near the top-level helpers, before `_live_build`):

```python
def _work_lift(pid, workers, info: str, gt: int) -> float:
    """On-shift 'keep working' lift: a worker at their workplace during open hours (docs/sound-attention.md
    Increment 6). Returns the purpose lift magnitude, else 0.0."""
    from aidnd.server.play.engine import open_hours
    if pid in workers and open_hours.is_open(info or "", gt):
        return PB["workplace_purpose_lift"]
    return 0.0
```

Then in `_live_build`, in the loop that already sets `venue_social` (lines 333-336), set `on_shift` alongside. After `workers = {...}` (line 336), where each present NPC's state is assigned `venue_social`:

```python
    workers = {pid for pid in here_all if people[pid].work == bid}
    _binfo = (data or {}).get("name", "")            # 'Кузница «…»' — matches open_hours by type substring
    for _pid in here_all:
        st = people[_pid].state
        st.venue_social = leisure                     # existing
        st.on_shift = _work_lift(_pid, workers, _binfo, _gt())
```

(Adapt to the exact existing loop shape — the existing code already iterates `here_all` assigning `venue_social`; add the `on_shift` line in that same loop rather than duplicating it.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/play/test_work_shift.py -v`
Expected: PASS (all three). If `open_hours.hours_for` does not match "Кузница …" to smithy hours, adjust the test's `info` string to what `hours_for` matches (check `open_hours.py` canonical keys, e.g. `"кузн"`), and pass the building's kind string in `_live_build` accordingly.

- [ ] **Step 6: Commit**

```bash
git add src/aidnd/server/play/engine/session/config.py src/aidnd/server/play/engine/world.py tests/play/test_work_shift.py
git commit -m "feat(play/live): set NpcState.on_shift for workers at their open workplace [work-duty]"
```

---

### Task 3: Live builder retains `purpose` afford on post-zone objects

**Files:**
- Modify: `src/aidnd/server/play/engine/world.py` (the zone-object → MItem conversion, lines 294-308, which today keeps only the max-afford need)
- Test: `tests/play/test_work_afford.py` (create)

**Interfaces:**
- Produces: `_afford_need(afford: dict, zone_kind: str, is_post: bool) -> str | None` — pure helper returning the need a zone object should satisfy: prefers `purpose` when the object sits at a post/workshop zone and affords any `purpose`, otherwise the existing max-afford rule (with the existing `fatigue→comfort` remap outside beds/cells).

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_work_afford.py
from aidnd.server.play.engine.world import _afford_need


def test_post_object_retains_purpose_over_comfort():
    # a hot forge affords both comfort and purpose; at a post it must surface PURPOSE
    assert _afford_need({"comfort": 0.3, "purpose": 0.1}, "workshop", True) == "purpose"


def test_non_post_object_uses_max_afford():
    assert _afford_need({"comfort": 0.3, "purpose": 0.1}, "tables", False) == "comfort"


def test_fatigue_remaps_to_comfort_outside_beds():
    assert _afford_need({"fatigue": 0.4}, "tables", False) == "comfort"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/play/test_work_afford.py -v`
Expected: FAIL — `_afford_need` not defined.

- [ ] **Step 3: Extract and adjust the afford rule**

In `src/aidnd/server/play/engine/world.py`, add the helper and use it in the zone-object loop (lines 294-308). Replace the inline `max(aff.items(), …)` logic:

```python
def _afford_need(afford: dict, zone_kind: str, is_post: bool) -> str | None:
    if not afford:
        return None
    if is_post and afford.get("purpose", 0) > 0:      # a worker's post surfaces WORK, not comfort
        return "purpose"
    need, _rate = max(afford.items(), key=lambda kv: kv[1])
    if need == "fatigue" and zone_kind not in ("beds", "cell"):
        need = "comfort"
    return need
```

In the loop (lines 294-308), compute `is_post = bool(z.get("post"))` for the zone and call `_afford_need(aff, z["kind"], is_post)` in place of the inline `need, rate = max(...)`; keep the existing `MItem(o["name"], min(0.5, round(rate*2.2, 2)), satisfies=need)` construction (recover `rate` from `aff[need]`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/play/test_work_afford.py -v`
Expected: PASS.

- [ ] **Step 5: Full suite green**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests -q`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add src/aidnd/server/play/engine/world.py tests/play/test_work_afford.py
git commit -m "feat(play/live): post-zone objects retain purpose afford so on-shift workers have work to do [work-duty]"
```

---

### Task 4: Live playtest — verify the duty (manual, gated)

**Files:** none (uses the existing playtest driver).

- [ ] **Step 1: Boot a real-LLM dev server**

Run (background): `AIDND_OPEN_PLAY=1 AIDND_PROFILE=deepseek .venv/bin/python -m uvicorn aidnd.server.app:app --host 127.0.0.1 --port 8100`

- [ ] **Step 2: Drive into a smithy and observe**

Re-run the shop portion of the playtest driver (`scratchpad/playtest2.py`) or drive `/api/play/act` "иду к кузнице" → enter → `/api/play/live` ×3.
Expected (before/after): the on-shift smith `use`s the forge / is described smithing (not drinking); a random stranger entering does NOT pull the smith off work; addressing the smith DOES get a response. Record a short before/after note.

- [ ] **Step 3: Tune if needed**

If the smith still drinks, raise `PB["workplace_purpose_lift"]` (0.6 → 0.9) and re-observe. If workers ignore the player entirely, it's too high — lower it. Commit any tuning change:

```bash
git add src/aidnd/server/play/engine/session/config.py
git commit -m "tune(play/live): workplace_purpose_lift → <value> after playtest [work-duty]"
```

- [ ] **Step 4: Deploy Increment 1**

Run the `/deploy` flow (pytest green → commit → push origin main → VPS git-reset + restart `aidnd` → verify `active`).

---

## Later increments (own plans after Increment 1 ships)

- **Increment 2 — pool-wide work affordances (spec Unit 3):** furnisher afford-only top-up stamping `purpose` on post/workshop anchors across the pool (idempotent, no `worlds.db` rewrite).
- **Increment 3 — idle repertoire + satiety (spec Unit 4):** a role/zone-flavoured idle-action pool above `idle_floor`; satiety damping on repeated `use` (reuse the beaten-topic dedup pattern, `world.py:802-808`); retire the hardcoded `"кружка эля у очага"` (`world.py:218-226`).
- **Increment 4 (optional) — shop customers (spec Unit 3):** `wares` object affording `novelty` on shop counter/shelf zones → "examine the goods."

## Self-review notes

- **Spec coverage:** Units 1–2 fully covered (Tasks 1–2); Unit 3 minimal slice (Task 3, live-builder retain-purpose) — the pool-wide furnisher stamp is deferred to Increment 2 (noted). Unit 4 deferred to Increment 3 (noted). Playtest per spec Testing (Task 4).
- **Tuning values are real starting numbers, not placeholders:** `workplace_purpose_lift = 0.6`, tuned in Task 4.
- **Type consistency:** `on_shift: float` used identically in model.py, goals.py, world.py, and tests.
