# Emergent Quests — Inc 1 (Honest Bridge) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** build the dormant "honest bridge" that translates a giver's real `Milestone.done` into a contract completion predicate and, when an emergent (`src:"sift"`) contract completes, advances that giver's real `Agenda.cursor` and re-plans — so finishing an emergent quest IS the giver's milestone closing.

**Architecture:** a NEW pure package `src/aidnd/server/play/engine/quests/` with `bridge.py` (mind-only imports; reuses `agenda._met` and `llm_agent.plan_agenda`), plus a thin play-engine adapter + hooks in `contracts.py`. Inc 1 ships **dormant**: no code writes `src:"sift"` contracts yet (Inc 2 does the sift→cast→persist), so the bridge is exercised only by unit tests and a light integration harness. Improvised contracts (`_make_contract`, no `src`) are provably untouched.

**Tech Stack:** Python 3.14, `uv run pytest`, SQLite `WorldStore`, `aidnd.mind` (State/World/Body/Item, `Agenda`/`Milestone`/`_met`, `plan_agenda`).

## Global Constraints

(Copied verbatim from the spec — every task's requirements implicitly include this section.)

- Code owns dice/inventory/numbers (no LLM in `bridge.py` except the existing `plan_agenda` call it triggers).
- Predicates never change mid-quest — `done_any[0]` never mutates; disjuncts only append.
- Improvised contracts unchanged (`_make_contract`'s random-container errands stay as fallback texture; emergent quests are marked `src:"sift"`, improvised ones are not).
- Tunables live in PB (`session/config.py`). **Inc 1 introduces no new numeric tunable** — the bridge has no magic numbers; the `quest_*` PB keys belong to Inc 2/3 (salience/director) and are NOT added here.
- Russian commit messages `feat(play/quests): …`.
- NEVER a `Co-Authored-By` trailer on commits.
- Tests via `uv run pytest`.

**Interface contract (Inc 2/3 plans are written in parallel against these EXACT names — do NOT rename):**
```python
# src/aidnd/server/play/engine/quests/bridge.py
def milestone_to_step(m) -> dict | None      # {kind, want?, target?, where?} per spec §4 table; None if not delegatable
def make_done_any(m) -> list[dict]           # [dict(m.done)] — verbatim copy, [0] is always the milestone predicate
def done_any_met(ct: dict, giver_state) -> bool   # any disjunct _met for the giver
def quest_writeback(ct: dict, giver_state, manager=None) -> bool  # guard + cursor+=1 + plan_agenda; True if advanced
```

**Resolved ambiguity — `giver_state`:** the interface names a single `giver_state`, but `agenda._met(cond, state, world)` needs BOTH a mind `State` and a mind `World` (loot/place live on `world.bodies[state.config.id]`, not on `State` — verified in `mind/model.py:60` and `mind/world.py:36`). **Resolution: `giver_state` is the pair `(state, world)`** — the giver's `NpcState` and a mind `World` in which the giver's `Body` carries their current loot. This mirrors how `advance_agendas(state, world)` and the `test_agenda.py` fixtures already pair the two. The play engine builds this pair from the live store (`_giver_world`, Task 3); unit tests build it directly like `test_agenda.py`.

**Contract data fields (spec §4, read-only in Inc 1):** `data["seed"]`, `data["arc"]`, `data["roles"]`, `data["src"]=="sift"`, `data["done_any"]`.

---

## File Structure

- **Create** `src/aidnd/server/play/engine/quests/__init__.py` — empty package marker.
- **Create** `src/aidnd/server/play/engine/quests/bridge.py` — the four pure interface functions + a private `_anchor_idx` helper. Mind-only imports (`agenda._met`, `llm_agent.plan_agenda`).
- **Modify** `src/aidnd/server/play/mechanics/contracts.py` — add `_giver_world(ct)` adapter, `_sift_maybe_close()` predicate-driven closer, wire it into the four completion triggers, and add the writeback hook at the tail of `_contract_complete`.
- **Modify** `src/aidnd/server/play/mechanics/combat.py` — wire `_sift_maybe_close()` into `_contract_on_death`.
- **Create** `tests/play/test_quests_bridge.py` — pure unit tests (Tasks 1 & 2).
- **Create** `tests/play/test_quests_hook.py` — play-engine integration tests (Task 3).

---

## Task 1: Milestone → step translation + verbatim `done_any`

**Files:**
- Create: `src/aidnd/server/play/engine/quests/__init__.py`
- Create: `src/aidnd/server/play/engine/quests/bridge.py`
- Test: `tests/play/test_quests_bridge.py`

**Interfaces:**
- Produces:
  - `milestone_to_step(m) -> dict | None` — `have`→`{"kind":"bring","want":<item>}`, `dead`→`{"kind":"dead","target":<id>}`, `wealth`→`{"kind":"bring"}` (casting fills `want` with a real valuable), `affinity`→`{"kind":"deliver","target":<id>}` (casting fills `want` with the gift), `at`→`None` (not delegatable), anything else→`None`.
  - `make_done_any(m) -> list[dict]` — `[dict(m.done)]`, a verbatim shallow copy; `[0]` is always the milestone predicate.

- [ ] **Step 1: Create the package marker**

Create `src/aidnd/server/play/engine/quests/__init__.py` with exactly:

```python
"""Emergent-quest pipeline (see docs/superpowers/specs/2026-07-12-emergent-quests-design.md).
Inc 1 ships only bridge.py (the honest milestone↔predicate↔writeback bridge)."""
```

- [ ] **Step 2: Write the failing translation tests**

Create `tests/play/test_quests_bridge.py`:

```python
"""Inc 1 honest bridge (docs/superpowers/specs/2026-07-12-emergent-quests-design.md §4):
Milestone.done → contract step (5 real _met kinds), verbatim done_any, giver-relative
done_any evaluation, and the completion writeback that advances the giver's real Agenda."""

from __future__ import annotations

from aidnd.mind import Body, Item, NpcConfig, NpcState
from aidnd.mind.agenda import Agenda, Milestone
from aidnd.mind.world import World
from aidnd.server.play.engine.quests import bridge


def _m(done: dict) -> Milestone:
    return Milestone("веха", "acquire", "цель", {}, done)


# ── §4 table: all 5 real _met kinds → step (or None) ──
def test_translate_have_to_bring():
    assert bridge.milestone_to_step(_m({"type": "have", "item": "гроссбух"})) == {
        "kind": "bring", "want": "гроссбух"}


def test_translate_dead_to_dead():
    assert bridge.milestone_to_step(_m({"type": "dead", "id": "npc:ralf"})) == {
        "kind": "dead", "target": "npc:ralf"}


def test_translate_wealth_to_bring_want_filled_by_casting():
    step = bridge.milestone_to_step(_m({"type": "wealth", "value": 100}))
    assert step == {"kind": "bring"}          # `want` (a real valuable) is casting's job
    assert "want" not in step


def test_translate_affinity_to_deliver_gift():
    step = bridge.milestone_to_step(_m({"type": "affinity", "id": "npc:x", "value": 0.5}))
    assert step == {"kind": "deliver", "target": "npc:x"}   # `want` (the gift) is casting's job


def test_translate_at_is_not_delegatable():
    assert bridge.milestone_to_step(_m({"type": "at", "place": "дом"})) is None


def test_translate_never_and_unknown_are_not_delegatable():
    assert bridge.milestone_to_step(_m({"type": "never"})) is None
    assert bridge.milestone_to_step(_m({})) is None


# ── done_any[0] is a VERBATIM copy of Milestone.done ──
def test_make_done_any_is_verbatim_copy():
    m = _m({"type": "have", "item": "гроссбух"})
    res = bridge.make_done_any(m)
    assert res == [{"type": "have", "item": "гроссбух"}]
    res[0]["item"] = "подделка"                # mutating the copy must NOT touch the milestone
    assert m.done == {"type": "have", "item": "гроссбух"}
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/play/test_quests_bridge.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'aidnd.server.play.engine.quests.bridge'` (import error at collection).

- [ ] **Step 4: Write the minimal implementation**

Create `src/aidnd/server/play/engine/quests/bridge.py`:

```python
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

from aidnd.mind.agenda import _met
from aidnd.mind.llm_agent import plan_agenda


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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/play/test_quests_bridge.py -q`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add src/aidnd/server/play/engine/quests/__init__.py \
        src/aidnd/server/play/engine/quests/bridge.py \
        tests/play/test_quests_bridge.py
git commit -m "feat(play/quests): мост веха→шаг + дословный done_any (inc 1)"
```

---

## Task 2: giver-relative `done_any` evaluation + completion writeback

**Files:**
- Modify: `src/aidnd/server/play/engine/quests/bridge.py`
- Test: `tests/play/test_quests_bridge.py` (append)

**Interfaces:**
- Consumes: `agenda._met(cond, state, world)` (`agenda.py:59`), `llm_agent.plan_agenda(state, world, ctx, manager)` (`llm_agent.py:300`), `Agenda.current()` (`agenda.py:42`).
- Produces:
  - `done_any_met(ct: dict, giver_state) -> bool` — `giver_state=(state, world)`; True iff ANY `cond` in `ct["done_any"]` satisfies `_met(cond, state, world)`.
  - `quest_writeback(ct: dict, giver_state, manager=None) -> bool` — for `ct["src"]=="sift"` only: guard (`done_any[0]` still `_met` for the giver AND the anchored milestone still open/unadvanced), then `agendas[i].cursor += 1`; if the agenda is now exhausted, mark it `done` and (when `manager` is not None) `plan_agenda` the giver's next ambition and append it. Returns True iff the cursor advanced. Guarded per §6 so an already-advanced ("milestone moot") writeback is a no-op returning False.

- [ ] **Step 1: Write the failing evaluation + writeback tests**

Append to `tests/play/test_quests_bridge.py`:

```python
# ── helpers: a giver State + a mind World holding their loot (mirrors test_agenda.py) ──
def _giver(pid: str, done: dict, loot=(), rels=None, cursor=0):
    cfg = NpcConfig(id=pid, name=pid)
    st = NpcState.from_config(cfg)
    st.relationships = dict(rels or {})
    st.agendas = [Agenda("цель", "ambition", 0.7, [Milestone("веха", "acquire", "цель", {}, done)])]
    st.agendas[0].cursor = cursor
    w = World()
    w.add(Body(id=pid, place="дом", loot=[Item(n, 0.5) for n in loot]))
    return st, w


def _ct(**over) -> dict:
    base = {"src": "sift", "giver": "npc:dunn", "done_any": [{"type": "have", "item": "гроссбух"}]}
    base.update(over)
    return base


# ── done_any_met: ANY disjunct true for the giver ──
def test_done_any_met_true_when_have():
    st, w = _giver("npc:dunn", {"type": "have", "item": "гроссбух"}, loot=["гроссбух Марты"])
    assert bridge.done_any_met(_ct(), (st, w)) is True


def test_done_any_met_false_when_none_hold():
    st, w = _giver("npc:dunn", {"type": "have", "item": "гроссбух"}, loot=["хлеб"])
    assert bridge.done_any_met(_ct(), (st, w)) is False


def test_done_any_met_true_via_second_disjunct():
    st, w = _giver("npc:dunn", {"type": "have", "item": "гроссбух"}, loot=["хлеб"])
    w.add(Body(id="npc:ralf", place="дом", hp=0, alive=False))
    ct = _ct(done_any=[{"type": "have", "item": "гроссбух"}, {"type": "dead", "id": "npc:ralf"}])
    assert bridge.done_any_met(ct, (st, w)) is True


# ── writeback: advances the giver's real cursor AND re-plans the next ambition ──
def test_writeback_advances_cursor_and_replans(monkeypatch):
    calls = []
    monkeypatch.setattr(bridge, "plan_agenda", lambda *a, **k: calls.append(a) or None)
    st, w = _giver("npc:dunn", {"type": "have", "item": "гроссбух"}, loot=["гроссбух Марты"])
    ok = bridge.quest_writeback(_ct(), (st, w), manager=object())
    assert ok is True
    assert st.agendas[0].cursor == 1                 # honest bridge: the giver's real goal moved
    assert st.agendas[0].status == "done"            # single-milestone agenda exhausted
    assert len(calls) == 1                           # plan_agenda re-planned the next ambition


def test_writeback_skips_non_sift():
    st, w = _giver("npc:dunn", {"type": "have", "item": "гроссбух"}, loot=["гроссбух Марты"])
    assert bridge.quest_writeback(_ct(src="improvised"), (st, w)) is False
    assert st.agendas[0].cursor == 0
    assert bridge.quest_writeback({"giver": "npc:dunn", "done_any": [{"type": "have", "item": "г"}]},
                                  (st, w)) is False   # no src key at all → improvised


def test_writeback_guards_moot(monkeypatch):
    spy = []
    monkeypatch.setattr(bridge, "plan_agenda", lambda *a, **k: spy.append(1))
    # (a) predicate no longer holds → no advance
    st, w = _giver("npc:dunn", {"type": "have", "item": "гроссбух"}, loot=["хлеб"])
    assert bridge.quest_writeback(_ct(), (st, w), manager=object()) is False
    assert st.agendas[0].cursor == 0
    # (b) milestone already advanced (cursor moved on) → no double advance
    st2, w2 = _giver("npc:dunn", {"type": "have", "item": "гроссбух"},
                     loot=["гроссбух Марты"], cursor=1)
    assert bridge.quest_writeback(_ct(), (st2, w2), manager=object()) is False
    assert st2.agendas[0].cursor == 1
    assert spy == []                                  # never re-planned on a mooted writeback
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/play/test_quests_bridge.py -q`
Expected: FAIL — `AttributeError: module 'aidnd.server.play.engine.quests.bridge' has no attribute 'done_any_met'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `src/aidnd/server/play/engine/quests/bridge.py`:

```python
def done_any_met(ct: dict, giver_state) -> bool:
    """True iff ANY disjunct in ct['done_any'] is _met for the giver. giver_state = (state, world).
    'However obtained' (spec §3a): the predicate is checked on the giver's real state, regardless of
    which trigger/route produced it."""
    state, world = giver_state
    return any(_met(cond, state, world) for cond in (ct.get("done_any") or []))


def _anchor_idx(ct: dict, agendas: list, target: dict) -> int | None:
    """Which of the giver's agendas this quest anchors. Prefer the explicit seed evidence tag
    'agenda:<pid>:<idx>' (spec §4 data model); else fall back to the agenda whose CURRENT milestone
    IS this predicate (an unadvanced anchor)."""
    for ev in ((ct.get("seed") or {}).get("evidence") or []):
        if isinstance(ev, str) and ev.startswith("agenda:"):
            try:
                return int(ev.rsplit(":", 1)[1])
            except (ValueError, IndexError):
                pass
    for i, ag in enumerate(agendas):
        m = ag.current()
        if m is not None and dict(m.done) == dict(target):
            return i
    return None


def quest_writeback(ct: dict, giver_state, manager=None) -> bool:
    """Completion of a src:"sift" contract advances the giver's REAL agenda (spec §3b, §5 Step 5):
    verify done_any[0] still _met for the giver AND the anchored milestone still open/unadvanced,
    then cursor += 1; if the agenda is now exhausted, mark it done and (with a manager) plan_agenda
    the next ambition. Guard (§6 'milestone moot'): a no-op returning False if already advanced or the
    predicate no longer holds. Returns True iff the cursor advanced."""
    if ct.get("src") != "sift":                          # improvised contracts never write back
        return False
    state, world = giver_state
    done_any = ct.get("done_any") or []
    if not done_any or not _met(done_any[0], state, world):   # predicate must STILL hold
        return False
    agendas = getattr(state, "agendas", None) or []
    idx = _anchor_idx(ct, agendas, done_any[0])
    if idx is None or not (0 <= idx < len(agendas)):
        return False
    ag = agendas[idx]
    m = ag.current()
    if m is None or dict(m.done) != dict(done_any[0]):   # already advanced / different milestone
        return False
    ag.cursor += 1                                        # agenda.py:42 — the honest bridge fires
    if ag.cursor >= len(ag.milestones):                  # whole ambition reached → form a new one
        ag.status = "done"
        if manager is not None:
            ctx = {"roles": {state.config.id: getattr(state.config, "role", "")}}
            newag = plan_agenda(state, world, ctx, manager)
            if newag is not None:
                agendas.append(newag)
    return True
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/play/test_quests_bridge.py -q`
Expected: PASS (13 tests total).

- [ ] **Step 5: Commit**

```bash
git add src/aidnd/server/play/engine/quests/bridge.py tests/play/test_quests_bridge.py
git commit -m "feat(play/quests): оценка done_any + writeback вехи с guard (inc 1)"
```

---

## Task 3: play-engine wiring — giver world, predicate-driven close, writeback hook

**Files:**
- Modify: `src/aidnd/server/play/mechanics/contracts.py` (add `_giver_world`, `_sift_maybe_close`; wire the three triggers `_contract_on_give:343`/`_contract_on_move:371`/`_contract_on_talk:380`; add the writeback hook at the tail of `_contract_complete:311`)
- Modify: `src/aidnd/server/play/mechanics/combat.py` (wire `_contract_on_death:360`)
- Test: `tests/play/test_quests_hook.py`

**Interfaces:**
- Consumes: `bridge.done_any_met(ct, giver_state)`, `bridge.quest_writeback(ct, giver_state, manager)` (Task 2); existing `_contract_complete(ct)` (`contracts.py:311`), `_store()`/`_wid()`/`_S`/`_materialize_npc` (`core`/`items`).
- Produces (module-level in `contracts.py`, importable by `combat.py`):
  - `_giver_world(ct: dict) -> tuple` — `(giver_state, world)`: the giver's `NpcState` plus a mind `World` whose giver `Body` carries the giver's real store loot (purse + inventory), and where each `dead`-disjunct target gets a `Body` reflecting its `dead|<id>` flag. This is the `giver_state` the bridge consumes.
  - `_sift_maybe_close() -> str | None` — sweeps active `src:"sift"` contracts; the first whose `done_any_met` is true is completed via `_contract_complete` and its narration returned. Non-sift contracts are skipped (the step engine stays authoritative for them).

- [ ] **Step 1: Write the failing integration tests**

Create `tests/play/test_quests_hook.py`:

```python
"""Inc 1 play wiring: a src:"sift" contract closes predicate-driven and its completion advances the
giver's real Agenda cursor via the writeback hook; improvised contracts are provably untouched
(no writeback, step engine unchanged)."""

from __future__ import annotations

import pytest

from aidnd.mind import Body, Item, NpcConfig, NpcState, World
from aidnd.mind.agenda import Agenda, Milestone
from aidnd.server.play.engine import core
from aidnd.server.play.engine import deeds as dd
from aidnd.server.play.mechanics import contracts
from aidnd.worldgen import WorldStore


class _P:
    def __init__(self, name, role, done, cursor=0):
        self.name, self.role, self.work, self.persona = name, role, None, {}
        cfg = NpcConfig(id="npc:dunn", name=name, role=role)
        self.state = NpcState.from_config(cfg)
        self.state.agendas = [Agenda("вернуть гроссбух", "ambition", 0.7,
                                     [Milestone("вернуть гроссбух", "acquire", "цель", {}, done)])]
        self.state.agendas[0].cursor = cursor
        self.charisma = 0.3
        self.appearance = 0.3


@pytest.fixture
def world(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    for mod in (core, contracts, dd):
        monkeypatch.setattr(mod, "_store", lambda: st, raising=False)
        monkeypatch.setattr(mod, "_wid", lambda: 1, raising=False)
    # keep _contract_complete's heavy store side-effects out of the way — Inc 1 tests the bridge
    monkeypatch.setattr(contracts, "_materialize_npc", lambda *a, **k: None)
    monkeypatch.setattr(contracts, "_pc_remember", lambda *a, **k: None)
    monkeypatch.setattr(contracts, "_npc_save", lambda *a, **k: None)
    monkeypatch.setattr(dd, "record", lambda *a, **k: None)
    people = {"npc:dunn": _P("Дунн", "горожанин", {"type": "have", "item": "гроссбух"})}
    core._S["people"] = people
    core._S["model"] = None                             # no LLM → writeback advances but skips replan
    st.purse_add(1, "npc:dunn", 40)
    st.purse_add(1, "pc", 0)
    return st, people


def _giver_holds(st, name):
    # a mind (state, world) where the giver carries `name` → _met(have) true
    def _fake(ct):
        p = core._S["people"][ct["giver"]]
        w = World()
        w.add(Body(id=ct["giver"], place="дом", loot=[Item(name, 0.5)]))
        return p.state, w
    return _fake


def test_sift_completion_writes_back_cursor(world, monkeypatch):
    st, people = world
    monkeypatch.setattr(contracts, "_giver_world", _giver_holds(st, "гроссбух Марты"))
    st.save_contract(1, "ct:dunn:1", "active", {
        "giver": "npc:dunn", "giver_name": "Дунн", "kind": "bring", "want": "гроссбух",
        "where": "", "step": 0, "steps": [{"kind": "bring", "want": "гроссбух"}],
        "reward": 30, "reward_item": None,
        "src": "sift", "arc": {"beat": "active"}, "roles": {"giver": "npc:dunn"},
        "done_any": [{"type": "have", "item": "гроссбух"}]})
    ct = next(c for c in st.contracts(1, "active") if c["id"] == "ct:dunn:1")
    contracts._contract_complete(ct)
    assert people["npc:dunn"].state.agendas[0].cursor == 1     # real agenda advanced
    assert st.contracts(1, "active") == []                     # contract closed


def test_improvised_completion_never_writes_back(world, monkeypatch):
    st, people = world
    monkeypatch.setattr(contracts, "_giver_world", _giver_holds(st, "гроссбух Марты"))
    st.save_contract(1, "ct:dunn:2", "active", {
        "giver": "npc:dunn", "giver_name": "Дунн", "kind": "bring", "want": "гроссбух",
        "where": "", "step": 0, "steps": [{"kind": "bring", "want": "гроссбух"}],
        "reward": 30, "reward_item": None})               # NO src → improvised
    ct = next(c for c in st.contracts(1, "active") if c["id"] == "ct:dunn:2")
    contracts._contract_complete(ct)
    assert people["npc:dunn"].state.agendas[0].cursor == 0     # untouched
    assert [c["id"] for c in st.contracts(1, "done")] == ["ct:dunn:2"]   # but still paid/closed


def test_sift_maybe_close_completes_only_predicate_met_sift(world, monkeypatch):
    st, people = world
    monkeypatch.setattr(contracts, "_giver_world", _giver_holds(st, "гроссбух Марты"))
    st.save_contract(1, "ct:sift", "active", {
        "giver": "npc:dunn", "giver_name": "Дунн", "kind": "dead", "target": "npc:ralf",
        "where": "", "step": 0, "steps": [{"kind": "dead", "target": "npc:ralf"}],
        "reward": 10, "reward_item": None, "src": "sift",
        "done_any": [{"type": "have", "item": "гроссбух"}]})   # already true via giver loot
    st.save_contract(1, "ct:imp", "active", {
        "giver": "npc:dunn", "giver_name": "Дунн", "kind": "bring", "want": "меч",
        "where": "", "step": 0, "steps": [{"kind": "bring", "want": "меч"}],
        "reward": 5, "reward_item": None})                # improvised — ignored by the sweep
    narr = contracts._sift_maybe_close()
    assert narr and "Уговор исполнен" in narr
    active = {c["id"] for c in st.contracts(1, "active")}
    assert active == {"ct:imp"}                            # only the sift one closed
    assert people["npc:dunn"].state.agendas[0].cursor == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/play/test_quests_hook.py -q`
Expected: FAIL — `AttributeError: <module 'aidnd.server.play.mechanics.contracts'> does not have the attribute '_giver_world'` (monkeypatch target missing).

- [ ] **Step 3: Add `_giver_world` and `_sift_maybe_close` to `contracts.py`**

In `src/aidnd/server/play/mechanics/contracts.py`, insert these two functions immediately **before** `def _contract_on_give` (currently line 343):

```python
def _giver_world(ct: dict) -> tuple:
    """Build the giver-relative (state, world) the bridge consumes: the giver's Body carries their
    REAL store loot (purse + inventory) so have/wealth predicates read true; each dead-disjunct target
    gets a Body reflecting its dead-flag; affinity reads state.relationships. Dormant in Inc 1 — only
    src:"sift" contracts (Inc 2+) ever reach it."""
    from aidnd.mind import Body as _MBody
    from aidnd.mind import Item as _MItem
    from aidnd.mind import World as _MWorld

    giver = ct["giver"]
    p = _S["people"][giver]
    _materialize_npc(giver, "pockets")
    loot = []
    coins = _store().purse_get(_wid(), giver)
    if coins > 0:
        loot.append(_MItem("кошель", min(1.0, coins / 40), kind="coin", amount=coins))
    for r in _store().inventory(_wid(), giver):
        it = _store().get_item(r["item_id"])
        if it:
            loot.append(_MItem(it["name"], min(1.0, (it.get("worth") or 0) / 40)))
    w = _MWorld()
    w.add(_MBody(id=giver, place="", loot=loot))
    for cond in ct.get("done_any") or []:
        if cond.get("type") == "dead":
            vid = cond.get("id")
            if vid and vid not in w.bodies:
                dead = bool(_store().flag_get(_wid(), f"dead|{vid}"))
                w.add(_MBody(id=vid, place="", hp=0 if dead else 10, alive=not dead))
    return p.state, w


def _sift_maybe_close() -> str | None:
    """Predicate-driven close for emergent (src:"sift") contracts (spec §3a 'however obtained'):
    any active sift contract whose done_any holds for the giver completes now, whatever route made it
    true. Improvised contracts are skipped — their step engine stays authoritative."""
    from aidnd.server.play.engine.quests import bridge as _qb

    for ct in _store().contracts(_wid(), "active"):
        if ct.get("src") != "sift":
            continue
        if _qb.done_any_met(ct, _giver_world(ct)):
            return _contract_complete(ct)
    return None
```

- [ ] **Step 4: Add the writeback hook to `_contract_complete`**

In `_contract_complete` (`contracts.py:311`), the body ends with:

```python
    _npc_save(giver)
    return f"Уговор исполнен! {paid}."
```

Replace those two lines with:

```python
    _npc_save(giver)
    if ct.get("src") == "sift":  # honest bridge (Inc 1): advance the giver's REAL agenda + re-plan
        from aidnd.server.play.engine.quests import bridge as _qb

        try:
            _qb.quest_writeback(ct, _giver_world(ct), _S.get("model"))
        except Exception:  # noqa: BLE001 — writeback must NEVER break the payout it follows
            pass
    return f"Уговор исполнен! {paid}."
```

- [ ] **Step 5: Wire the three same-file triggers to consult `_sift_maybe_close` first**

In `_contract_on_give` (`contracts.py:343`), insert as the FIRST line of the body (before `for ct in _store().contracts(...)`):

```python
    hit = _sift_maybe_close()  # sift closes predicate-driven, whatever route was taken
    if hit:
        return hit
```

Do the same — insert the identical two-line guard as the first body statement — in `_contract_on_move` (`contracts.py:371`) and `_contract_on_talk` (`contracts.py:380`).

- [ ] **Step 6: Wire `_contract_on_death` in `combat.py`**

`combat.py` already imports `_ct_advance, _ct_cur` from `contracts` (`combat.py:46`). Change that import line to also bring in `_sift_maybe_close`:

```python
from aidnd.server.play.mechanics.contracts import _ct_advance, _ct_cur, _sift_maybe_close
```

Then in `_contract_on_death` (`combat.py:360`), insert as the FIRST line of the body (before `for ct in _store().contracts(...)`):

```python
    hit = _sift_maybe_close()  # villain down by ANY hand → a sift dead-disjunct may close now
    if hit:
        return hit
```

- [ ] **Step 7: Run the integration tests to verify they pass**

Run: `uv run pytest tests/play/test_quests_hook.py -q`
Expected: PASS (3 tests).

- [ ] **Step 8: Run the contracts/combat regression neighborhood**

Run: `uv run pytest tests/play tests/combat -q`
Expected: PASS — no existing play/combat test regressed by the trigger guards (improvised contracts are skipped by `_sift_maybe_close`'s `src != "sift"` continue, so their step engine is unchanged).

- [ ] **Step 9: Commit**

```bash
git add src/aidnd/server/play/mechanics/contracts.py \
        src/aidnd/server/play/mechanics/combat.py \
        tests/play/test_quests_hook.py
git commit -m "feat(play/quests): предикатное закрытие sift + writeback-хук в _contract_complete (inc 1)"
```

---

## Task 4: full-suite green

**Files:** none (verification only).

- [ ] **Step 1: Run the full suite**

Run: `uv run pytest tests -q`
Expected: PASS — the prior baseline (363 passed) plus the new Inc 1 tests (16: 13 in `test_quests_bridge.py`, 3 in `test_quests_hook.py`) → **379 passed**, 0 failed. If any pre-existing test fails, it is a regression from Task 3's trigger wiring — inspect the failing trigger path and confirm the `src != "sift"` skip leaves improvised contracts untouched.

- [ ] **Step 2: Commit only if Step 1 changed anything**

No file changes are expected in Task 4. If Step 1 surfaced a regression that required an edit, re-run `uv run pytest tests -q` to confirm green, then:

```bash
git add -A
git commit -m "feat(play/quests): зелёный прогон полного набора после inc 1"
```

Otherwise skip the commit — the suite is already green from Task 3.

---

## Self-Review

**1. Spec coverage (Inc 1 scope):**
- §3b bridge diagram (Milestone → step → done_any → complete → writeback → guard): Task 1 (`milestone_to_step`, `make_done_any`), Task 2 (`quest_writeback` with the `_met`+open-milestone guard), Task 3 (the `_contract_complete` hook). ✔
- §4 bridge table — all 5 real `_met` kinds: `have`/`dead`/`wealth`/`affinity` map to steps; `at`→None. Task 1 tests each. ✔
- §4 data model fields (`seed`/`arc`/`roles`/`src`/`done_any`): read-only in Inc 1; `done_any` consumed by `done_any_met`/`quest_writeback`, `seed.evidence` by `_anchor_idx`, `src` gates the writeback. No writer (Inc 2). ✔
- §5 Step 5 writeback path (verify `_met(done_any[0])` → cursor+=1 → `plan_agenda`): `quest_writeback`, tested in Task 2 + Task 3. ✔
- §6 "milestone moot" writeback guard (skip if already advanced / predicate no longer holds): `quest_writeback`'s two guards, `test_writeback_guards_moot`. ✔
- §9 Inc 1 (bridge ships standalone; improvised contracts keep working with `src:"sift"` marking emergent): Task 3 regression test `test_improvised_completion_never_writes_back` + the `src != "sift"` skips. ✔
- §10 resolved affinity→deliver-gift: `milestone_to_step` returns `{"kind":"deliver","target":X}`. ✔
- Testing strategy §7 Inc 1: translation for 5 kinds (`at` yields no seed) ✔; completion advances cursor + `plan_agenda` called ✔; improvised no-writeback regression ✔.

**2. Placeholder scan:** no TBD/TODO/"handle edge cases"/"similar to Task N"; every code step shows complete code; every test step shows full test bodies. ✔

**3. Type consistency:** `giver_state=(state, world)` used identically in `done_any_met`, `quest_writeback`, `_giver_world`, and all tests. `milestone_to_step` return shapes (`{"kind":"bring","want":…}`, `{"kind":"dead","target":…}`, `{"kind":"bring"}`, `{"kind":"deliver","target":…}`, `None`) match the Task 1 tests and the §4 table. `quest_writeback(ct, giver_state, manager=None)`, `done_any_met(ct, giver_state)`, `make_done_any(m)`, `milestone_to_step(m)` — names/arities identical to the interface contract everywhere they appear. `_sift_maybe_close()` / `_giver_world(ct)` names consistent across `contracts.py`, `combat.py` import, and the hook tests. ✔

**Ambiguities resolved:** (a) `giver_state` type — pair `(state, world)`, because `_met` needs both and `State` carries no loot (documented above). (b) "plan_agenda for the next milestone" — `plan_agenda` authors a whole `Agenda`, so it is invoked only when the current agenda is EXHAUSTED after `cursor += 1` (the giver forms his next ambition, matching §5 Step 5 row 6 "his new ambition"); a still-unfinished agenda simply advances to its pre-authored next milestone. (c) "wire done_any into triggers" — implemented as `_sift_maybe_close()` consulted first in all four triggers, giving `src:"sift"` contracts predicate-driven "however obtained" closure while `src != "sift"` short-circuits keep the improvised step engine authoritative. (d) No new PB tunables in Inc 1 (the `quest_*` keys are Inc 2/3 salience/director weights).
