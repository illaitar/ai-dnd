# NPC Perception & Appraisal (Subsystem 1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** NPCs (and the player) read each other's *visible surface* and form an appraisal that moves
their emotions and where they choose to stand — the "proud citizen sits away from the beggar" and
"race-enemy stirs anger" behaviour from [npc-brain.md](npc-brain.md).

**Architecture:** Widen machinery that already runs. `Body` gains a visible surface (race, squalor,
marks). A new pure `mind/appraisal.py` turns (observer traits × other's surface) + a race-sentiment
table + existing relationship/memory into an `Impression`; a driver applies it each tick (emotions
via the existing `appraise()`, plus a first-impression relationship prior). `disgust` becomes a 5th
emotion. Proxemics is one extra term in the existing move/zone utility. No new subsystems, no LLM.

**Tech Stack:** Python 3.14, pytest, `uv`, the `aidnd.mind` package (utility core), the play engine.

## Global Constraints

- Each increment ends green (`uv run pytest -q`) → commit → deploy via `/deploy`.
- Commit messages English; **no `Co-Authored-By: Claude` trailer**.
- Russian-language game: **all player-facing / LLM-prompt string literals stay Russian**; new code,
  comments and docstrings are English; every new file opens with an English "Key functions" docstring.
- New functions ≤50 lines. No hardcoded gameplay numbers in code strings — tunables in `PB`/data.
- Deterministic: appraisal is pure arithmetic (no LLM, no wall-clock, no `Math.random`-style calls).
- Personal > culture > personality: an existing relationship/memory overrides a group sentiment
  which overrides a trait-derived read.

---

## File Structure

```
src/aidnd/mind/model.py        + disgust in EMOTIONS · emotion_gain/emotion_baseline entry
src/aidnd/mind/tick.py         appraise(): + `revulsion` dim → disgust delta
src/aidnd/mind/world.py        Body: + race · squalor · marks (visible surface) + armed()
src/aidnd/mind/appraisal.py    NEW — Impression, impression(), appraise_present(), race loader
src/aidnd/mind/value.py        + proxemics term in the move-utility
src/aidnd/mind/llm_agent.py    decide_hybrid: call appraise_present() right after perceive
content/race_relations.json    NEW — race × race → sentiment [-1..1]
src/aidnd/server/play/engine/world.py   _live_build: project surface onto every Body incl. player
scripts/peoplegen.py (or a small seeder)  seed a fraction of the pool as non-human races
tests/mind/test_appraisal.py   NEW — impression + appraise_present + disgust + proxemics
```

Shared types (used across tasks — keep names exact):
- `Impression = {valence: float[-1..1], emo: dict, prior: dict, remember: str|None}` where `emo` is a
  **dims dict for `appraise()`** (`revulsion, harm, goal_impact, desert, intent`) and `prior` seeds a
  relationship `{trust, affinity, fear}`.
- `impression(observer: NpcState, other: Body, race_rel: dict) -> Impression`
- `appraise_present(state: NpcState, world, percept, race_rel: dict) -> None`
- `race_sentiment(race_rel: dict, a: str, b: str) -> float`

---

## Task 1: Add the `disgust` emotion

**Files:** Modify `src/aidnd/mind/model.py` (EMOTIONS + `emotion_gain`/`emotion_baseline`),
`src/aidnd/mind/tick.py` (`appraise`). Test: `tests/mind/test_appraisal.py`.

**Interfaces:** Produces `EMOTIONS` now includes `"disgust"`; `appraise(state, dims, source)` reads a
new `revulsion[0..1]` dim and raises `disgust = revulsion × emotion_gain("disgust")`.

- [ ] **Step 1: Failing test**
```python
# tests/mind/test_appraisal.py
from aidnd.mind.model import NpcConfig, NpcState, EMOTIONS
from aidnd.mind.tick import appraise

def test_revulsion_raises_disgust():
    assert "disgust" in EMOTIONS
    st = NpcState.from_config(NpcConfig(id="npc:x", traits={"pride": 0.9}))
    appraise(st, {"revulsion": 0.8}, source="beggar")
    assert st.emotion["disgust"] > 0.3
    assert st.emotion_target.get("disgust") == "beggar"
```
- [ ] **Step 2: Run → FAIL** — `uv run pytest tests/mind/test_appraisal.py -x` (`"disgust" not in EMOTIONS`).
- [ ] **Step 3: Implement** — in `model.py`: `EMOTIONS = ("anger", "fear", "joy", "distress", "disgust")`; add `"disgust"` to the `emotion_gain` map (e.g. `"disgust": 0.6 + t.get("pride", 0.5)`) and leave `emotion_baseline` default 0. In `tick.py appraise`, add `rev = float(dims.get("revulsion", 0.0))` and `"disgust": max(0.0, rev)` to the `delta` dict (the existing loop applies `× emotion_gain` and sets `emotion_target`).
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `git commit -m "mind: add disgust emotion + revulsion appraisal dim"`.

**Increment 1 close:** `uv run pytest -q` green → `/deploy`.

---

## Task 2: Visible surface on `Body`

**Files:** Modify `src/aidnd/mind/world.py` (`Body`). Test: `tests/mind/test_appraisal.py`.

**Interfaces:** Produces `Body` fields `race: str = "human"`, `squalor: float = 0.0` (0 kept … 1
filthy), `marks: list` (visible tokens, e.g. `["брошенный клинок"]`), and a method
`armed() -> bool` (True if any `carrying` item looks like a weapon). Existing `appearance` = wealth,
`faction` = group.

- [ ] **Step 1: Failing test**
```python
from aidnd.mind.world import Body, Item
def test_body_surface_defaults_and_armed():
    b = Body(id="x", place="зал", race="орк", squalor=0.7, carrying=[Item("нож", 0.2, kind="weapon")])
    assert b.race == "орк" and b.squalor == 0.7
    assert b.armed() is True
    assert Body(id="y", place="зал").armed() is False   # empty-handed default
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** — add the three fields to the `Body` dataclass (defaults `race="human"`,
  `squalor=0.0`, `marks: list = field(default_factory=list)`), and `def armed(self) -> bool: return
  any(getattr(i, "kind", "") == "weapon" for i in self.carrying)`. Check `Item`'s real signature in
  `world.py` first and match it in the test.
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `git commit -m "mind: visible surface on Body (race/squalor/marks/armed)"`.

**Increment 2 close:** pytest green → `/deploy`.

---

## Task 3: Race-relations table + loader

**Files:** Create `content/race_relations.json`; add `race_sentiment` to `src/aidnd/mind/appraisal.py`
(create the module). Test: `tests/mind/test_appraisal.py`.

**Interfaces:** Produces `race_sentiment(race_rel: dict, a: str, b: str) -> float` in `[-1..1]`
(how race `a` feels about race `b`; unknown pair → 0.0; a race about itself → mild positive). A
`load_race_relations() -> dict` that reads the JSON once (cached).

- [ ] **Step 1: Failing test**
```python
from aidnd.mind.appraisal import load_race_relations, race_sentiment
def test_race_sentiment():
    rr = load_race_relations()
    assert race_sentiment(rr, "человек", "человек") >= 0.0
    assert race_sentiment(rr, "дворф", "орк") < 0.0      # authored enmity
    assert race_sentiment(rr, "человек", "неведомый") == 0.0   # unknown → neutral
```
- [ ] **Step 2: Run → FAIL** (no module).
- [ ] **Step 3: Implement** — `content/race_relations.json` like
  `{"дворф": {"орк": -0.7}, "орк": {"дворф": -0.6}, "эльф": {"орк": -0.4}}` (Russian race names to
  match the pool); `mind/appraisal.py` with the English "Key functions" docstring, `load_race_relations`
  (path via `importlib.resources`/repo `content/`), and `race_sentiment` (self → 0.15, table lookup,
  else 0.0).
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `git commit -m "mind: race_relations table + race_sentiment loader"`.

---

## Task 4: `impression()` — the pure appraisal

**Files:** Modify `src/aidnd/mind/appraisal.py` (add `Impression`, `impression`). Test:
`tests/mind/test_appraisal.py`.

**Interfaces:** Produces `Impression` (dataclass with `valence`, `emo`, `prior`, `remember`) and
`impression(observer: NpcState, other: Body, race_rel: dict) -> Impression`. Combines the three
tiers, **personal > culture > personality**.

- [ ] **Step 1: Failing tests**
```python
from aidnd.mind.appraisal import impression, load_race_relations
from aidnd.mind.model import NpcConfig, NpcState
from aidnd.mind.world import Body

def _obs(**tr): return NpcState.from_config(NpcConfig(id="obs", race="человек", traits={**tr}))

def test_proud_recoils_from_squalor():
    imp = impression(_obs(pride=0.9), Body(id="beg", place="зал", appearance=0.05, squalor=0.8), {})
    assert imp.valence < 0 and imp.emo.get("revulsion", 0) > 0.3

def test_race_enemy_stirs_anger_and_fear():
    rr = load_race_relations()
    imp = impression(_obs(bravery=0.4), Body(id="o", place="зал", race="орк"), rr) \
        if _obs().config.race == "дворф" else None
    # observer is a dwarf, target an orc:
    dwarf = NpcState.from_config(NpcConfig(id="d", race="дворф", traits={"bravery": 0.4}))
    imp = impression(dwarf, Body(id="o", place="зал", race="орк"), rr)
    assert imp.valence < 0 and imp.emo.get("desert", 0) < 0

def test_personal_bond_overrides_race_hate():
    rr = load_race_relations()
    dwarf = NpcState.from_config(NpcConfig(id="d", race="дворф"))
    dwarf.rel("o")["affinity"] = 0.8            # he saved my life
    imp = impression(dwarf, Body(id="o", place="зал", race="орк"), rr)
    assert imp.valence > 0                       # personal beats culture
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** — `impression` as small helpers (each ≤50 lines):
  - **Tier A (traits × surface):** `revulsion = pride × (1 − appearance) × squalor`;
    `warmth = sociability × charisma`; `wary = (1 − bravery) × (1.0 if other.armed() else 0.0)`;
    `contempt = malice × (1 − honesty)`.
  - **Tier B (culture):** `cult = race_sentiment(race_rel, observer.race, other.race)`, modulated by
    `(0.5 + malice)` for hostility and softened by low malice.
  - **Tier C (personal):** existing `observer.relationships.get(other.id)` — if present, its
    `affinity` dominates (`valence = 0.7 × rel_affinity + 0.3 × (A+B)`), else `valence = warmth −
    revulsion − contempt + cult`.
  - Map to `emo` dims: `{"revulsion": revulsion, "harm": wary, "desert": min(0, cult),
    "goal_impact": valence, "intent": False}`; `prior = {"affinity": valence, "fear": wary,
    "trust": max(0, warmth − wary)}`; `remember` = a short Russian note only when |valence|>0.5
    (e.g. `"замызганный оборванец у очага"`, `"орк — на дух не переношу"`).
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `git commit -m "mind: impression() — trait/culture/personal appraisal"`.

**Increment 3 close (Tasks 3–4):** pytest green → `/deploy`.

---

## Task 5: `appraise_present()` — apply impressions each tick

**Files:** Modify `src/aidnd/mind/appraisal.py` (`appraise_present`), `src/aidnd/mind/llm_agent.py`
(call it in `decide_hybrid` after `perceive`). Test: `tests/mind/test_appraisal.py`.

**Interfaces:** Produces `appraise_present(state, world, percept, race_rel) -> None` — for each
`percept.present` other, compute `impression`, `appraise(state, imp.emo, source=other.id)`, and
**seed a relationship prior only if none exists yet** (`state.relationships.setdefault(...)`), and
add `imp.remember` to memory once. Idempotent within a tick (guard by a seen-set on `state`).

- [ ] **Step 1: Failing test**
```python
from aidnd.mind.appraisal import appraise_present, load_race_relations
from aidnd.mind.world import World, Body
from aidnd.mind.sim import perceive
from aidnd.mind.model import NpcConfig, NpcState

def test_appraise_present_moves_emotion_and_seeds_prior():
    w = World(); w.link("зал", "улица")
    obs = NpcState.from_config(NpcConfig(id="obs", race="человек", traits={"pride": 0.9}))
    w.add(Body(id="obs", place="зал")); w.bodies["obs"]  # ensure present
    w.add(Body(id="beg", place="зал", appearance=0.05, squalor=0.8))
    appraise_present(obs, w, perceive(obs, w), load_race_relations())
    assert obs.emotion["disgust"] > 0.2
    assert "beg" in obs.relationships and obs.relationships["beg"]["affinity"] < 0
```
- [ ] **Step 2: Run → FAIL.** [ ] **Step 3: Implement** `appraise_present`; then in `decide_hybrid`
  (`llm_agent.py`), right after it builds the percept, call `appraise_present(state, world, percept,
  race_rel)` (thread `race_rel` in via a module-level cached `load_race_relations()`; do NOT change
  decide_hybrid's return). Keep it side-effect-only. [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `git commit -m "mind: appraise_present — apply impressions on perceive"`.

**Increment 4 close:** pytest green → `/deploy`.

---

## Task 6: Project surface onto Bodies (incl. the player)

**Files:** Modify `src/aidnd/server/play/engine/world.py` (`_live_build`, ~lines 970–1002). Test:
`tests/play/test_surface.py`.

**Interfaces:** Consumes `Body.race/squalor/marks`. Every NPC `Body` added in `_live_build` is set
from `people[pid].persona`/`mech` (race from persona `race`; squalor derived from status/`appearance`
+ any "оборванец/грязн" hint or a `hygiene` field; marks from persona `look.marks`). The **player**
`Body` gets the same fields (race default `"человек"`, squalor from a `pc_state` field / default 0).

- [ ] **Step 1: Failing test** — build a world (the `test_economy` fixture pattern), enter/observe a
  scene, and assert a present NPC's `Body` in `_S["live"]["world"].bodies` has a non-empty `race` and
  a `squalor` in `[0,1]`; assert the player Body has `race`.
- [ ] **Step 2: Run → FAIL.** [ ] **Step 3: Implement** — extend the two `Body(...)` constructions in
  `_live_build` with `race=`, `squalor=`, `marks=` from persona/mech (helper `_npc_surface(p) -> dict`
  ≤50 lines); player Body likewise. Preserve every existing field. [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `git commit -m "scene: project NPC/player visible surface onto Bodies"`.

**Increment 5 close:** pytest green → `/deploy`.

---

## Task 7: Proxemics — distance term in the move utility

**Files:** Modify `src/aidnd/mind/value.py` (the `move` branch of `utility`). Test:
`tests/mind/test_appraisal.py`.

**Interfaces:** In `utility(a, g, state, world, percept)` for a `move` action, add a social term:
`Σ over present others of −impression_valence(other) × proximity(dest, other)` — moving *toward* a
disliked other lowers utility, moving *away* raises it; liked/charismatic others pull closer. Read
the already-applied `state.relationships[other]["affinity"]` as the cached valence (set by Task 5) —
don't recompute the impression here.

- [ ] **Step 1: Failing test** — construct a small `World` with a disliked other at place `A` and a
  free place `B`; a `move` toward `B` (away) must score higher than a `move` toward `A`.
- [ ] **Step 2: Run → FAIL.** [ ] **Step 3: Implement** the term (≤50 lines; proximity = 1 if same
  place as the other, decayed by `world.dist`). Gate it small enough not to override needs/safety.
  [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `git commit -m "mind: proxemics — sit far from disliked, near liked"`.

**Increment 6 close:** pytest green → `/deploy`.

---

## Task 8: Seed non-human NPCs into the pool

**Files:** Modify the offline forge (`scripts/peoplegen.py` or a small `scripts/seed_races.py`) +
`src/aidnd/worldgen/population.py` if race defaults live there. Test: `tests/worldgen/test_races.py`.

**Interfaces:** A deterministic offline step tags a fraction (~8–12%) of pool NPCs with a non-human
`race` (орк/дворф/эльф) in their `mech`/`persona`, so `race_relations` has real targets. Idempotent;
does not disturb existing placed adults (mirror `depgen`'s top-up discipline).

- [ ] **Step 1: Failing test** — after the seeder, `_pool().list_people()` contains ≥1 non-human
  race and the fraction is within a tolerance; determinism (same seed → same set).
- [ ] **Step 2: Run → FAIL.** [ ] **Step 3: Implement** the seeder (deterministic RNG keyed by id;
  writes race into the pool `mech`/`persona`; skips already-tagged — idempotent). [ ] **Step 4:
  Run → PASS.** [ ] **Step 5: Commit** — `git commit -m "worldgen: seed non-human races into the NPC pool"`.

**Increment 7 close:** pytest green → run the seeder on `worlds.db`, commit the pool, `/deploy`.

---

## Self-Review

- **Spec coverage:** disgust → Task 1; two-layer surface → Task 2 (Surface) + the Hidden gate reuses
  items-inspection (out of this subsystem's scope, flagged); race table + non-humans → Tasks 3, 8;
  impression (A+B+C, personal>culture>personality) → Task 4; apply to emotion + relationship prior →
  Task 5; project onto Bodies incl. player → Task 6; proxemics → Task 7. The *attention economy* and
  *freeform conversation* are Subsystems 2–3 (separate plans) — correctly out of scope here.
- **Type consistency:** `Impression{valence, emo, prior, remember}`, `impression(...)`,
  `appraise_present(...)`, `race_sentiment(...)`, and the `Body` fields `race/squalor/marks/armed()`
  are used identically across Tasks 2–7.
- **Placeholders:** none — each task carries a concrete first test and the exact change. Russian
  strings in tests/examples (`"орк"`, `"замызганный оборванец"`) are game content and stay Russian.

Related: [npc-brain.md](npc-brain.md) (design) · [mind.md](mind.md) · [items.md](items.md)
(surface/hidden precedent) · [bench.md](bench.md) (the autonomous player that gets a trait vector).
