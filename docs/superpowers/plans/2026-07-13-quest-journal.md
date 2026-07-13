# Quest Journal «Хроника → дела» — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the player journal from an ambient chronicle (overheard lines, met-people, visited-places + scattered quest one-liners) into a **collection of дел** — one first-person, past-tense history thread per quest, written by the narrator LLM from **code-supplied facts** on real quest events only. `GET /api/play/journal` returns quests grouped `[{cid, title, giver, status, thread:[{gt, beat, text}]}]`; the «Хроника» tab reads «Ко мне обратилась Роза Медовар… → Я согласился… → Я обыскал помещение и понял, что она хотела меня обобрать → Так и завершилось это дело.» Every non-quest write is removed.

**Architecture:** One reshaped writer, one narrator call per event, one grouping endpoint, one two-level UI. `engine/journal.py` gets a new **`j_beat(cid, beat, facts)`** — it renders an RU facts block, makes **one** `core._model().call("narrator", …, temperature=0.4)` (the same manager seam `voice.py:166` uses), and appends a `kind='quest'`, `prov=<beat>`, `refs=[cid]` row via the existing `journal_add` (schema UNCHANGED — the beat rides the `prov` column). It is **best-effort**: `LLMUnavailable`/empty → no row, never raises (the quest transaction already committed). The five existing `j_quest` sites are rewired to named beats + one **new** `step` site (`contracts.py:305`); the five ambient helpers (`journal_feed`/`j_event`/`j_person`/`j_person_once`/`j_place`) and their call sites are **deleted**; a one-shot migration purges legacy non-quest rows. `misc.py` `journal_endpoint` groups quest rows by `refs[0]=cid`, orders each thread `gt`-ascending, enriches title/giver/status from `_store().contracts(...)`. `play.html` `renderJournal` becomes a two-level дела view (list → expandable thread). Ships as one increment.

**Tech Stack:** Python 3, FastAPI handlers, the shared `ModelManager` (`core._model()` → `mgr.call("narrator", …)`), `WorldStore` (sqlite, `journal`/`contracts` tables), `aidnd.inference.client.LLMUnavailable`, the `play.html` template (vanilla JS), pytest via `uv run pytest`.

## Global Constraints

- **No LLM fallback.** Journaling is **best-effort**: quest mechanics NEVER wait on it. `j_beat` runs *after* `save_contract` commits; on `LLMUnavailable` / empty / garbled output it **returns without writing a row and never raises** — **no canned line, no stub** (the no-LLM-fallback rule forbids a fabricated sentence just as it forbids a fake direction). A skipped beat is simply an absent thread line.
- **Code owns facts; the LLM only words the line.** Every fact string in the facts block comes from the contract / giver — the narrator decides no *what*, only phrasing («только по фактам, ничего не домысливай»). Interpretive beats (`twist`/`reveal`) feed only mechanics-confirmed `framer.reveal`.
- **Russian commits** in the form `feat(play/quests): …` or `fix(play/quests): …`. **NEVER** add a `Co-Authored-By: Claude` trailer.
- **Test-fixture discipline (hard-learned):** snapshot/restore the session dict with `saved = dict(core._S._d()); d = core._S._d(); … d.clear(); d.update(saved)` in a `try/finally`; **AND** root-patch `session.persist._STORE` with `monkeypatch.setattr(persist, "_STORE", store)` (journal/store resolve `_store()` lazily). `ruff` strips momentarily-unused imports — keep the lazy-import-inside-function pattern used across the play engine.
- **Tunables in PB only if truly tunable.** Reuse `PB["journal_cap"]=2000` as-is (now effectively a quest-thread-rows cap). Narrator temperature stays a **local `0.4` literal** in `j_beat` (matching the `voice.py:166` idiom) — **no new PB key**. No thread-length or beat-count caps (beats are code events, bounded by the quest's own step count).
- **Frontend = the `play.html` template.** Match its existing style idioms (`.jrow`/`.jgrp`/`.jmark`/`.jempty`/`.job`/`.jdone` classes, `api()`, `esc()`, `setView`) — no framework, no build step.

---

## Settled decisions (spec §10 open questions — CLOSED)

- **Offer beat granularity** → **one** narrator call / one row for the offer beat (intro + ask folded).
- **Narrator temperature** → stays a **local `0.4` literal**; not promoted to PB.
- **Legacy un-typed quest rows** (old `prov` `told`/`saw`) → keep rendering in threads gracefully (UI shows unknown beats as plain lines); they are NOT purged.
- **`twist` vs `reveal` beat** → the twist site (`twist.py:41`) emits a single **`twist`** beat. No deterministic deception/void marker exists on the twist seed (only `reveal_on`/`fact`/`adds`, verified `seeds.py:95,109`), so text-sniffing for a `reveal` label would be a guess — forbidden by "code owns facts". Both `twist` and `reveal` are in the closed set and render identically; `reveal` stays reserved for a future site that can mark exposure deterministically. (Drift note in Self-review.)

---

## Drift found vs. the spec's file:line snapshot (re-verified against HEAD)

The spec was written a few commits ago; the **npc-geo-knowledge** increment has since shipped. Re-verification against HEAD:

| Spec anchor | HEAD | Status |
|---|---|---|
| `dialogue.py:270` offer `j_quest("told", pitch, cid)` | **`dialogue.py:270`** (import at `:268`, inside the `_WORK_INTEREST_RE` branch) | ✅ exact |
| `world.py:206` accept `j_quest("told", summary, cid)` | **`world.py:206`** (`_accept_contract`; top import `j_quest, journal_feed` at `:45`) | ✅ exact |
| `contracts.py:305` `_ct_advance` (NEW step site) | **`contracts.py:305`**; `save_contract` at `:313`, returns hint at `:314`; `_step_desc` at `:299` | ✅ exact |
| `contracts.py:342` complete `j_quest("saw", …)` | **`contracts.py:342`** (`_contract_complete`, import at `:334`, `summary` built `:336-341`) | ✅ exact |
| `twist.py:41` twist `_j_quest("told", reveal, cid)` | **`twist.py:41`** (guarded helper `_j_quest` at `:10`) | ✅ exact |
| `pipeline.py:374` overtaken | **`pipeline.py:374`** `_j_quest_overtaken(line, cid)` (helper at `:316`) | ✅ exact |
| `world.py:1300` `journal_feed(feed)` | **`world.py:1300`** | ✅ exact |
| `dialogue.py:120` `j_person_once(...)` | **`dialogue.py:120`** (import at `:50`) | ✅ exact |
| `hero.py:184` `j_place` in `_mark_seen` | **`hero.py:184`**; geo already added `prov`/`text` kwargs (`_mark_seen(bid, *, prov="saw", text=None)` at `:177`), seen-flag at `:180-182`, `j_place` import at `:19` | ⚠️ geo shipped — `j_place` already has a `prov` param; we DELETE the call at `:184` and keep `:180-182` |
| `freeform.py:376` `j_event("gave", …)` | **`freeform.py:376`** (import at `:374`) | ✅ exact |
| `inventory.py:133` `j_event("saw", …)` | **`inventory.py:133`** (import at `:40`) | ✅ exact |
| `misc.py:152` `journal_endpoint` | **`misc.py:152`** (`kind` filter, `limit` cap 500) | ✅ exact |
| `play.html:478-481` jtabs, `:1283` `renderJournal`, `:1281` `JMARK`, `:1280` `let JTAB` | **all exact** | ✅ exact |
| `store.py:248` `journal_add`, `:259` `journal_list`, cap-prune `:255-257` | **exact**; `contracts(wid, status=None)` at `:392`, `flag_get/set` at `:373/:382` | ✅ exact |
| `config.py:231` `PB["journal_cap"]=2000` | **`config.py:231`** | ✅ exact |

**Test drift (the important one):** the geo increment landed test files that exercise the exact helpers this spec deletes. `LLMUnavailable` lives at `aidnd.inference.client` (`pipeline.py:13`). Baseline: **`uv run pytest tests -q --co` → 575 tests**. These files reference removed helpers and are handled inside the tasks below:

- `tests/play/test_journal_feed.py` — `journal_feed` (DELETE in Task 3)
- `tests/play/test_journal_hooks.py` — person/place/event hooks (DELETE in Task 3)
- `tests/play/test_journal_helper.py` — `j_event`/`j_person`/`j_place`/`j_quest` wrappers (DELETE in Task 3)
- `tests/play/test_geo_journal_prov.py` — `j_place(prov=…)` (DELETE in Task 3 — `j_place` is gone; the geo map-mark survives, its journal row does not, per spec §6)
- `tests/play/test_geo_say_share.py` — asserts a `place/told` journal row at `:93` (UPDATE in Task 3 — drop the journal-row assertions, keep the `seen|` map-mark assertions)
- `tests/play/test_journal_quests.py` — asserts old `told`/`saw` beats (REWRITE in Task 2)
- `tests/play/test_quest_overtaken.py:97` — asserts `prov=="saw"` (UPDATE in Task 2 → `"overtaken"`)
- `tests/play/test_journal_api.py` — flat `kind` filter (REWRITE in Task 4 → grouping)
- `tests/play/test_journal_store.py`, `tests/play/test_newworld_journal.py` — raw-store tests, UNTOUCHED (they exercise `journal_add`/`journal_list`/`destroy_world` directly, which are unchanged).

---

## File structure

- **Modify `src/aidnd/server/play/engine/journal.py`** — add `j_beat(cid, beat, facts)` + `_facts_ru` + `purge_legacy_once`; delete `j_event`/`j_person`/`j_person_once`/`j_place`/`journal_feed`/`_emit`.
- **Modify `src/aidnd/server/play/engine/world.py`** — accept beat (`:206`), drop `journal_feed` call (`:1300`) + top import (`:45`).
- **Modify `src/aidnd/server/play/mechanics/contracts.py`** — step beat (`:305` `_ct_advance`), done beat (`:342` `_contract_complete`).
- **Modify `src/aidnd/server/play/handlers/dialogue.py`** — offer beat (`:270`), drop `j_person_once` (`:120`) + import (`:50`).
- **Modify `src/aidnd/server/play/engine/quests/twist.py`** — `_j_quest` → `_j_beat`, twist beat (`:41`).
- **Modify `src/aidnd/server/play/engine/quests/pipeline.py`** — `_j_quest_overtaken` → `_j_beat_overtaken`, overtaken beat (`:374`).
- **Modify `src/aidnd/server/play/engine/pc/hero.py`** — drop `j_place` call (`:184`) + import (`:19`); keep seen-flag (`:180-182`) and the (now-inert) `prov`/`text` kwargs for the geo call-site compat.
- **Modify `src/aidnd/server/play/handlers/freeform.py`** — drop `j_event` (`:374-376`).
- **Modify `src/aidnd/server/play/handlers/inventory.py`** — drop `j_event` (`:133`) + import (`:40`).
- **Modify `src/aidnd/worldgen/store.py`** — add `journal_purge_nonquest(world_id)`.
- **Modify `src/aidnd/server/play/handlers/misc.py`** — reshape `journal_endpoint` (`:152`) to grouped дела.
- **Modify `src/aidnd/server/web/play.html`** — jtabs (`:478-481`) → single дела list; `renderJournal`/`JMARK`/`JTAB` (`:1280-1299`) → two-level view.
- **Tests:** add `tests/play/test_journal_beat.py`, `tests/play/test_journal_migration.py`, `tests/play/test_journal_dela_api.py`; rewrite `test_journal_quests.py`; update `test_quest_overtaken.py`, `test_geo_say_share.py`; delete `test_journal_feed.py`, `test_journal_hooks.py`, `test_journal_helper.py`, `test_geo_journal_prov.py`, `test_journal_api.py`.

### Seam quick-reference (verified `file:line` at HEAD)

- `narrator/voice.py:166` `mgr.call("narrator", msgs, options={"temperature":0.85})` — the manager seam `j_beat` reuses (at `0.4`). `_model()` from `core.py:206`.
- `worldgen/store.py:248` `journal_add(world_id, kind, prov, refs, text, gt)`; `:259` `journal_list(world_id, kind=None, limit=200) -> [{gt,kind,prov,refs,text}]` (newest-first, `refs` decoded); `:255-257` cap-prune shared across kinds; `:392` `contracts(world_id, status=None) -> [{id,status,**data}]`; `:373` `flag_get`; `:382` `flag_set`.
- `session/persist.py` `_store()`; `session/state.py` `_wid()`; `session/time.py` `_gt()` — the leaf resolvers `journal.py` already imports at top.
- `aidnd.inference.client.LLMUnavailable` — raised by `mgr.call(...)` with no model.
- contract dict fields (from `store.contracts`): `id`, `status`, `giver` (pid), `giver_name`, `kind`, `want`, `target_name`, `where`, `reward`, `pitch`, `framer.reveal`, `seed.twist`, `src`, `steps`, `step`.
- persona appearance: `(person.persona.get("look") or {}).get("clothing")` (verified — pool personas carry `look.clothing`, `world.py:291-293`).

---

# INCREMENT 1 — quest-only journal + threads

Ships the full user-locked design: `j_beat` writer, five rewired beats + the new `step` beat, ambient removal + migration purge, grouped дела API, two-level дела UI. Unit-green throughout; one live fraud-arc playtest gate; then deploy.

---

## Task 1: `j_beat` writer core (best-effort narrator beat)

**Files:**
- Modify: `src/aidnd/server/play/engine/journal.py`
- Test: `tests/play/test_journal_beat.py`

**Interfaces:**
- Consumes: `_wid`/`_store`/`_gt` (already imported), `core._model().call("narrator", …)`, `LLMUnavailable`.
- Produces: `j_beat(cid: str, beat: str, facts: dict) -> None` — renders an RU facts line, makes ONE narrator call at temp `0.4`, appends `journal_add(wid, "quest", beat, [cid], line, gt)`. `LLMUnavailable`/empty/any exception → returns, no row, never raises.

This task adds `j_beat` **alongside** the existing helpers (nothing removed yet) so the whole suite stays green.

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_journal_beat.py
"""j_beat: code-built facts → ONE narrator call → one kind='quest' prov=<beat> refs=[cid] row.
BEST-EFFORT: LLMUnavailable / empty output → NO row and NO exception (quest already committed)."""
import pytest

from aidnd.inference.client import LLMUnavailable
from aidnd.server.play.engine import core
from aidnd.server.play.engine.journal import j_beat
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


class _StubOK:
    def __init__(self, line="Я взялся за это дело."):
        self.line = line
        self.calls = []

    def call(self, role, messages, **kw):
        self.calls.append((role, messages, kw))
        return {"content": self.line}


class _StubDown:
    def call(self, role, messages, **kw):
        raise LLMUnavailable("no model")


class _StubEmpty:
    def call(self, role, messages, **kw):
        return {"content": "   "}


@pytest.fixture
def store(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    saved = dict(core._S._d()); d = core._S._d()
    try:
        d.clear(); d.update(wid=1, gt=21360)
        yield st
    finally:
        d.clear(); d.update(saved)


def _quest_rows(st):
    return [r for r in st.journal_list(1, kind="quest")]


def test_beat_writes_one_quest_row(store, monkeypatch):
    stub = _StubOK("Я взялся добыть для Розы мешочек с медяками.")
    monkeypatch.setattr(core, "_model", lambda: stub)
    j_beat("ct:sift:p_roza:20880", "accept",
           {"kind": "bring", "want": "мешочек с медяками", "where": "сундук (лавка Розы)",
            "reward": 8, "giver_name": "Роза Медовар"})
    rows = _quest_rows(store)
    assert len(rows) == 1
    assert rows[0]["kind"] == "quest"
    assert rows[0]["prov"] == "accept"                       # beat rides prov column
    assert rows[0]["refs"] == ["ct:sift:p_roza:20880"]
    assert rows[0]["gt"] == 21360
    assert rows[0]["text"] == "Я взялся добыть для Розы мешочек с медяками."


def test_facts_reach_the_narrator_prompt(store, monkeypatch):
    stub = _StubOK()
    monkeypatch.setattr(core, "_model", lambda: stub)
    j_beat("c1", "offer",
           {"giver_name": "Роза Медовар", "giver_role": "лавочник",
            "appearance": "в переднике, руки в муке", "pitch": "Сбегай к сундуку за медяками."})
    role, messages, kw = stub.calls[-1]
    assert role == "narrator"
    assert kw.get("options", {}).get("temperature") == 0.4    # local literal, low for faithful wording
    user = messages[-1]["content"]
    assert "Роза Медовар" in user and "в переднике" in user and "Сбегай к сундуку" in user


def test_llm_down_writes_no_row_and_does_not_raise(store, monkeypatch):
    monkeypatch.setattr(core, "_model", lambda: _StubDown())
    j_beat("c1", "accept", {"giver_name": "Роза Медовар"})    # must NOT raise
    assert _quest_rows(store) == []


def test_empty_output_writes_no_row(store, monkeypatch):
    monkeypatch.setattr(core, "_model", lambda: _StubEmpty())
    j_beat("c1", "done", {"giver_name": "Роза", "what": "мешочек", "kind": "bring"})
    assert _quest_rows(store) == []


def test_no_session_is_a_safe_noop(monkeypatch):
    # no wid/store bound → best-effort no-op, never raises
    saved = dict(core._S._d()); d = core._S._d()
    try:
        d.clear()
        j_beat("c1", "accept", {"giver_name": "X"})
    finally:
        d.clear(); d.update(saved)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_journal_beat.py -q`
Expected: FAIL — `ImportError: cannot import name 'j_beat' from '…journal'`.

- [ ] **Step 3: Add `j_beat` + `_facts_ru` to `journal.py`**

Add the `LLMUnavailable` import to the top of `src/aidnd/server/play/engine/journal.py` (leaf import, no cycle):

```python
from aidnd.inference.client import LLMUnavailable
```

Then append the writer (leave the existing helpers in place — Task 3 removes them):

```python
_BEATS = {"offer", "accept", "step", "twist", "reveal", "done", "overtaken", "failed"}

_J_SYS = (
    "Ты — герой этой истории, ведёшь дневник дел. Опиши событие ниже ОДНОЙ короткой "
    "фразой: от ПЕРВОГО лица, в ПРОШЕДШЕМ времени, по-русски, только по фактам — "
    "ничего не домысливай и не добавляй. Верни ТОЛЬКО фразу, без кавычек и пояснений."
)


def _facts_ru(beat: str, f: dict) -> str:
    """Render the code-built facts dict into one RU description for the narrator. Pure string
    assembly — no invention; every value comes from the caller (the contract/giver)."""
    if beat == "offer":
        role = f" ({f['giver_role']})" if f.get("giver_role") else ""
        app = f", {f['appearance']}" if f.get("appearance") else ""
        return (f"ко мне обратился(лась) {f.get('giver_name', 'кто-то')}{role}{app}; "
                f"его(её) просьба: {f.get('pitch', '')}")
    if beat == "accept":
        where = f", место: {f['where']}" if f.get("where") else ""
        what = f.get("want") or f.get("target_name") or "поручение"
        return (f"я согласился взяться за дело для {f.get('giver_name', 'заказчика')}: "
                f"{what}{where}; награда: {f.get('reward', '?')}")
    if beat == "step":
        return (f"я выполнил шаг ({f.get('step_narr', '')}); осталось: {f.get('next', '')} "
                f"— шаг {f.get('n', '?')} из {f.get('total', '?')}")
    if beat in ("twist", "reveal"):
        return f"вскрылось: {f.get('reveal', 'новый поворот в этом деле')}"
    if beat == "done":
        return (f"дело для {f.get('giver_name', 'заказчика')} завершено: {f.get('what', 'исполнено')} "
                f"(тип: {f.get('kind', '')})")
    if beat == "overtaken":
        return (f"дело уладилось без меня, я опоздал — {f.get('giver_name', 'заказчик')} сказал(а): "
                f"«{f.get('giver_line', 'поздно')}»")
    if beat == "failed":
        return f"дело для {f.get('giver_name', 'заказчика')} не удалось: {f.get('reason', '')}"
    return "; ".join(f"{k}: {v}" for k, v in (f or {}).items())


def j_beat(cid: str, beat: str, facts: dict) -> None:
    """One thread line for a quest event. beat ∈ {offer,accept,step,twist,reveal,done,overtaken,failed}.
    Builds an RU facts block, makes ONE narrator call (temp 0.4), appends kind='quest' prov=beat
    refs=[cid]. BEST-EFFORT: LLMUnavailable / empty / any error → returns without writing; NEVER
    raises to the caller (the quest transaction has already committed). No canned fallback line."""
    try:
        wid = _wid()
        store = _store()
    except Exception:  # noqa: BLE001 — no live session: journaling is best-effort, never fatal
        return None
    if wid is None or store is None:
        return None
    try:
        from aidnd.server.play.engine.core import _model  # deferred: avoid load-time cycle
        msgs = [{"role": "system", "content": _J_SYS},
                {"role": "user", "content": f"Событие ({beat}): {_facts_ru(beat, facts)}."}]
        resp = _model().call("narrator", msgs, options={"temperature": 0.4})
    except LLMUnavailable:
        return None                                          # no model → no row, no stub (no-LLM-fallback)
    except Exception:  # noqa: BLE001 — journaling never breaks a committed quest
        return None
    line = ((resp.get("content") if resp else "") or "").strip().strip('"').strip()
    if not line:
        return None                                          # empty/garbled → no row
    store.journal_add(wid, "quest", beat, [cid], line, _gt())
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/play/test_journal_beat.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Full-suite sanity (nothing removed yet)**

Run: `uv run pytest tests -q`
Expected: PASS — 575 baseline + 5 new = 580, zero regressions (the existing helpers are untouched).

- [ ] **Step 6: Commit**

```bash
git add src/aidnd/server/play/engine/journal.py tests/play/test_journal_beat.py
git commit -m "feat(play/quests): j_beat — реплика дела от первого лица (один нарратор-вызов, best-effort)"
```

---

## Task 2: Rewire the five quest sites to `j_beat` + add the new `step` beat

**Files:**
- Modify: `src/aidnd/server/play/handlers/dialogue.py:266-270` (offer)
- Modify: `src/aidnd/server/play/engine/world.py:206` + `:45` (accept)
- Modify: `src/aidnd/server/play/mechanics/contracts.py:305-314` (step, NEW) + `:334-342` (done)
- Modify: `src/aidnd/server/play/engine/quests/twist.py:10-18,41` (twist)
- Modify: `src/aidnd/server/play/engine/quests/pipeline.py:316-326,374` (overtaken)
- Rewrite: `tests/play/test_journal_quests.py`
- Modify: `tests/play/test_quest_overtaken.py:80-97`

**Interfaces:** each old `j_quest(prov, text, cid)` call is replaced by `j_beat(cid, beat, facts)` with the exact facts block from spec §5 (`kind='quest'`, `refs=[cid]` unchanged); `_ct_advance` gains a `step` beat between `save_contract` and its return.

- [ ] **Step 1: Rewrite the quest-beat test first (it will fail against the old `j_quest` sites)**

Replace the whole of `tests/play/test_journal_quests.py` with:

```python
# tests/play/test_journal_quests.py
"""Quest beats land in the chronicle via j_beat: accept → prov='accept', complete → prov='done',
each refs=[cid]. The narrator is stubbed (code owns the FACTS, the stub owns the wording)."""
import asyncio
from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


class _Voice:
    """Echoes the beat name back as the line, so tests can key off it without a live LLM."""
    def call(self, role, messages, **kw):
        user = messages[-1]["content"]
        beat = user.split("(", 1)[1].split(")", 1)[0] if "(" in user else "?"
        return {"content": f"[{beat}] {user[:40]}"}


def _npc(pid, name, role):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    return SimpleNamespace(id=pid, name=name, role=role, persona={}, state=st, keys=[])


@pytest.fixture
def wired(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    monkeypatch.setattr(core, "_model", lambda: _Voice())
    people = {"p_odo": _npc("p_odo", "Одо", "трактирщик")}
    saved = dict(core._S._d()); d = core._S._d()
    try:
        d.clear(); d.update(wid=1, gt=600, people=people)
        yield st
    finally:
        d.clear(); d.update(saved)


def _quest_rows(st):
    return st.journal_list(1, kind="quest")


def test_accept_writes_accept_beat(wired):
    from aidnd.server.play.engine.world import _accept_contract
    cid = "ct:odo:1"
    ct = {"id": cid, "giver": "p_odo", "giver_name": "Одо", "kind": "bring",
          "want": "бочонок сидра", "where": "погреб", "reward": 6}
    _accept_contract(cid, ct)
    r = [x for x in _quest_rows(wired) if x["refs"] == [cid]]
    assert len(r) == 1 and r[0]["prov"] == "accept"


def test_complete_writes_done_beat(wired):
    from aidnd.server.play.mechanics.contracts import _contract_complete
    cid = "ct:odo:1"
    ct = {"id": cid, "giver": "p_odo", "giver_name": "Одо", "kind": "bring",
          "want": "бочонок сидра", "where": "погреб", "reward": 6}
    wired.purse_set(1, "p_odo", 20) if hasattr(wired, "purse_set") else None
    _contract_complete(ct)
    r = [x for x in _quest_rows(wired) if x["refs"] == [cid] and x["prov"] == "done"]
    assert len(r) == 1
```

> Note: `_contract_complete` pays out — it calls `_materialize_npc`/`purse_get`/`purse_add`. If the fixture needs the giver to have coins, seed via the store's purse API (`grep -n "def purse_set\|def purse_add\|def purse_get" src/aidnd/worldgen/store.py` and mirror `tests/play/test_journal_quests.py`'s original giver-funding, which this rewrite preserves). Keep the assertion focused on the `done` row landing; drop any brittle exact-text assertion (the stub owns wording now).

- [ ] **Step 2: Run the rewritten test to verify it fails**

Run: `uv run pytest tests/play/test_journal_quests.py -q`
Expected: FAIL — the sites still call `j_quest` (prov `told`/`saw`), so no `accept`/`done` prov rows exist.

- [ ] **Step 3: Offer beat — `dialogue.py:266-270`**

Replace the `if contract:` block:

```python
        contract = (_S.get("pending_offer") or {}).pop(npc, None)
        if contract:                    # the pitch is now SHOWN as the «Уговор» card → journal it
            from aidnd.server.play.engine.journal import j_beat
            look = (getattr(p, "persona", None) or {}).get("look") or {}
            j_beat(contract["id"], "offer", {
                "giver_name": p.name, "giver_role": p.role,
                "appearance": look.get("clothing") or "",
                "pitch": contract.get("pitch") or "",
            })
```

- [ ] **Step 4: Accept beat — `world.py:206` (+ import `:45`)**

At `world.py:45`, drop `j_quest` from the top import (keep `journal_feed` for now — Task 3 removes it):

```python
from aidnd.server.play.engine.journal import journal_feed
```

Replace `world.py:206` (`j_quest("told", summary, cid)`):

```python
    from aidnd.server.play.engine.journal import j_beat
    j_beat(cid, "accept", {
        "kind": ct.get("kind"), "want": ct.get("want"), "target_name": ct.get("target_name"),
        "where": ct.get("where", ""), "reward": ct.get("reward"),
        "giver_name": ct.get("giver_name") or _S["people"][ct["giver"]].name,
    })
```

- [ ] **Step 5: Step beat — `contracts.py:305-314` (NEW)**

In `_ct_advance`, insert the `step` beat between `save_contract` (`:313`) and the return (`:314`):

```python
    _store().save_contract(_wid(), ct["id"], "active", data)
    from aidnd.server.play.engine.journal import j_beat
    j_beat(ct["id"], "step", {
        "step_narr": step_narr, "next": _step_desc(steps[nstep]),
        "n": nstep + 1, "total": len(steps),
    })
    return f"{step_narr} Шаг {nstep} из {len(steps)}. Дальше: {_step_desc(steps[nstep])}."
```

- [ ] **Step 6: Done beat — `contracts.py:334-342`**

Replace the `from … import j_quest` (`:334`) and the `j_quest("saw", …)` (`:342`) — keep the `summary` build (`:336-341`) as the `what` value:

```python
    from aidnd.server.play.engine.journal import j_beat
    # (summary is still built above at :336-341)
    j_beat(ct["id"], "done", {
        "giver_name": p.name, "what": summary, "kind": ct.get("kind"),
    })
```

- [ ] **Step 7: Twist beat — `twist.py:10-18,41`**

Replace the guarded helper `_j_quest` (`:10-18`) with a beat variant:

```python
def _j_beat(cid, beat, facts):
    try:
        from aidnd.server.play.engine.journal import j_beat
    except ImportError:
        return
    try:
        j_beat(cid, beat, facts)
    except Exception:  # noqa: BLE001 — journaling is best-effort, never breaks the twist
        pass
```

Replace the call at `:41`:

```python
        _j_beat(ct["id"], "twist", {"reveal": reveal})   # single twist beat (see decision above)
```

- [ ] **Step 8: Overtaken beat — `pipeline.py:316-326,374`**

Replace `_j_quest_overtaken` (`:316-326`):

```python
def _j_beat_overtaken(cid: str, line: str, giver_name: str) -> None:
    """Guarded journal call (house pattern, twist.py:10): active/accepted overtaken quests get a
    closing beat; queued/offered/board never reached the player's journal yet."""
    try:
        from aidnd.server.play.engine.journal import j_beat
    except ImportError:
        return
    try:
        j_beat(cid, "overtaken", {"giver_line": line, "giver_name": giver_name})
    except Exception:  # noqa: BLE001
        pass
```

Replace the call at `:374`:

```python
                _j_beat_overtaken(ct["id"], line, ct.get("giver_name", "кто-то"))
```

- [ ] **Step 9: Fix the overtaken test's beat assertion — `test_quest_overtaken.py:80-97`**

Update the docstring and the assertion at `:96-97` from `prov == "saw"` to `prov == "overtaken"`, and stub the narrator (the test currently drives the real `_recheck_overtaken`, which now calls `j_beat` → a model call). Mirror the `_Voice` stub + `monkeypatch.setattr(core, "_model", …)` idiom from the rewritten `test_journal_quests.py`:

```python
    rows = st.journal_list(core._wid(), kind="quest")
    assert any(r.get("prov") == "overtaken" and cid in (r.get("refs") or []) for r in rows)
```

- [ ] **Step 10: Run tests to verify they pass**

Run: `uv run pytest tests/play/test_journal_quests.py tests/play/test_quest_overtaken.py -q`
Expected: PASS (both files).

- [ ] **Step 11: Commit**

```bash
git add src/aidnd/server/play/handlers/dialogue.py \
        src/aidnd/server/play/engine/world.py \
        src/aidnd/server/play/mechanics/contracts.py \
        src/aidnd/server/play/engine/quests/twist.py \
        src/aidnd/server/play/engine/quests/pipeline.py \
        tests/play/test_journal_quests.py tests/play/test_quest_overtaken.py
git commit -m "feat(play/quests): пять квест-бит + новый шаг-бит через j_beat (offer/accept/step/twist/done/overtaken)"
```

---

## Task 3: Remove every ambient write + one-shot legacy purge

**Files:**
- Modify: `src/aidnd/server/play/engine/journal.py` (delete `_emit`/`j_event`/`j_person`/`j_person_once`/`j_place`/`journal_feed`; add `purge_legacy_once`)
- Modify: `src/aidnd/server/play/engine/world.py:1300` + `:45` (drop `journal_feed`)
- Modify: `src/aidnd/server/play/handlers/dialogue.py:50,120` (drop `j_person_once`)
- Modify: `src/aidnd/server/play/engine/pc/hero.py:19,184` (drop `j_place`; keep seen-flag)
- Modify: `src/aidnd/server/play/handlers/freeform.py:374-376` (drop `j_event`)
- Modify: `src/aidnd/server/play/handlers/inventory.py:40,133` (drop `j_event`)
- Modify: `src/aidnd/worldgen/store.py` (add `journal_purge_nonquest`)
- Add: `tests/play/test_journal_migration.py`
- Update: `tests/play/test_geo_say_share.py`
- Delete: `tests/play/test_journal_feed.py`, `tests/play/test_journal_hooks.py`, `tests/play/test_journal_helper.py`, `tests/play/test_geo_journal_prov.py`

**Interfaces:** `purge_legacy_once(wid) -> None` — one-shot `DELETE FROM journal WHERE kind!='quest'` per world, guarded by a `journal_purged` flag. `store.journal_purge_nonquest(world_id) -> int` — rows removed.

- [ ] **Step 1: Write the failing migration test + the "no ambient rows" test**

```python
# tests/play/test_journal_migration.py
"""Legacy purge: non-quest rows (person/place/event) are deleted ONCE per world behind the
journal_purged flag; quest rows (incl. old un-typed prov) survive. Idempotent on re-run.
Also asserts the ambient helpers are GONE from journal.py."""
import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.engine import journal as J
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    saved = dict(core._S._d()); d = core._S._d()
    try:
        d.clear(); d.update(wid=1, gt=600)
        yield st
    finally:
        d.clear(); d.update(saved)


def _seed_mixed(st):
    st.journal_add(1, "event", "heard1", [], "кто-то сболтнул", 100)
    st.journal_add(1, "person", "saw", ["p1"], "встретил кого-то", 101)
    st.journal_add(1, "place", "saw", ["b1"], "впервые вошёл", 102)
    st.journal_add(1, "quest", "told", ["c_old"], "старая нетипизированная строка", 103)  # legacy
    st.journal_add(1, "quest", "accept", ["c_new"], "Я взялся за дело.", 104)


def test_purge_deletes_nonquest_keeps_quest(store):
    _seed_mixed(store)
    J.purge_legacy_once(1)
    kinds = {r["kind"] for r in store.journal_list(1)}
    assert kinds == {"quest"}
    provs = {r["prov"] for r in store.journal_list(1, kind="quest")}
    assert provs == {"told", "accept"}                       # legacy un-typed quest row survives


def test_purge_is_idempotent(store):
    _seed_mixed(store)
    J.purge_legacy_once(1)
    st_rows = store.journal_list(1)
    J.purge_legacy_once(1)                                   # second call: flag set → no-op
    assert store.journal_list(1) == st_rows
    assert store.flag_get(1, "journal_purged")


def test_ambient_helpers_are_gone():
    for name in ("journal_feed", "j_event", "j_person", "j_person_once", "j_place"):
        assert not hasattr(J, name), f"{name} must be deleted from journal.py"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/play/test_journal_migration.py -q`
Expected: FAIL — `AttributeError: module '…journal' has no attribute 'purge_legacy_once'` (and, until Step 5, `test_ambient_helpers_are_gone` fails because the helpers still exist).

- [ ] **Step 3: Add `journal_purge_nonquest` to `store.py`**

Next to `journal_list` (`store.py:259`):

```python
    def journal_purge_nonquest(self, world_id: int) -> int:
        """One-time migration: delete all non-quest journal rows for a world (person/place/event).
        Returns the number of rows removed. Protects the shared journal_cap from stale ambience."""
        with self._conn() as c:
            cur = c.execute("DELETE FROM journal WHERE world_id=? AND kind!='quest'", (world_id,))
            return cur.rowcount
```

- [ ] **Step 4: Add `purge_legacy_once` to `journal.py`**

```python
def purge_legacy_once(wid) -> None:
    """One-shot legacy compost: drop all non-quest rows for this world, guarded by a journal_purged
    flag so it runs exactly once after deploy. Best-effort no-op with no live store."""
    try:
        store = _store()
    except Exception:  # noqa: BLE001
        return None
    if wid is None or store is None:
        return None
    if store.flag_get(wid, "journal_purged"):
        return None
    store.journal_purge_nonquest(wid)
    store.flag_set(wid, "journal_purged")
    return None
```

- [ ] **Step 5: Delete the five ambient helpers from `journal.py`**

Remove `_emit`, `j_event`, `j_person`, `j_person_once`, `j_place`, `journal_feed` (their defs at `journal.py:26-86`). `j_beat` writes via `store.journal_add` directly, so `_emit` has no remaining caller. Update the module docstring (`:1-17`) to describe the single quest-beat writer + the one-shot purge. Confirm nothing else in-tree imports the deleted names:

```bash
grep -rn "journal_feed\|j_event\|j_person\|j_person_once\|j_place\|_emit\b" src/aidnd/ | grep -v "engine/journal.py"
```

Expected after edits: only the call sites removed in Steps 6-9 (fix any stray hit before proceeding).

- [ ] **Step 6: Drop `journal_feed` — `world.py:1300` + `:45`**

Delete the `journal_feed(feed)` line (`:1300`, and the surrounding `feed`-build only if it is now dead — verify with `grep -n "feed" src/aidnd/server/play/engine/world.py` around `:1290-1305`; the scene/live feed itself stays, only the journal write goes). Delete the now-empty top import (`:45`).

- [ ] **Step 7: Drop `j_person_once` — `dialogue.py:120` + `:50`**

Delete the `j_person_once(...)` call (`:120`) and its `place = …` line (`:118-119`) if `place` is now unused (verify), and the top import at `:50`.

- [ ] **Step 8: Drop `j_place` in `_mark_seen` — `hero.py:184` + `:19`**

Remove the `j_place(...)` call (`:184`) and the top `j_place` import (`:19`). Keep the seen-flag body (`:180-182`). Keep the `prov`/`text` kwargs on `_mark_seen` (now inert) so the geo share call-site `_mark_seen(bid, prov="told", text=…)` (`dialogue.py`) stays valid — the map reveal survives, only its journal row dies (spec §6). Resulting body:

```python
def _mark_seen(bid: str | None, *, prov: str = "saw", text: str | None = None) -> None:
    """Fog of war: location becomes known (map marker) when the player learns it — came themselves
    or heard from people. The persistent JOURNAL no longer records this (quest-only journal);
    prov/text are accepted for call-site compatibility but no row is written."""
    if bid and bid not in _seen():
        _S["seen"].add(bid)
        _store().flag_set(_wid(), f"seen|{bid}")
```

- [ ] **Step 9: Drop the two `j_event` sites — `freeform.py:374-376`, `inventory.py:133` + `:40`**

`freeform.py`: delete the `from … import j_event` (`:374`) and the `j_event("gave", …)` (`:376`). `inventory.py`: delete the `j_event("saw", …)` (`:133-134`) and the top import (`:40`).

- [ ] **Step 10: Update `test_geo_say_share.py` — drop the journal-row assertions**

The geo share still marks the map (`seen|<bid>`) but no longer writes a journal row. Edit `tests/play/test_geo_say_share.py`: keep the `seen|` assertions, remove the `_place_rows`/`journal_rows`/`prov=='told'` assertions (lines around `:88-93,97,879-880`). In `test_where_question_shares_direction_and_reveals` keep `res["line"]` + `"b_smithy" in _seen()`; in `test_ordinary_line_no_geo_no_mark` keep `"b_smithy" not in _seen()` and drop the `_place_rows(...) == []` line.

- [ ] **Step 11: Delete the obsolete ambient test files**

```bash
git rm tests/play/test_journal_feed.py tests/play/test_journal_hooks.py \
       tests/play/test_journal_helper.py tests/play/test_geo_journal_prov.py
```

(All four exercise helpers that no longer exist. Retro-fill is a non-goal, so there is no replacement for the ambient behavior — the new coverage lives in `test_journal_beat.py` + `test_journal_migration.py`.)

- [ ] **Step 12: Run the affected tests**

Run: `uv run pytest tests/play/test_journal_migration.py tests/play/test_geo_say_share.py tests/play/test_journal_store.py tests/play/test_newworld_journal.py -q`
Expected: PASS (migration 3, geo-say updated, store/newworld untouched-green).

- [ ] **Step 13: Full-suite gate**

Run: `uv run pytest tests -q`
Expected: PASS — no failures, no import errors from a stray deleted-helper reference. (Suite size ≈ 575 − 4 deleted files' tests + `test_journal_beat`(5) + `test_journal_migration`(3); the exact number will settle here — record it as the new baseline.)

- [ ] **Step 14: Commit**

```bash
git add -A
git commit -m "feat(play/quests): журнал только для дел — удалены амбиентные записи (feed/люди/места/события) + разовая чистка"
```

---

## Task 4: Grouped дела API (`journal_endpoint` → threads)

**Files:**
- Modify: `src/aidnd/server/play/handlers/misc.py:152-158`
- Add: `tests/play/test_journal_dela_api.py`

**Interfaces:** `GET /api/play/journal?limit=…` → `{"dela": [{cid, title, giver, status, thread:[{gt, beat, text}]}]}`, quests newest-beat-first, each `thread` gt-ascending. Enrichment from `_store().contracts(wid)` across all statuses; a cid with no live contract → `status="unknown"`, `title` falls back to the first row's text prefix. Legacy un-typed rows group and render (`beat` = their old `prov`). Runs `purge_legacy_once(wid)` lazily on first read.

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_journal_dela_api.py
"""GET /api/play/journal groups quest rows into per-quest threads: gt-ascending within a дело,
дела newest-beat-first, enriched title/giver/status from the live contract. Legacy un-typed rows
and orphan cids still render."""
import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.engine.session import persist
from aidnd.server.play.handlers import misc as misc_mod
from aidnd.worldgen import WorldStore


@pytest.fixture
def wired(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    monkeypatch.setattr(misc_mod, "_play", lambda: None)
    # дело A (roza): offer→accept→done, out of gt order on insert
    st.journal_add(1, "quest", "done", ["cA"], "Так и завершилось это дело.", 22080)
    st.journal_add(1, "quest", "offer", ["cA"], "Ко мне обратилась Роза.", 20940)
    st.journal_add(1, "quest", "accept", ["cA"], "Я согласился.", 21360)
    # дело B (gwen): a single later offer → should float ABOVE A (latest beat gt bigger)
    st.journal_add(1, "quest", "offer", ["cB"], "Ко мне обратилась Гвен.", 30000)
    st.save_contract(1, "cA", "done",
                     {"giver": "p_roza", "giver_name": "Роза Медовар", "kind": "bring"})
    st.save_contract(1, "cB", "active",
                     {"giver": "p_gwen", "giver_name": "Гвен Тихвуд", "kind": "befriend"})
    saved = dict(core._S._d()); d = core._S._d()
    try:
        d.clear(); d.update(wid=1)
        yield st
    finally:
        d.clear(); d.update(saved)


def test_groups_into_dela_newest_first(wired):
    out = misc_mod.journal_endpoint()
    dela = out["dela"]
    assert [g["cid"] for g in dela] == ["cB", "cA"]           # B's latest beat (30000) > A's (22080)


def test_thread_is_gt_ascending(wired):
    dela = {g["cid"]: g for g in misc_mod.journal_endpoint()["dela"]}
    gts = [t["gt"] for t in dela["cA"]["thread"]]
    assert gts == [20940, 21360, 22080]                      # story order regardless of insert order
    beats = [t["beat"] for t in dela["cA"]["thread"]]
    assert beats == ["offer", "accept", "done"]


def test_enrichment_title_giver_status(wired):
    dela = {g["cid"]: g for g in misc_mod.journal_endpoint()["dela"]}
    assert dela["cA"]["giver"] == "Роза Медовар"
    assert dela["cA"]["status"] == "done"
    assert "Роза Медовар" in dela["cA"]["title"] and "добыть" in dela["cA"]["title"]


def test_orphan_cid_renders_unknown(wired):
    wired.journal_add(1, "quest", "offer", ["cGhost"], "Некое забытое дело.", 40000)
    g = next(x for x in misc_mod.journal_endpoint()["dela"] if x["cid"] == "cGhost")
    assert g["status"] == "unknown" and g["thread"][0]["text"] == "Некое забытое дело."


def test_empty_journal(wired):
    for cid in ("cA", "cB"):
        pass
    fresh = misc_mod.journal_endpoint
    # wipe rows: a brand-new world id has none
    core._S._d()["wid"] = 999
    assert fresh()["dela"] == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/play/test_journal_dela_api.py -q`
Expected: FAIL — the endpoint still returns `{"entries": …}` (flat, `kind`-filtered), so `out["dela"]` is a `KeyError`.

- [ ] **Step 3: Reshape `journal_endpoint` — `misc.py:152-158`**

```python
@router.get("/api/play/journal")
def journal_endpoint(limit: int = 500):
    """Player chronicle «Хроника → дела»: quest rows grouped into per-quest first-person threads.
    Returns {dela:[{cid,title,giver,status,thread:[{gt,beat,text}]}]}, дела newest-beat-first,
    each thread oldest-beat-first (reads top-to-bottom as a story). No LLM on the read path."""
    _play()
    from aidnd.server.play.engine.core import _store, _wid
    from aidnd.server.play.engine.journal import purge_legacy_once
    wid = _wid()
    purge_legacy_once(wid)                                    # one-shot legacy compost (guard flag)
    rows = _store().journal_list(wid, kind="quest", limit=min(int(limit), 1000))
    cmap = {c["id"]: c for c in _store().contracts(wid)}      # live contracts across ALL statuses
    groups: dict = {}
    for r in rows:
        cid = (r.get("refs") or [None])[0]
        if cid:
            groups.setdefault(cid, []).append(r)
    _KD = {"bring": "добыть", "deliver": "отнести", "visit": "наведаться",
           "befriend": "расположить к себе", "clear": "зачистить"}
    dela = []
    for cid, thread in groups.items():
        thread.sort(key=lambda r: r["gt"])                   # story order
        c = cmap.get(cid) or {}
        giver = c.get("giver_name") or ""
        kind_ru = _KD.get(c.get("kind"), "дело")
        title = (f"{kind_ru} для {giver}" if giver
                 else (thread[0]["text"][:40] if thread else cid))
        dela.append({
            "cid": cid, "title": title, "giver": giver,
            "status": c.get("status", "unknown"),
            "thread": [{"gt": r["gt"], "beat": r["prov"], "text": r["text"]} for r in thread],
        })
    dela.sort(key=lambda g: g["thread"][-1]["gt"] if g["thread"] else 0, reverse=True)
    return {"dela": dela}
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/play/test_journal_dela_api.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Delete the obsolete flat-API test**

```bash
git rm tests/play/test_journal_api.py
```

(It asserts the flat `entries` + `kind` filter that no longer exist; `test_journal_dela_api.py` replaces its coverage.)

- [ ] **Step 6: Full-suite gate**

Run: `uv run pytest tests -q`
Expected: PASS — no failures.

- [ ] **Step 7: Commit**

```bash
git add src/aidnd/server/play/handlers/misc.py tests/play/test_journal_dela_api.py
git rm tests/play/test_journal_api.py
git commit -m "feat(play/quests): /api/play/journal — дела с нитями (группировка по cid, обогащение из контрактов)"
```

---

## Task 5: Frontend «Хроника → дела» — two-level view

**Files:**
- Modify: `src/aidnd/server/web/play.html:475-484` (panel/tabs)
- Modify: `src/aidnd/server/web/play.html:1280-1299` (`JTAB`/`jTab`/`JMARK`/`renderJournal`)

No pytest here (template JS). Verified by curling the endpoint + a browser check. Keep it modest — match `.jrow`/`.jgrp`/`.jmark`/`.jempty` idioms; no framework.

- [ ] **Step 1: Collapse the four tabs to a single дела panel — `:475-484`**

Replace the `<div id="journalpanel" …>` block (removing the `.jtabs` div entirely):

```html
    <div id="journalpanel" class="workpanel">
      <div class="cap">&#10022; Хроника — дела <span onclick="setView('explore')" style="cursor:pointer;color:var(--faint);float:right">✕</span></div>
      <div class="jbody" id="jbody"></div>
    </div>
```

- [ ] **Step 2: Rewrite the journal JS — `:1280-1299`**

Replace `let JTAB='event';`, `const JMARK=…;`, `function jTab(…)`, and `async function renderJournal(){…}` with:

```javascript
const JBEAT={offer:'✦',accept:'◆',step:'·',twist:'✕',reveal:'✕',done:'✓',overtaken:'—',failed:'✕'};
const JSTATUS={active:'в деле',done:'завершено',closed:'закрыто',offered:'предложено',board:'на доске',queued:'зреет',unknown:''};
let JOPEN={};                                              // cid → thread expanded?
async function renderJournal(){
  const el=$('jbody');if(!el)return;
  const r=await api('/api/play/journal');
  const dela=(r.dela||[]);
  if(!dela.length){el.innerHTML='<div class="jempty">пока пусто — дела впишутся сюда по ходу игры</div>';return;}
  el.innerHTML=dela.map(d=>{
    const open=!!JOPEN[d.cid], done=(d.status==='done'||d.status==='closed');
    const head=`<div class="jgrp jdela${done?' jdone':''}" style="cursor:pointer" onclick="toggleDela('${esc(d.cid)}')">`
      +`<span class="jmark">${open?'▾':'▸'}</span>${esc(d.title||'дело')}`
      +`<span class="ctw" style="margin-left:6px">${JSTATUS[d.status]||''}</span></div>`;
    const body=open
      ? d.thread.map(t=>`<div class="jrow"><span class="jmark">${JBEAT[t.beat]||'·'}</span>${esc(t.text)}</div>`).join('')
      : '';
    return head+body;
  }).join('');
}
function toggleDela(cid){JOPEN[cid]=!JOPEN[cid];renderJournal();}
```

The `setView('journal')` path (`:667`) already calls `renderJournal()`; the voice-command route (`:677`) and the header «хроника» link (`:419`) are unchanged. No `.jtabs`/`.jtab` CSS needs removing (harmless once the markup is gone), but you may drop `:61-63` for tidiness.

- [ ] **Step 3: Browser verify (dev server)**

Start the dev server (`.claude/launch.json` `aidnd` config or `uv run uvicorn aidnd.server.app:app --port 8000`), open the play page, drive a quest to at least the offer+accept beats (or seed a couple of quest rows via the store), then:

- [ ] `curl -s "http://127.0.0.1:8000/api/play/journal" | python3 -m json.tool` → shows `{"dela":[{cid,title,giver,status,thread:[…]}]}` with a gt-ascending thread.
- [ ] Open «хроника» (header link or `Хроника` voice command): the panel shows a **list of дела** (title + status), no four-tab bar. Clicking a дело **expands** its first-person thread (offer → accept → …), clicking again collapses it. A завершённое дело renders dashed/dim (`.jdone`). Empty world shows «пока пусто…».
- [ ] Screenshot the expanded Роза thread for the PR; confirm it reads top-to-bottom as a story and the beat glyphs line up.

- [ ] **Step 4: Commit**

```bash
git add src/aidnd/server/web/play.html
git commit -m "feat(play/quests): «Хроника → дела» — двухуровневый вид (список дел → раскрываемая нить)"
```

---

## Task 6: Suite gate + live playtest + deploy

**Files:** none (verification only).

- [ ] **Step 1: Full suite**

Run: `uv run pytest tests -q`
Expected: PASS — zero failures. If red, fix the offending task before proceeding; never paper over with skips.

- [ ] **Step 2: Lint**

Run: `uv run ruff check src/aidnd/server/play src/aidnd/worldgen/store.py`
Expected: clean — no unused-import warnings from the deleted helpers/imports.

- [ ] **Step 3: Live fraud-arc playtest (the standing `/playtest` method)**

Drive the Роза (Пигельмуль-style) arc end-to-end on a fresh-ish world with a live model:

- [ ] Ask Роза about work → the «Уговор» card shows and an `offer` beat lands.
- [ ] Accept → `accept` beat.
- [ ] (If the seed carries a `step`) advance a step → `step` beat naming the next step.
- [ ] Visit the villain node → the twist fires → `twist` beat («вскрылось…»).
- [ ] Complete → `done` beat («Так и завершилось это дело…»).
- [ ] Open «Хроника»: the thread must read like the spec §5 Роза example — coherent first-person past tense, no fabricated facts beyond the mechanics-confirmed reveal.
- [ ] Over ~10 ticks near the market (overheard speech, meeting NPCs, entering buildings): assert **nothing non-quest** lands in the journal — the дела list gains no rows from ambience — while the **live feed** still shows in-scene chatter and the **map markers / NPC cards** still populate.

Record the transcript via `/playtest`; note any wording/beat-glyph texture issues for a follow-up.

- [ ] **Step 4: Deploy**

Once green and the playtest reads right, ship via the `/deploy` skill (autonomous prod deploy per project convention). No `Co-Authored-By` trailer on any commit.

---

## Self-review notes (author's pass)

- **Spec coverage:** §3.3 `j_beat` one-write-path → Task 1; §3.2 hooks table (offer/accept/step/twist/done/overtaken) → Task 2 (with the NEW `step` at `contracts.py:305`); §2/§6 ambient removal + §4.3 migration purge → Task 3; §3.4/§4 grouping read path → Task 4; §3/§9 two-level UI → Task 5; §7 unit + live testing → Tasks 1-6. Non-goals honored: no retro-fill (legacy rows purged / un-typed quest rows kept but not synthesized), live feed + map seen-flags + NPC-card state untouched, no new PB key, no gates/rolls.
- **Settled decisions baked in:** one narrator call / one row for `offer`; temp `0.4` local literal (asserted in Task 1's `test_facts_reach_the_narrator_prompt`); legacy un-typed quest rows render (Task 4 `test_orphan_cid_renders_unknown` + migration `test_purge_deletes_nonquest_keeps_quest` keeps the `told` row).
- **Drift resolved:** the geo increment shipped between spec and HEAD — `j_place`/`_mark_seen` already carry `prov`/`text`, so Task 3 deletes the `hero.py:184` call and keeps the (now-inert) kwargs for the geo share call-site rather than reverting the signature; the geo map-mark survives, its journal row does not (spec §6). Four geo/journal test files that exercise deleted helpers are removed, `test_geo_say_share`/`test_quest_overtaken` are surgically updated, and `test_journal_api`/`test_journal_quests` are replaced — all enumerated with file:line above. All other spec anchors verified exact at HEAD.
- **`twist` vs `reveal`:** collapsed to a single `twist` beat because the twist seed exposes no deterministic deception/void marker (only `reveal_on`/`fact`/`adds`); labeling by sniffing `framer.reveal` text would violate "code owns facts". Both are in the closed set and render identically; `reveal` stays reserved. The §5 worked example's `reveal` label thus appears as `twist` in practice — a deliberate, honest simplification.
- **Placeholder scan:** every code step carries complete code; every test step carries real assertions and (where load-bearing) exact expected strings. The two soft spots are flagged inline, not hidden: (a) Task 2 Step 1's `_contract_complete` payout may need the giver funded via the store purse API — the note points at the accessor and the original test's funding to mirror; (b) Task 3 Steps 6-7 delete adjacent dead locals (`feed` build, `place=` line) only after a `grep` confirms they are unused.
- **Type consistency:** facts dict keys per beat (`giver_name`/`giver_role`/`appearance`/`pitch`; `kind`/`want`/`target_name`/`where`/`reward`; `step_narr`/`next`/`n`/`total`; `reveal`; `what`; `giver_line`) match spec §4.1 and are produced identically at the call sites (Task 2) and consumed by `_facts_ru` (Task 1). Journal row shape `{gt,kind='quest',prov=beat,refs=[cid],text}` (Task 1) is grouped verbatim by the API into `{cid,title,giver,status,thread:[{gt,beat,text}]}` (Task 4) and rendered field-for-field by `renderJournal` (Task 5). `journal_add`/`journal_list`/`contracts`/`journal_purge_nonquest` signatures match their store definitions.
- **Independent green:** Task 1 adds `j_beat` without removing anything (suite grows, nothing breaks); Task 2 rewires sites and updates only the two beat-asserting tests; Task 3 removes helpers and their now-orphaned tests in the same commit so the suite is green at the boundary; Task 4 swaps the API and its one test together. No task leaves the tree red.
