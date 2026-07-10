# The Room Hears the Player (Workstream C, inc 1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** When the player speaks to the room, NPCs who *hear* it can react — emergently (some engage, busy/hostile ones don't), via audibility + their own utility. Fixes "no one reacts to me speaking."

**Architecture:** The player's untargeted utterance is recorded on the live scene (`lv["pc_said"]`); in the tick, each present NPC that can *hear* it (audibility) gets a tier-scaled impulse to react and the line in its prompt; whether it replies is `decide_hybrid`'s own call. No caps. First real slice of the attention economy.

**Tech Stack:** Python 3.14, pytest, `uv run pytest`.

## Global Constraints

- No mechanical gates — the impulse only *raises* an NPC's pull to react; it never forces a reply or caps who speaks. Reaction is emergent (`decide_hybrid`).
- No hardcoded gameplay numbers in code — tunables in `PB` (`session/config.py`).
- Mind package `src/aidnd/mind` stays PURE — reads `ctx` only.
- Full suite green before deploy: `uv run pytest /Users/nik/Desktop/dnd-ai/tests` (ABSOLUTE path).
- Deploy the green increment via `/deploy` (commit — NO `Co-Authored-By: Claude` trailer — push origin main, VPS git-reset + restart `aidnd`, verify `active`).

> **✔ shipped to prod.** Playtest: player speech draws emergent multi-NPC replies (keeper introduced herself + offered a drink); not a mob. Final review: SHIP. 278 green. pc_said_impulse tuned to 2.8.

Spec: [docs/superpowers/specs/2026-07-10-player-speech-heard-design.md](../specs/2026-07-10-player-speech-heard-design.md).

---

### Task 1: reactive pieces — impulse helper + PB + prompt line

**Files:**
- Modify: `src/aidnd/server/play/engine/world.py` (add `_pc_said_impulse` helper near `_work_lift`)
- Modify: `src/aidnd/server/play/engine/session/config.py` (PB key)
- Modify: `src/aidnd/mind/llm_agent.py` (`build_prompt` render, after the «ТВОИ ТЕМЫ» block from Workstream B)
- Test: `tests/play/test_pc_said.py` (create), `tests/mind/test_pc_said_line.py` (create)

**Interfaces:**
- Produces: `_pc_said_impulse(tier: str) -> float` — `PB["pc_said_impulse"] × {L1:1.0, L2:0.65, L3:0.4}`, else 0.0.
- Produces: `ctx["pc_said"]: dict[pid, str]` consumed by `build_prompt` (built in Task 2).

- [ ] **Step 1: Write the failing tests**

```python
# tests/play/test_pc_said.py
from aidnd.server.play.engine.world import _pc_said_impulse
from aidnd.server.play.engine.session.config import PB


def test_impulse_scales_by_tier():
    l1, l2, l3 = _pc_said_impulse("L1"), _pc_said_impulse("L2"), _pc_said_impulse("L3")
    assert l1 > l2 > l3 > 0
    assert l1 == PB["pc_said_impulse"]


def test_impulse_below_event_and_debt_but_above_must_gate():
    # a near hearer is selected to think (>= live_must_impulse) but can't outrank a real event/debt
    assert _pc_said_impulse("L1") >= PB["live_must_impulse"]
    assert _pc_said_impulse("L1") < 3.5   # 'событие'
    assert _pc_said_impulse("L1") < 4.0   # 'долг ответа'


def test_impulse_unknown_tier_zero():
    assert _pc_said_impulse("") == 0.0
```

```python
# tests/mind/test_pc_said_line.py
# build_prompt renders the «Чужак сказал» line only when ctx carries pc_said for this NPC.
# (Implementer: build the minimal (state, world, percept) fixture the SAME way tests/mind/test_topics_line.py does.)
from aidnd.mind.llm_agent import build_prompt


def _text(state, world, percept, ctx):
    return "\n".join(m["content"] for m in build_prompt(state, world, percept, ctx, prefs=[]))


def test_pc_said_line_rendered(minimal_state_world_percept):
    st, w, pc = minimal_state_world_percept
    t = _text(st, w, pc, {"pc_said": {st.config.id: "нет ли работы?"}})
    assert "нет ли работы?" in t and "Чужак" in t


def test_pc_said_line_absent(minimal_state_world_percept):
    st, w, pc = minimal_state_world_percept
    assert "Чужак" not in _text(st, w, pc, {"pc_said": {}})
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/play/test_pc_said.py /Users/nik/Desktop/dnd-ai/tests/mind/test_pc_said_line.py -v`
Expected: FAIL — `_pc_said_impulse` / PB key / prompt line not defined.

- [ ] **Step 3: PB key**

In `session/config.py`, near `live_must_impulse`:

```python
    "pc_said_impulse": 2.2,   # near hearer's pull to react when the player speaks aloud (L1; tier-scaled)
```

- [ ] **Step 4: impulse helper (world.py, near `_work_lift`)**

```python
_PC_SAID_TIER = {"L1": 1.0, "L2": 0.65, "L3": 0.4}


def _pc_said_impulse(tier: str) -> float:
    """Tier-scaled pull to react to the player's spoken line — near louder than far, and never
    above a real event/debt (so a busy NPC keeps to its business). 0.0 if unheard/unknown tier."""
    return round(PB["pc_said_impulse"] * _PC_SAID_TIER.get(tier, 0.0), 2)
```

- [ ] **Step 5: prompt line (llm_agent.py `build_prompt`)**

After the «ТВОИ ТЕМЫ» block (find `my_topics` from Workstream B):

```python
    said = (ctx.get("pc_said") or {}).get(cfg.id)
    if said:
        lines.append(f"  ⚑ Чужак рядом только что сказал вслух: «{said}» — ответь, если тебе есть "
                     "что сказать, или занимайся своим.")
```

- [ ] **Step 6: run tests to pass, then full suite**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/play/test_pc_said.py /Users/nik/Desktop/dnd-ai/tests/mind/test_pc_said_line.py -v` → PASS
Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests -q` → PASS

- [ ] **Step 7: Commit**

```bash
git add src/aidnd/server/play/engine/world.py src/aidnd/server/play/engine/session/config.py src/aidnd/mind/llm_agent.py tests/play/test_pc_said.py tests/mind/test_pc_said_line.py
git commit -m "feat(play): reactive pieces for player speech — pc_said impulse + prompt line [pc-heard]"
```

---

### Task 2: wire it — emit the utterance + hear it in the tick

**Files:**
- Modify: `src/aidnd/server/play/handlers/freeform.py` (`_attempt` fallback — emit `lv["pc_said"]`)
- Modify: `src/aidnd/server/play/engine/world.py` (`_live_tick` — hear + impulse + ctx; and a testable `_pc_heard` helper)
- Test: `tests/play/test_pc_heard.py` (create)

**Interfaces:**
- Consumes: `_pc_said_impulse` (Task 1), `audibility` (`engine/sound`), `PB["sound_voice"]`.
- Produces: `_pc_heard(pz, order, place_of, zn_by_place, zones_l) -> dict[pid, tier]` — which present NPCs hear the player and at what tier. `pz` = player's zone dict (or None); `place_of(pid)` → the NPC's place; zoneless venue (`not zones_l`) → every present NPC hears at `"L1"` (one conversational space).

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_pc_heard.py
from aidnd.server.play.engine.world import _pc_heard


def test_zoneless_everyone_hears_L1():
    heard = _pc_heard(None, ["a", "b"], lambda p: "room", {}, [])
    assert heard == {"a": "L1", "b": "L1"}


def test_zoned_near_hears_far_does_not():
    # two zones with centroids; player at z1, 'near' at z1, 'far' at a distant z2
    z1 = {"id": "z1", "name": "z1", "cx": 0, "cy": 0}
    z2 = {"id": "z2", "name": "z2", "cx": 40, "cy": 40}   # far enough to be inaudible
    zn = {"z1": z1, "z2": z2}
    place = {"near": "z1", "far": "z2"}
    heard = _pc_heard(z1, ["near", "far"], lambda p: place[p], zn, [z1, z2])
    assert heard.get("near") == "L1"
    assert "far" not in heard   # too far → inaudible → not a hearer
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/play/test_pc_heard.py -v`
Expected: FAIL — `_pc_heard` not defined. (If the exact far-distance in `test_zoned_near_hears_far_does_not` is audible under the real `PB` thresholds, widen z2's centroid until `far` is inaudible — the assertion is "near hears, distant does not," not a specific coordinate.)

- [ ] **Step 3: emit the utterance (freeform.py `_attempt` fallback)**

In the DM-narrator fallback (the `if text:` block, ~freeform.py:371), record it on the live scene so the tick can react (find `_S` — already imported):

```python
    _lv = _S.get("live")
    if _lv is not None and text:
        _lv["pc_said"] = text
        _lv["pc_spoke"] = True
```

Place this INSIDE `if text:`, before or after the narrator call — it must run so the subsequent `_world_tick()` (called by `act()` after `_run_plan`) sees `lv["pc_said"]`.

- [ ] **Step 4: `_pc_heard` helper + wiring in `_live_tick` (world.py)**

Add the helper (near `_pc_said_impulse`):

```python
def _pc_heard(pz, order, place_of, zn_by_place, zones_l) -> dict:
    """Present NPCs who hear the player's spoken line, tier by audibility. Zoneless venue → all L1."""
    heard = {}
    for pid in order:
        if not zones_l:
            heard[pid] = "L1"
            continue
        nz = zn_by_place.get(place_of(pid), {"id": place_of(pid)})
        t = audibility(pz, nz, PB["sound_voice"]) if pz else None
        if t:
            heard[pid] = t[1] if isinstance(t, tuple) else t   # audibility returns e.g. ('…','L1') or 'L1'
    return heard
```

(Check what `audibility` returns in this codebase — `_player_in_scene` compares `tier == "L1"`, so it returns the string tier; use it directly and drop the tuple branch if so.)

In `_live_tick`, right where `salient = lv.pop("salient", …)` is consumed (just before the `for pid in order:` impulse loop, ~world.py:728), consume `pc_said` and compute hearers:

```python
    pc_said = lv.pop("pc_said", None)
    pc_heard = {}
    if pc_said and PLAYER in w.bodies:
        zn_by_place = {z["name"]: z for z in zones_l} if zones_l else {}
        pz = (zn_by_place.get(w.bodies[PLAYER].place) or (room_center(zones_l) if zones_l else None))
        pc_heard = _pc_heard(pz, order, lambda p: w.bodies[p].place, zn_by_place, zones_l)
```

Inside the impulse loop, AFTER the existing `if salient / elif … else` chain sets `(imp, why)`, add (raise-only, so a real event/debt/emotion still wins):

```python
        ph = _pc_said_impulse(pc_heard.get(pid, ""))
        if ph > imp:
            imp, why = ph, "услышал чужака"
```

After the loop, expose the utterance to hearers' prompts — in the `ctx = {…}` dict add:

```python
        "pc_said": {pid: pc_said for pid in pc_heard} if pc_said else {},
```

- [ ] **Step 5: run tests + full suite**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/play/test_pc_heard.py -v` → PASS
Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests -q` → PASS

- [ ] **Step 6: Commit**

```bash
git add src/aidnd/server/play/handlers/freeform.py src/aidnd/server/play/engine/world.py tests/play/test_pc_heard.py
git commit -m "feat(play/live): the room hears the player — spoken line becomes a heard scene event NPCs may react to [pc-heard]"
```

---

### Task 3: playtest + tune + deploy (manual, gated)

- [ ] **Step 1: Boot a real-LLM dev server** — `AIDND_OPEN_PLAY=1 AIDND_PROFILE=deepseek .venv/bin/python -m uvicorn aidnd.server.app:app --host 127.0.0.1 --port 8100`
- [ ] **Step 2: Drive a populated building; the player speaks to the room** ("что за слухи?", "нет ли работы?"). Assert: ≥1 nearby NPC now *engages* (answers or a pointed brush-off), and it stays emergent — not every hearer replies; busy/hostile ones keep to their business.
- [ ] **Step 3: Tune** — if nobody engages, raise `PB["pc_said_impulse"]` (2.2 → 2.8); if the whole room drops everything to answer (a mob), lower it. Commit any tuning.
- [ ] **Step 4: Deploy** via the `/deploy` flow (pytest green → commit → push → VPS restart → `active`).

## Self-review notes
- Spec coverage: C1 emit (Task 2 Step 3), C2 hear+impulse (Task 2 Step 4), C3 prompt line (Task 1 Step 5). Playtest per spec (Task 3).
- Raise-only impulse keeps it emergent (never demotes a real reason; never forces a reply).
- Types: `_pc_said_impulse(str)->float`; `_pc_heard(...)->dict[pid,tier]`; `ctx["pc_said"]: dict[pid,str]`.
