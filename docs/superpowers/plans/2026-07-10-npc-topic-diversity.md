# NPC Topic Diversity & Rumor Saturation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Break the tavern "клад" monoculture — rotate/saturate the shared rumor so a chewed subject fades, and surface each NPC's own persona topics into the live decision prompt.

**Architecture:** All changes in the live-scene ctx assembly (`world.py`) + the mind decision prompt (`llm_agent.py`), reusing the existing `voice._topics_for`. A per-scene heat map (`lv["rumor_heat"]`) models "the room tires of a subject." No caps.

**Tech Stack:** Python 3.14, pytest, `uv run pytest`.

## Global Constraints

- No mechanical gates — model "a room tires of a subject" / "people have their own topics"; never cap who may speak.
- No hardcoded gameplay numbers in code — tunables in the `PB` table (`session/config.py`).
- Mind package `src/aidnd/mind` stays PURE — it only READS `ctx`; `topics_of` is built server-side (`world.py`, which may import `voice._topics_for`) and passed in `ctx`.
- Full suite green before deploy: `uv run pytest /Users/nik/Desktop/dnd-ai/tests` (ABSOLUTE path; shell CWD may not be repo root).
- Deploy each green increment via `/deploy` (commit — NO `Co-Authored-By: Claude` trailer — push origin main, VPS git-reset + restart `aidnd`, verify `active`).

---

## Scope
Increment B1+B2+B3 (spec Units B1–B3). B4 (conversation subject+budget in `convo.py`) is a deferred follow-up.
Spec: [docs/superpowers/specs/2026-07-10-npc-topic-diversity-design.md](../specs/2026-07-10-npc-topic-diversity-design.md).

Current code (verified this session):
- `world.py:667-669`: `rums = lv.get("rumors") or []; rumor_of = {pid: rums[hash((pid, _gt()//1440)) % len(rums)] for pid in order} if rums else {}`
- `world.py:665-666`: `news = [...guild/board...][-2:]; news += _deeds.town_talk(lv["names"], limit=2)`
- `world.py:670-686`: the `ctx = {...}` dict (has `"news": news[:3]`, `"rumor_of": rumor_of`).
- `voice._topics_for(p)` (`narrator/voice.py:158-164`): returns `persona.rumors[:2] + persona.wants[:1]` (or generic filler).
- `llm_agent.py:155-161`: renders the news line and the `«ТЫ слыхал здешний слух: …»` line from `ctx`.

---

### Task 1: Rumor rotation + heat saturation (B1+B2)

**Files:**
- Modify: `src/aidnd/server/play/engine/world.py` (rumor_of/news construction, ~665-669; add `_pick_rumor` helper)
- Modify: `src/aidnd/server/play/engine/session/config.py` (PB knobs)
- Test: `tests/play/test_rumor_saturation.py` (create)

**Interfaces:**
- Produces: `_pick_rumor(pool: list[str], seed_key, heat: dict, hot: float) -> str | None` — module-level pure helper in `world.py`. Returns a rotated pick from the non-hot subset of `pool` (`heat.get(r,0.0) < hot`); `None` if the pool is empty or all subjects are hot.
- Produces: `lv["rumor_heat"]: dict[str,float]` — per-scene subject heat, decayed and warmed each tick.

- [ ] **Step 1: Write the failing tests**

```python
# tests/play/test_rumor_saturation.py
from aidnd.server.play.engine.world import _pick_rumor
from aidnd.server.play.engine.session.config import PB


def test_pick_rotates_by_seed():
    pool = ["a", "b", "c"]
    picks = {_pick_rumor(pool, ("n1", w), {}, 1.0) for w in range(6)}
    assert picks <= set(pool) and len(picks) > 1          # not a single constant


def test_pick_skips_hot_subjects():
    pool = ["a", "b"]
    for _ in range(10):
        assert _pick_rumor(pool, ("n1", 0), {"a": 1.0}, 1.0) == "b"   # 'a' hot → never picked


def test_pick_none_when_all_hot():
    assert _pick_rumor(["a", "b"], ("n1", 0), {"a": 1.0, "b": 1.0}, 1.0) is None


def test_pick_none_on_empty_pool():
    assert _pick_rumor([], ("n1", 0), {}, 1.0) is None


def test_saturation_over_repeated_offers():
    # a subject offered ~rumor_hot/rumor_warm times crosses hot then, after cooling, returns
    pool = ["x"]
    heat = {}
    offered = 0
    while _pick_rumor(pool, ("n", 0), heat, PB["rumor_hot"]) is not None:
        heat["x"] = heat.get("x", 0.0) + PB["rumor_warm"]     # simulate the tick's warm step
        offered += 1
        assert offered < 100                                  # guard
    assert offered >= 2                                       # moderate: lingers a few offers
    # cool it back below hot → offered again
    for _ in range(int(PB["rumor_hot"] / PB["rumor_cool"]) + 1):
        heat["x"] = max(0.0, heat["x"] - PB["rumor_cool"])
    assert _pick_rumor(pool, ("n", 0), heat, PB["rumor_hot"]) == "x"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/play/test_rumor_saturation.py -v`
Expected: FAIL — `_pick_rumor` / PB keys not defined.

- [ ] **Step 3: Add the PB knobs**

In `src/aidnd/server/play/engine/session/config.py`, near `"leisure_social_lift"`/`"workplace_purpose_lift"`:

```python
    # RUMOR SATURATION (docs/.../npc-topic-diversity-design.md): a room tires of a chewed subject
    "rumor_rot_min": 90,     # rotate a location rumor every ~this many game-minutes (was: whole day)
    "rumor_warm": 0.34,      # heat added each time a subject is offered
    "rumor_hot": 1.0,        # heat ≥ this → subject drops out of offered topics (~3 offers)
    "rumor_cool": 0.15,      # heat decay per tick (cools back over ~7 ticks)
```

- [ ] **Step 4: Add `_pick_rumor` and wire heat into the ctx assembly**

In `src/aidnd/server/play/engine/world.py`, add the helper (module level, near `_work_lift`):

```python
def _pick_rumor(pool, seed_key, heat: dict, hot: float):
    """Rotated pick from the NON-hot subset of `pool` (a subject the room has chewed drops out).
    None if the pool is empty or every subject is hot."""
    avail = [r for r in pool if heat.get(r, 0.0) < hot]
    return avail[hash(seed_key) % len(avail)] if avail else None
```

Replace the `rumor_of` construction (world.py:667-669) and heat the offered subjects. After `news`
is built (line 666) and before the `ctx = {...}` dict:

```python
    rums = lv.get("rumors") or []
    heat = lv.setdefault("rumor_heat", {})
    for _k in list(heat):                                  # cool every subject each tick
        heat[_k] = max(0.0, heat[_k] - PB["rumor_cool"])
        if heat[_k] <= 0.0:
            del heat[_k]
    _rot = _gt() // PB["rumor_rot_min"]
    rumor_of = {}
    for _pid in order:
        _r = _pick_rumor(rums, (_pid, _rot), heat, PB["rumor_hot"])
        if _r:
            rumor_of[_pid] = _r
    news = [n for n in news if heat.get(n, 0.0) < PB["rumor_hot"]]   # hot town-talk drops out too
    for _s in set(rumor_of.values()) | set(news):          # warm every subject offered this tick
        heat[_s] = heat.get(_s, 0.0) + PB["rumor_warm"]
```

Keep the existing `ctx["news"] = news[:3]` and `ctx["rumor_of"] = rumor_of` (now the saturated values).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/play/test_rumor_saturation.py -v`
Expected: PASS.

- [ ] **Step 6: Full suite green**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests -q`
Expected: PASS (all).

- [ ] **Step 7: Commit**

```bash
git add src/aidnd/server/play/engine/world.py src/aidnd/server/play/engine/session/config.py tests/play/test_rumor_saturation.py
git commit -m "feat(play/live): rumor rotation + heat saturation — a chewed subject fades from offered topics [topic-diversity]"
```

---

### Task 2: Per-persona topics line (B3)

**Files:**
- Modify: `src/aidnd/server/play/engine/world.py` (add `ctx["topics_of"]` in the `ctx = {...}` dict, ~670-686)
- Modify: `src/aidnd/mind/llm_agent.py` (`build_prompt`, render after the rumor line ~161)
- Test: `tests/mind/test_topics_line.py` (create)

**Interfaces:**
- Consumes: `voice._topics_for(p) -> list[str]` (already exists), `lv["rumor_heat"]` (Task 1).
- Produces: `ctx["topics_of"]: dict[pid, list[str]]` — each present NPC's own topics, hot subjects filtered out.
- `build_prompt` renders `«ТВОИ ТЕМЫ (о чём тебе есть что сказать): …»` from `ctx["topics_of"].get(cfg.id)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/mind/test_topics_line.py
# build_prompt renders the persona-topics line when ctx carries topics_of for this NPC.
from aidnd.mind.llm_agent import build_prompt
from aidnd.mind.model import NpcConfig, NpcState
from aidnd.mind import perceive as mind_perceive
# NOTE (implementer): construct a minimal NpcState/World/percept using the REAL constructors
# (see how existing tests in tests/mind build these — e.g. test_emergent.py). Keep the assertion:


def _prompt_text(state, world, percept, ctx):
    msgs = build_prompt(state, world, percept, ctx, prefs=[])
    return "\n".join(m["content"] for m in msgs)


def test_topics_line_rendered_when_present(minimal_state_world_percept):
    state, world, percept = minimal_state_world_percept
    ctx = {"topics_of": {state.config.id: ["пропавший караван", "новая пошлина"]}}
    text = _prompt_text(state, world, percept, ctx)
    assert "ТВОИ ТЕМЫ" in text
    assert "пропавший караван" in text


def test_topics_line_absent_when_empty(minimal_state_world_percept):
    state, world, percept = minimal_state_world_percept
    text = _prompt_text(state, world, percept, {"topics_of": {}})
    assert "ТВОИ ТЕМЫ" not in text
```

(Implementer: add a small `minimal_state_world_percept` fixture built from the real `mind` constructors — mirror an existing `tests/mind` test's setup. The two assertions are what matter.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/mind/test_topics_line.py -v`
Expected: FAIL — no `ТВОИ ТЕМЫ` line rendered.

- [ ] **Step 3: Render the line in `build_prompt`**

In `src/aidnd/mind/llm_agent.py`, after the rumor block (lines 158-161), add:

```python
    my_topics = (ctx.get("topics_of") or {}).get(cfg.id) or []
    if my_topics:
        lines.append("  ТВОИ ТЕМЫ (о чём тебе есть что сказать): "
                     + "; ".join(f"«{t}»" for t in my_topics[:3]) + " — заведи, к слову.")
```

- [ ] **Step 4: Build `ctx["topics_of"]` in `world.py`**

In `src/aidnd/server/play/engine/world.py`, import `_topics_for` (from `narrator/voice.py` — check the existing import of `voice`/`_topics_for`; `resolve.py` re-exports `_VOICE`/narrator symbols, so import `_topics_for` from where the file already gets narrator helpers). Then add to the `ctx = {...}` dict, filtering hot subjects with the same `heat`:

```python
        "topics_of": {pid: [t for t in _topics_for(people[pid])
                            if heat.get(t, 0.0) < PB["rumor_hot"]]
                      for pid in order},
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/mind/test_topics_line.py -v`
Expected: PASS.

- [ ] **Step 6: Full suite green**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests -q`
Expected: PASS (all).

- [ ] **Step 7: Commit**

```bash
git add src/aidnd/server/play/engine/world.py src/aidnd/mind/llm_agent.py tests/mind/test_topics_line.py
git commit -m "feat(mind): per-persona ТВОИ ТЕМЫ line — NPCs raise their own rumors/wants, not just the town rumor [topic-diversity]"
```

---

### Task 3: Playtest + tune + deploy (manual, gated)

**Files:** none.

- [ ] **Step 1: Boot a real-LLM dev server**

Run (background): `AIDND_OPEN_PLAY=1 AIDND_PROFILE=deepseek .venv/bin/python -m uvicorn aidnd.server.app:app --host 127.0.0.1 --port 8100`

- [ ] **Step 2: Drive a tavern and observe topic spread**

Drive `/api/play/enter` a tavern → `/api/play/live` ×6, capture the digest/feed.
Expected (before/after): the room carries **≥2 distinct subjects** at once; the dominant rumor **fades within a few ticks** instead of every NPC chanting it; NPCs raise their own persona topics.

- [ ] **Step 3: Tune if needed**

If subjects still monoculture, lower `rumor_hot` or raise `rumor_warm` (burn out faster). If topics feel too scattered/incoherent, raise `rumor_hot`. Commit any tuning change.

- [ ] **Step 4: Deploy**

Run the `/deploy` flow (pytest green → commit → push origin main → VPS git-reset + restart `aidnd` → verify `active`).

## Self-review notes
- Spec coverage: B1 (rotation, Task 1 Step 4 `_rot`), B2 (heat, Task 1), B3 (topics line, Task 2). Playtest per spec Testing (Task 3).
- Tuning values are real starting numbers (`rumor_rot_min=90`, `rumor_warm=0.34`, `rumor_hot=1.0`, `rumor_cool=0.15`), tuned in Task 3.
- Type consistency: `_pick_rumor(pool, seed_key, heat, hot) -> str | None`; `heat: dict[str,float]`; `ctx["topics_of"]: dict[pid, list[str]]` — used identically across tasks.
