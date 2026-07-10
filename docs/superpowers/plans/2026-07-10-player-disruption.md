# The Room Flinches at a Disruption (Workstream C, inc 2) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** A disruptive player act (shout / throw / break / brandish / threaten) makes the room react via the existing `salient` channel; the DM narrates only the player's action, not a phantom non-reaction.

**Architecture:** In the freeform fallback (where inc 1 sets `pc_said`), a keyword classifier flags a disruption and sets `lv["salient"]` — the existing "whole room notices, reacts in character" event. The `attack` path sets it too. `_DM_SYS` (freeform-fallback-only) gains a directive to narrate just the player's act.

**Tech Stack:** Python 3.14, pytest.

## Global Constraints

- No mechanical gates — `salient` only *raises* the room's pull to react (existing behavior); each NPC's reaction is its own utility choice ("не моё дело" is valid).
- No hardcoded gameplay numbers in code (this increment adds none — it reuses the existing salient impulse).
- Full suite green before deploy: `uv run pytest /Users/nik/Desktop/dnd-ai/tests` (ABSOLUTE path).
- Deploy via `/deploy` (commit — NO `Co-Authored-By: Claude` trailer — push origin main, VPS git-reset + restart `aidnd`, verify `active`).

Spec: [docs/superpowers/specs/2026-07-10-player-disruption-design.md](../specs/2026-07-10-player-disruption-design.md).

Current code (verified):
- Freeform fallback `freeform.py:370-387`: sets `pc_said` (inc 1) then calls the narrator with `_DM_SYS` + snapshot + `«{text}»`.
- Attack path `freeform.py:348-368`: opens combat, returns.
- `_DM_SYS` at `narrator/voice.py:182`, imported and used ONLY at `freeform.py:380` (verified — not shared with NPC dialogue).

---

### Task 1: disruptive act → salient + DM narrates only the player's action

**Files:**
- Modify: `src/aidnd/server/play/handlers/freeform.py` (add `_DISRUPTIVE_RE`; set `lv["salient"]` in the fallback + the attack path)
- Modify: `src/aidnd/server/play/engine/narrator/voice.py` (`_DM_SYS` directive)
- Test: `tests/play/test_disruption.py` (create)

**Interfaces:**
- Produces: `_DISRUPTIVE_RE` (compiled, IGNORECASE) — matches clear disruptions (shout/throw/break/brandish/threaten), not ordinary speech.

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_disruption.py
from aidnd.server.play.handlers.freeform import _DISRUPTIVE_RE

DISRUPTIVE = [
    "выхватываю меч и рычу на весь зал",
    "громко спрашиваю: кто здесь главный?",
    "швыряю кружку об стену",
    "ору: тихо все!",
    "хватаюсь за нож",
    "бью кулаком по столу",
    "угрожаю всем в зале",
    "достаю клинок из-за пояса",
]
BENIGN = [
    "спрашиваю про слухи",
    "спрашиваю, где купить меч",
    "как дела, хозяин?",
    "сажусь за стол и осматриваюсь",
    "заказываю эль",
    "подхожу к стойке",
]


def test_disruptive_lines_match():
    for t in DISRUPTIVE:
        assert _DISRUPTIVE_RE.search(t), f"should be disruptive: {t!r}"


def test_benign_lines_do_not_match():
    for t in BENIGN:
        assert not _DISRUPTIVE_RE.search(t), f"should NOT be disruptive: {t!r}"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/play/test_disruption.py -v`
Expected: FAIL — `_DISRUPTIVE_RE` not defined (ImportError).

- [ ] **Step 3: add `_DISRUPTIVE_RE` (freeform.py, module level near the other regexes / imports)**

```python
import re

_DISRUPTIVE_RE = re.compile(
    r"кричу|ору\b|заор|во весь голос|громко (говорю|спрашива|зов|крич)|рычу|выхватыва|обнажа"
    r"|хвата\w* за (нож|меч|оруж|клинок|груд)|достаю (нож|меч|клинок|оруж)|швыр"
    r"|броса\w* (кружк|в стену|об пол|об стол)|опрокид|бью кулак|стуч\w* по стол|разбива"
    r"|угрожа|за грудки",
    re.IGNORECASE,
)
```

- [ ] **Step 4: set `lv["salient"]` on a disruptive utterance (freeform fallback)**

In `_attempt`, in the fallback `if text:` block, right after the existing `pc_said`/`pc_spoke` assignment:

```python
        if _lv is not None and _DISRUPTIVE_RE.search(text):
            _lv["salient"] = f"чужак: {text[:70]}"   # whole room notices — reacts in character
```

- [ ] **Step 5: set `lv["salient"]` on the player attack (freeform.py attack path)**

In the `if verb == "attack" and npc:` block, before `out["combat"] = True`:

```python
        _lv = _S.get("live")
        if _lv is not None:
            _lv["salient"] = f"чужак выхватил оружие на {p.name}!"
```

- [ ] **Step 6: DM narrates only the player's action (`_DM_SYS`)**

In `src/aidnd/server/play/engine/narrator/voice.py`, append to the `_DM_SYS` string (the freeform-fallback system prompt — verified not shared with NPC dialogue):

```python
    " Опиши ТОЛЬКО само действие игрока, коротко (одна-две фразы). НЕ описывай, как реагируют "
    "окружающие — их ответ придёт следующим ходом."
```

(Concatenate into the existing `_DM_SYS = (...)` literal; keep the rest verbatim.)

- [ ] **Step 7: run tests + full suite**

Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests/play/test_disruption.py -v` → PASS
Run: `uv run pytest /Users/nik/Desktop/dnd-ai/tests -q` → PASS

- [ ] **Step 8: Commit**

```bash
git add src/aidnd/server/play/handlers/freeform.py src/aidnd/server/play/engine/narrator/voice.py tests/play/test_disruption.py
git commit -m "feat(play): the room flinches at a player disruption — shout/throw/brandish set salient; DM narrates only the act [disruption]"
```

---

### Task 2: playtest + tune + deploy (manual, gated)

- [ ] **Step 1: Boot a real-LLM dev server** — `AIDND_OPEN_PLAY=1 AIDND_PROFILE=deepseek .venv/bin/python -m uvicorn aidnd.server.app:app --host 127.0.0.1 --port 8100`
- [ ] **Step 2: In a populated room, the player disrupts** — shout ("громко ору: тихо все!"), draw ("выхватываю нож"), throw ("швыряю кружку об стену"). Assert: the room *reacts* this tick (glances, flinches, someone squares up or tells the player off), varied by character — not a uniform script; and the DM line narrates only the player's act (no "никто не оборачивается"). Contrast: an ordinary question still uses inc-1's emergent path (no room-wide flinch).
- [ ] **Step 3: Tune** — if the regex misses/false-triggers on real inputs, adjust the patterns; commit.
- [ ] **Step 4: Deploy** via `/deploy` (pytest green → commit → push → VPS restart → `active`).

## Self-review notes
- Spec coverage: D1 disruptive→salient (Task 1 Steps 3-5), D2 DM directive (Step 6). Playtest per spec (Task 2).
- `_DM_SYS` verified freeform-fallback-only (safe to amend). Salient reuses the existing 3.5 impulse (no new PB number).
- Types: `_DISRUPTIVE_RE` compiled regex.
