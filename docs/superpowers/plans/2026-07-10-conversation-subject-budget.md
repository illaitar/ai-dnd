# Conversation Talk-Budget (B4) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make a single conversation thread exhaust its subject after ~6 lines — nudge a change of subject and release the answer-debt pin — so lively threads turn over instead of dragging.

**Architecture:** Add a per-conversation `spent` counter to the pure `convo.py`; `conv_note_say` counts it, `conv_debt_to` releases the pin at budget, `conv_block` nudges near budget. Two module constants (matching the existing `QUIET_DIE` pattern).

**Tech Stack:** Python 3.14, pytest, `uv run pytest`.

## Global Constraints

- No mechanical gates on who may speak — this models "a thread runs dry," never caps speech.
- `convo.py` is a PURE module (no server/DB/LLM imports); its tuning lives in module constants (existing precedent: `QUIET_DIE`, `LOG_KEEP`, `DEBT_STALE`) — NOT the `PB` table. `CONVO_BUDGET`/`CONVO_NUDGE` join them.
- Full suite green before deploy: `uv run pytest /Users/nik/Desktop/dnd-ai/tests` (ABSOLUTE path; shell CWD may not be repo root).
- Deploy the green increment via `/deploy` (commit — NO `Co-Authored-By: Claude` trailer — push origin main, VPS git-reset + restart `aidnd`, verify `active`).

---

### Task 1: Talk-budget in `convo.py`

**Files:**
- Modify: `src/aidnd/server/play/engine/convo.py`
- Test: `tests/play/test_convo_budget.py` (create)

**Interfaces:**
- Produces: module constants `CONVO_BUDGET = 6`, `CONVO_NUDGE = 2`.
- Produces: conversation dicts now carry `"spent": int` (lines said so far). `conv_debt_to` returns `None` once `spent >= CONVO_BUDGET`. `conv_block` appends an «иссякает» nudge line once `spent >= CONVO_BUDGET - CONVO_NUDGE`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/play/test_convo_budget.py
from aidnd.server.play.engine import convo
from aidnd.server.play.engine.convo import (
    CONVO_BUDGET, CONVO_NUDGE, conv_block, conv_debt_to, conv_note_say, conv_of,
)


def test_spent_counts_lines():
    lv = {}
    c = conv_note_say(lv, "a", "b", "привет", "z")
    assert c["spent"] == 1
    conv_note_say(lv, "b", "a", "здорово", "z")
    assert conv_of(lv, "a")["spent"] == 2


def test_debt_present_before_budget():
    lv = {}
    conv_note_say(lv, "a", "b", "видал крысу?", "z")     # spent 1, debt → b
    assert conv_debt_to(lv, "b") is not None


def test_debt_released_at_budget():
    lv = {}
    for i in range(CONVO_BUDGET):                         # drive spent to the budget
        frm, to = ("a", "b") if i % 2 == 0 else ("b", "a")
        conv_note_say(lv, frm, to, f"строка {i}", "z")
    c = conv_of(lv, "a")
    assert c["spent"] >= CONVO_BUDGET
    assert conv_debt_to(lv, c["debt"]["to"]) is None      # exhausted → no forced reply


def test_nudge_appears_near_budget():
    lv = {}
    for i in range(CONVO_BUDGET - CONVO_NUDGE):
        frm, to = ("a", "b") if i % 2 == 0 else ("b", "a")
        conv_note_say(lv, frm, to, f"реплика {i}", "z")
    assert "иссякает" in conv_block(lv, "a", {"a": "А", "b": "Б"})


def test_no_nudge_early():
    lv = {}
    conv_note_say(lv, "a", "b", "привет", "z")            # spent 1, well below
    assert "иссякает" not in conv_block(lv, "a", {"a": "А", "b": "Б"})


def test_merge_carries_max_spent():
    lv = {}
    conv_note_say(lv, "a", "b", "x", "z")                 # convo AB: spent 1
    for _ in range(3):
        conv_note_say(lv, "c", "d", "y", "z")             # convo CD: spent 3
    conv_note_say(lv, "b", "c", "мостик", "z")            # b(AB) → c(CD): merge
    c = conv_of(lv, "a")
    assert "c" in c["members"]
    assert c["spent"] >= 3                                # max(1,3)+bridge, NOT reset to 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/play/test_convo_budget.py -v`
Expected: FAIL — `CONVO_BUDGET` import error / `spent` KeyError / no nudge.

- [ ] **Step 3: Add constants**

In `src/aidnd/server/play/engine/convo.py`, after `DEBT_STALE = 3` (line 21):

```python
CONVO_BUDGET = 6       # lines before a thread's subject is 'spent' — it then winds down / turns over
CONVO_NUDGE = 2        # nudge a change of subject this many lines before the budget
```

- [ ] **Step 4: Track `spent` in `conv_note_say` (create + merge + per-line)**

In `conv_note_say`: (a) the merge branch (lines 37-41) — after `_convs(lv).remove(cb)`, carry the larger spend:

```python
        ca["spent"] = max(ca.get("spent", 0), cb.get("spent", 0))
```

(b) the new-conversation dict (lines 45-46) — add `"spent": 0`:

```python
        c = {"id": f"c{len(_convs(lv)) + 1}|{lv.get('clock', 0)}", "zone": zone,
             "members": [frm, to], "log": [], "debt": None, "quiet": 0, "spent": 0}
```

(c) after `c["quiet"] = 0` (line 53) — count this line:

```python
        c["spent"] = c.get("spent", 0) + 1
```

- [ ] **Step 5: Release the debt pin at budget in `conv_debt_to`**

Change the guard (lines 63-64) to also require the thread isn't spent:

```python
    if (c and c.get("debt") and c["debt"]["to"] == pid and c["debt"]["ticks"] <= DEBT_STALE
            and c.get("spent", 0) < CONVO_BUDGET):
        return c["debt"]
    return None
```

- [ ] **Step 6: Nudge in `conv_block`**

In `conv_block`, before `return "\n".join(lines)` (after the debt block, ~line 99):

```python
    if c.get("spent", 0) >= CONVO_BUDGET - CONVO_NUDGE:
        lines.append("  ⚑ разговор об этом иссякает — смени тему, пошути или отойди "
                     "(не тяни то же самое).")
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/play/test_convo_budget.py -v`
Expected: PASS (6 tests).

- [ ] **Step 8: Regression + full suite green**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/play/test_convo.py -q` (existing convo tests) then `uv run pytest /Users/nik/Desktop/dnd-ai/tests -q`
Expected: PASS (all).

- [ ] **Step 9: Commit**

```bash
git add src/aidnd/server/play/engine/convo.py tests/play/test_convo_budget.py
git commit -m "feat(play/convo): talk-budget — a thread's subject exhausts, nudging a change and releasing the answer-debt pin [convo-budget]"
```

---

### Task 2: Playtest + tune + deploy (manual, gated)

**Files:** none.

- [ ] **Step 1: Boot a real-LLM dev server**

Run (background): `AIDND_OPEN_PLAY=1 AIDND_PROFILE=deepseek .venv/bin/python -m uvicorn aidnd.server.app:app --host 127.0.0.1 --port 8100`

- [ ] **Step 2: Drive a tavern and observe thread turnover**

Enter a tavern → `/api/play/live` ×7, capture the digest/feed.
Expected: a single subject no longer drags ~5 ticks — a thread carries a few exchanges, then winds down or pivots (the «иссякает» nudge takes effect); the room still feels coherent, not clipped mid-sentence.

- [ ] **Step 3: Tune if needed**

If threads clip mid-story, raise `CONVO_BUDGET` (6 → 8). If a subject still lingers, lower it (6 → 4). Commit any tuning change.

- [ ] **Step 4: Deploy**

Run the `/deploy` flow (pytest green → commit → push origin main → VPS git-reset + restart `aidnd` → verify `active`).

## Self-review notes
- Spec coverage: spend counter (Step 4), debt-release (Step 5), nudge (Step 6), merge handling (Step 4a). Playtest per spec Testing (Task 2).
- `CONVO_BUDGET=6`/`CONVO_NUDGE=2` are real starting values (module constants, tuned in Task 2).
- Type consistency: `spent: int` on every conversation dict; `conv_debt_to -> dict | None`; `conv_block -> str | None`.
