# Player Journal «Хроника» Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the player a browsable, epistemically-honest chronicle — an append-only `journal` table written **only** at existing render moments (a feed line received, a pitch shown, a person met, a room first entered, an item attribute revealed), captured verbatim with **zero LLM calls**, surfaced through a new `#journalpanel` with four tabs.

**Architecture:** One new SQLite table (`journal`) in `worldgen/store.py` with `journal_add`/`journal_list`; one thin helper module `engine/journal.py` (`j_event`/`j_quest`/`j_person`/`j_place` + a `journal_feed` pass) that resolves world-id/store/game-time internally and no-ops when no session is live; five capture hooks inline at existing render sites; one `GET /api/play/journal` endpoint; one `#journalpanel` UI peer of `invpanel`/`magicpanel`. No new tick, no morning batch, no LLM seam.

**Tech Stack:** Python 3, FastAPI, SQLite (stdlib `sqlite3`), pytest via `uv run pytest`, vanilla-JS single-file frontend (`server/web/play.html`).

## Global Constraints

Copied verbatim from the spec (`docs/superpowers/specs/2026-07-12-player-journal-design.md`); every task's requirements implicitly include this section:

- **Zero LLM calls anywhere in this system.** Every hook copies an already-rendered (or deterministically composed) string into a row via pure SQL. No summarizing, no rewriting.
- **`text` = the exact rendered string, never rewritten** for the fidelity-critical paths (overheard fragment, deed line, pitch). Quest-beat text is a deterministic non-LLM summary composed from contract fields.
- **Provenance never upgrades.** An L2 half-heard line is stored as the exact cutout fragment (`prov="heard2"`), never promoted to the full line. A later L1 hearing is a *separate* `heard1` row; the earlier row is untouched.
- **Unwitnessed events never journal.** The feed IS the player's rendered scene → a deed/speech in the feed was witnessed by construction. Deeds in other nodes never enter the feed → never journal.
- **Tunables live in PB.** `PB["journal_cap"] = 2000` lives in `session/config.py`; no journal magic number is hardcoded elsewhere.
- **Commit messages in Russian house style:** `feat(play/journal): …`.
- **NEVER add a `Co-Authored-By` trailer** (Claude or otherwise) to any commit.
- **Tests run via `uv run pytest`.** Pre-quest baseline is `363 passed` (~2 min); this plan adds **+26 new tests**. Absolute totals are fragile under serialized execution — if the emergent-quest Inc 1 plan lands first (order Inc 1 → journal → Inc 2 → Inc 3), the baseline is already `379` and this plan ends at `405`. State green as "+26 new, 0 failed", not an absolute.

## Field grammar (closed sets — used by every task)

| Field | Values | Meaning |
|---|---|---|
| `kind` | `person` · `event` · `quest` · `place` | UI tab (Люди · События · Дела · Места) |
| `prov` | `saw` · `heard1` · `heard2` · `told` | mark ✦ · ◐(full) · ◐(fragment) · ◌ |
| `refs` | JSON list of **raw** ids: `["garm"]`, `["odo"]`, `["ct:odo:1"]`, `["dagger7"]`, `[bid]` — empty `[]` for ambient | UI groups Люди/Места by entity |
| `text` | the exact rendered string (overheard/deed) or a deterministic composed summary (quest) | never LLM-authored |

> **refs store raw ids.** The spec's §4 examples show namespaced ids (`npc:odo`, `node:cellar`) for readability, but the helper wrappers receive the raw ids the code already uses (bare `pid`/`bid`/`iid`; contract ids already carry their own `ct:` prefix from `f"ct:{npc}:{_mt()}"`). The UI groups within a single kind-tab, so raw ids cannot collide across entity types. Store raw ids as-is.

## File Structure

- **Modify** `src/aidnd/worldgen/store.py` — new `journal` table in `_init`; `journal_add` / `journal_list` methods (Task 1).
- **Modify** `src/aidnd/server/play/engine/session/config.py` — `PB["journal_cap"] = 2000` (Task 1).
- **Create** `src/aidnd/server/play/engine/journal.py` — the hook helper module (Task 2, extended in Task 3).
- **Modify** `src/aidnd/server/play/engine/world.py` — Hook 1: pid-stamp deed dicts + one `journal_feed(feed)` call; Hook 2 accept (Task 3, Task 4).
- **Modify** `src/aidnd/server/play/handlers/dialogue.py` — Hook 2 pitch + Hook 3 first meeting (Task 4, Task 5).
- **Modify** `src/aidnd/server/play/mechanics/contracts.py` — Hook 2 complete (Task 4).
- **Modify** `src/aidnd/server/play/engine/pc/hero.py` — Hook 4 first visit (Task 5).
- **Modify** `src/aidnd/server/play/handlers/inventory.py` — Hook 5 item reveal (Task 5).
- **Modify** `src/aidnd/server/play/handlers/misc.py` — `GET /api/play/journal` (Task 6).
- **Modify** `src/aidnd/server/web/play.html` — `#journalpanel` UI (Task 7).
- **Create** `tests/play/test_journal_store.py`, `tests/play/test_journal_helper.py`, `tests/play/test_journal_feed.py`, `tests/play/test_journal_quests.py`, `tests/play/test_journal_hooks.py`, `tests/play/test_journal_api.py`.

---

### Task 1: Store layer — `journal` table + `journal_add`/`journal_list` + `PB["journal_cap"]`

**Files:**
- Modify: `src/aidnd/worldgen/store.py:30-70` (table in `_init`), add methods after `deed_status` (`:240-243`)
- Modify: `src/aidnd/server/play/engine/session/config.py:214` (add key before `look_dc`/at end of `PB`)
- Test: `tests/play/test_journal_store.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `WorldStore.journal_add(self, world_id: int, kind: str, prov: str, refs: list, text: str, gt: int) -> None` — append-only INSERT; after insert, prune oldest rows beyond `PB["journal_cap"]` for that world.
  - `WorldStore.journal_list(self, world_id: int, kind: str | None = None, limit: int = 200) -> list[dict]` — rows newest-first (`ORDER BY id DESC`); each dict has keys `gt` (int), `kind` (str), `prov` (str), `refs` (list, JSON-decoded), `text` (str).
  - `PB["journal_cap"] = 2000`.

- [ ] **Step 1: Write the failing test**

Create `tests/play/test_journal_store.py`:

```python
"""journal table: append-only, newest-first, kind filter, cap-prune keeps the newest."""

from aidnd.server.play.engine import core
from aidnd.worldgen import WorldStore


def _store(tmp_path):
    return WorldStore(str(tmp_path / "live.db"))


def test_add_and_list_newest_first(tmp_path):
    st = _store(tmp_path)
    st.journal_add(1, "event", "heard2", [], "… так и не … Марты, …", 512)
    st.journal_add(1, "event", "saw", ["garm"], "Гарм ныряет рукой в чужой кошель", 512)
    st.journal_add(1, "person", "saw", ["odo"], "встретил Одо — трактирщик", 513)
    rows = st.journal_list(1)
    assert [r["gt"] for r in rows] == [513, 512, 512]          # newest id first
    assert rows[0]["kind"] == "person" and rows[0]["refs"] == ["odo"]
    assert rows[2]["prov"] == "heard2" and rows[2]["refs"] == []


def test_kind_filter_and_limit(tmp_path):
    st = _store(tmp_path)
    st.journal_add(1, "quest", "told", ["ct:odo:1"], "взялся за дело", 514)
    st.journal_add(1, "quest", "saw", ["ct:odo:1"], "выполнено для Одо", 516)
    st.journal_add(1, "person", "saw", ["odo"], "встретил Одо", 513)
    q = st.journal_list(1, kind="quest")
    assert len(q) == 2 and all(r["kind"] == "quest" for r in q)
    assert q[0]["prov"] == "saw" and q[1]["prov"] == "told"    # newest-first
    assert len(st.journal_list(1, limit=1)) == 1


def test_per_world_isolation(tmp_path):
    st = _store(tmp_path)
    st.journal_add(1, "event", "saw", [], "мир 1", 1)
    st.journal_add(2, "event", "saw", [], "мир 2", 1)
    assert [r["text"] for r in st.journal_list(1)] == ["мир 1"]
    assert [r["text"] for r in st.journal_list(2)] == ["мир 2"]


def test_cap_prune_keeps_newest(tmp_path, monkeypatch):
    st = _store(tmp_path)
    monkeypatch.setitem(core.PB, "journal_cap", 5)             # small cap for a fast test
    for i in range(6):                                          # one over the cap
        st.journal_add(1, "event", "saw", [], f"строка {i}", i)
    rows = st.journal_list(1, limit=100)
    assert len(rows) == 5                                       # count == cap
    assert rows[0]["text"] == "строка 5"                        # newest survives
    assert "строка 0" not in [r["text"] for r in rows]          # oldest pruned
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_journal_store.py -q`
Expected: FAIL with `AttributeError: 'WorldStore' object has no attribute 'journal_add'`.

- [ ] **Step 3: Add the table to `_init`**

In `src/aidnd/worldgen/store.py`, inside `_init` (after the `npc_state` table at `:69-70`), add:

```python
            # player journal «Хроника» — append-only capture at render moments (docs/.../player-journal-design.md)
            c.execute("CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                      "world_id INT, gt INT, kind TEXT, prov TEXT, refs TEXT, text TEXT)")
```

- [ ] **Step 4: Add the methods**

In `src/aidnd/worldgen/store.py`, after `deed_status` (`:240-243`), add:

```python
    def journal_add(self, world_id: int, kind: str, prov: str, refs: list,
                    text: str, gt: int) -> None:
        """Append one chronicle row, then prune oldest beyond PB['journal_cap'] for this world."""
        from aidnd.server.play.engine.core import PB  # lazy: PB is the single home of the cap
        with self._conn() as c:
            c.execute("INSERT INTO journal (world_id,gt,kind,prov,refs,text) VALUES (?,?,?,?,?,?)",
                      (world_id, gt, kind, prov, json.dumps(refs or [], ensure_ascii=False), text))
            c.execute("DELETE FROM journal WHERE world_id=? AND id NOT IN "
                      "(SELECT id FROM journal WHERE world_id=? ORDER BY id DESC LIMIT ?)",
                      (world_id, world_id, PB["journal_cap"]))

    def journal_list(self, world_id: int, kind: str | None = None, limit: int = 200) -> list:
        """Chronicle rows newest-first; optional kind filter. refs JSON-decoded to a list."""
        q = "SELECT gt,kind,prov,refs,text FROM journal WHERE world_id=?"
        args: list = [world_id]
        if kind:
            q += " AND kind=?"; args.append(kind)
        q += " ORDER BY id DESC LIMIT ?"; args.append(limit)
        with self._conn() as c:
            rows = c.execute(q, args).fetchall()
        return [{"gt": r[0], "kind": r[1], "prov": r[2],
                 "refs": json.loads(r[3] or "[]"), "text": r[4]} for r in rows]
```

> Note: `json` is already imported at `store.py:17`. The lazy `import PB` inside `journal_add` avoids a load-time layering cycle (worldgen→server) while keeping the cap in PB (Global Constraints).

- [ ] **Step 5: Add the PB tunable**

In `src/aidnd/server/play/engine/session/config.py`, inside the `PB` dict, immediately before the final `"look_dc": 8,` line (`:212`), add:

```python
    # PLAYER JOURNAL «Хроника»: rows kept per world; prune oldest on insert (docs/.../player-journal-design.md)
    "journal_cap": 2000,
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/play/test_journal_store.py -q`
Expected: PASS (4 tests).

- [ ] **Step 7: Commit**

```bash
git add src/aidnd/worldgen/store.py src/aidnd/server/play/engine/session/config.py tests/play/test_journal_store.py
git commit -m "feat(play/journal): таблица journal + journal_add/journal_list с cap-prune (PB journal_cap=2000)"
```

---

### Task 2: Hook helper module `engine/journal.py` — `j_event`/`j_quest`/`j_person`/`j_place`

**Files:**
- Create: `src/aidnd/server/play/engine/journal.py`
- Test: `tests/play/test_journal_helper.py` (create)

**Interfaces:**
- Consumes: `WorldStore.journal_add(world_id, kind, prov, refs, text, gt)` (Task 1); `_store()` / `_wid()` / `_gt()` from `session/persist`, `session/state`, `session/time`.
- Produces (later plans rely on these EXACT names — the emergent-quest pipeline will call the same `j_quest` for twist/foreshadow beats with no signature change):
  - `j_event(prov: str, text: str, refs: list | None = None) -> None` — `kind="event"`.
  - `j_quest(prov: str, text: str, cid: str) -> None` — `kind="quest"`, `refs=[cid]`.
  - `j_person(prov: str, text: str, pid: str) -> None` — `kind="person"`, `refs=[pid]`.
  - `j_place(text: str, bid: str) -> None` — `kind="place"`, `prov="saw"`, `refs=[bid]`.
  - All resolve `_wid()`/`_store()`/`_gt()` internally and are a **safe no-op returning `None`** when no session/store is available (never raise).

- [ ] **Step 1: Write the failing test**

Create `tests/play/test_journal_helper.py`:

```python
"""Thin journal wrappers: resolve wid/store/gt internally; safe no-op with no session."""

import pytest

from aidnd.server.play.engine import journal
from aidnd.worldgen import WorldStore


@pytest.fixture
def wired(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(journal, "_store", lambda: st)
    monkeypatch.setattr(journal, "_wid", lambda: 1)
    monkeypatch.setattr(journal, "_gt", lambda: 512)
    return st


def test_j_event_default_empty_refs(wired):
    journal.j_event("heard2", "… так и не … Марты, …")
    r = wired.journal_list(1)
    assert r == [{"gt": 512, "kind": "event", "prov": "heard2",
                  "refs": [], "text": "… так и не … Марты, …"}]


def test_j_event_with_refs(wired):
    journal.j_event("saw", "Гарм ныряет рукой в чужой кошель", refs=["garm"])
    assert wired.journal_list(1)[0]["refs"] == ["garm"]


def test_j_quest_wraps_cid(wired):
    journal.j_quest("told", "взялся за дело для Одо", "ct:odo:1")
    r = wired.journal_list(1)[0]
    assert r["kind"] == "quest" and r["prov"] == "told" and r["refs"] == ["ct:odo:1"]


def test_j_person_wraps_pid(wired):
    journal.j_person("saw", "встретил Одо — трактирщик", "odo")
    r = wired.journal_list(1)[0]
    assert r["kind"] == "person" and r["refs"] == ["odo"]


def test_j_place_is_always_saw(wired):
    journal.j_place("впервые вошёл в Трактир «Пьяный вол»", "b:tav")
    r = wired.journal_list(1)[0]
    assert r["kind"] == "place" and r["prov"] == "saw" and r["refs"] == ["b:tav"]


def test_no_session_is_noop(monkeypatch):
    def boom():
        raise RuntimeError("no live session")
    monkeypatch.setattr(journal, "_store", boom)
    monkeypatch.setattr(journal, "_wid", lambda: None)
    assert journal.j_event("saw", "x") is None                 # never raises
    assert journal.j_person("saw", "x", "p") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_journal_helper.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'aidnd.server.play.engine.journal'`.

- [ ] **Step 3: Write the module**

Create `src/aidnd/server/play/engine/journal.py`:

```python
"""Player-journal capture helpers — thin, LLM-free wrappers over WorldStore.journal_add.

Each wrapper resolves world-id / store / game-time internally and is a SAFE NO-OP
(returns None, never raises) when no live session/store is available. Called from the
five capture hooks at existing render sites; also hosts journal_feed (Hook 1 pass).

Import the id/store/time resolvers from the SESSION LEAF modules (not core) so a
top-level import from any hook site cannot form a load-time cycle.

Key functions
-------------
j_event(prov, text, refs=None) : kind=event row (overheard line, witnessed deed, item reveal).
j_quest(prov, text, cid)       : kind=quest row, refs=[cid] (pitch/accept=told, outcome=saw).
j_person(prov, text, pid)      : kind=person row, refs=[pid] (first meeting, later facts).
j_place(text, bid)             : kind=place row, prov=saw, refs=[bid] (first visit).
journal_feed(feed)             : Hook 1 pass — one event row per witnessed speech/deed (Task 3).
"""

from __future__ import annotations

from aidnd.server.play.engine.session.persist import _store
from aidnd.server.play.engine.session.state import _wid
from aidnd.server.play.engine.session.time import _gt


def _emit(kind: str, prov: str, refs: list, text: str) -> None:
    """One row via journal_add — silent no-op if there's no live world/store."""
    try:
        wid = _wid()
        store = _store()
    except Exception:  # noqa: BLE001 — no live session: capture is best-effort, never fatal
        return None
    if wid is None or store is None:
        return None
    store.journal_add(wid, kind, prov, list(refs or []), text, _gt())
    return None


def j_event(prov: str, text: str, refs: list | None = None) -> None:
    return _emit("event", prov, refs or [], text)


def j_quest(prov: str, text: str, cid: str) -> None:
    return _emit("quest", prov, [cid], text)


def j_person(prov: str, text: str, pid: str) -> None:
    return _emit("person", prov, [pid], text)


def j_place(text: str, bid: str) -> None:
    return _emit("place", "saw", [bid], text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/play/test_journal_helper.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/aidnd/server/play/engine/journal.py tests/play/test_journal_helper.py
git commit -m "feat(play/journal): модуль-хелпер journal.py — j_event/j_quest/j_person/j_place, безопасный no-op без сессии"
```

---

### Task 3: Hook 1 — overheard speech & witnessed deeds (`journal_feed` + feed pid-stamps)

**Files:**
- Modify: `src/aidnd/server/play/engine/journal.py` (add `journal_feed`)
- Modify: `src/aidnd/server/play/engine/world.py` — deed feed sites `:749`, `:1080-1085`, `:1094-1099`, `:1116-1121`, `:1212-1213`, `:1227-1228`, `:1234`; call site in `_live_tick` at `:1242`
- Test: `tests/play/test_journal_feed.py` (create)

**Interfaces:**
- Consumes: `j_event(prov, text, refs=None)` (Task 2).
- Produces: `journal_feed(feed: list[dict]) -> None` — iterates a tick's `feed`; for each `{"k":"speech","tier":int,...}` with `tier` in `(1, 2)` emits `event/heard1` (tier 1) or `event/heard2` (tier 2) with `refs=[]` and the exact `text`; for each `{"k":"deed","pid":<id>,...}` emits `event/saw` with `refs=[pid]` and the exact `text`. Speech `tier == 3`, murmur (never in feed), and ambient/"зал" deeds (no `"pid"`) produce **no row**.

Rationale for the pass (vs inline calls): the feed IS the witnessed set, so one pass over the fully-built feed captures exactly what the screen showed and is unit-testable with a synthetic feed. Deed dicts carry only a display `who`, so the actor `pid` is stamped onto each deed dict at its append site.

- [ ] **Step 1: Write the failing test**

Create `tests/play/test_journal_feed.py`:

```python
"""Hook 1: journal_feed captures witnessed speech (tier 1/2) and deeds (with a pid).
Unwitnessed deeds are structurally impossible — they never enter the feed → no row."""

import pytest

from aidnd.server.play.engine import journal
from aidnd.worldgen import WorldStore


@pytest.fixture
def wired(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(journal, "_store", lambda: st)
    monkeypatch.setattr(journal, "_wid", lambda: 1)
    monkeypatch.setattr(journal, "_gt", lambda: 512)
    return st


def test_tier1_speech_is_heard1_verbatim(wired):
    journal.journal_feed([{"k": "speech", "who": "Бронт", "tier": 1, "text": "полная фраза"}])
    r = wired.journal_list(1)
    assert len(r) == 1 and r[0]["prov"] == "heard1"
    assert r[0]["text"] == "полная фраза" and r[0]["refs"] == []


def test_tier2_speech_is_heard2_fragment(wired):
    journal.journal_feed([{"k": "speech", "who": "Бронт", "tier": 2,
                           "text": "… так и не … Марты, …"}])
    r = wired.journal_list(1)
    assert len(r) == 1 and r[0]["prov"] == "heard2"
    assert r[0]["text"] == "… так и не … Марты, …"


def test_tier3_speech_and_murmur_skip(wired):
    journal.journal_feed([{"k": "speech", "who": "зал", "tier": 3,
                           "text": "у «зала» о чём-то говорят"},
                          {"k": "deed", "who": "зал", "text": "за столами гудит негромкий говор"}])
    assert wired.journal_list(1) == []                         # neither journals


def test_witnessed_deed_is_saw_with_actor_ref(wired):
    journal.journal_feed([{"k": "deed", "who": "Гарм", "pid": "garm",
                           "text": "Гарм ныряет рукой в чужой кошель"}])
    r = wired.journal_list(1)
    assert len(r) == 1 and r[0]["prov"] == "saw"
    assert r[0]["refs"] == ["garm"] and r[0]["text"] == "Гарм ныряет рукой в чужой кошель"


def test_unwitnessed_deed_no_row(wired):
    # The market theft happens in another node → it is NEVER appended to the player's feed.
    # journal_feed only ever sees the witnessed feed → exactly the one witnessed deed journals.
    feed = [{"k": "deed", "who": "Гарм", "pid": "garm", "text": "Гарм ныряет в чужой кошель"}]
    journal.journal_feed(feed)
    r = wired.journal_list(1)
    assert len(r) == 1 and r[0]["refs"] == ["garm"]            # no market-theft row exists


def test_mixed_feed_order_preserved(wired):
    journal.journal_feed([
        {"k": "speech", "who": "Бронт", "tier": 2, "text": "… Марты …"},
        {"k": "deed", "who": "Гарм", "pid": "garm", "text": "срезает кошель"},
        {"k": "deed", "who": "зал", "text": "гул толпы"},       # ambient — skipped
    ])
    r = wired.journal_list(1)                                   # newest-first
    assert [x["kind"] for x in r] == ["event", "event"]
    assert r[0]["refs"] == ["garm"] and r[1]["prov"] == "heard2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_journal_feed.py -q`
Expected: FAIL with `AttributeError: module 'aidnd.server.play.engine.journal' has no attribute 'journal_feed'`.

- [ ] **Step 3: Add `journal_feed` to `journal.py`**

Append to `src/aidnd/server/play/engine/journal.py`:

```python
def journal_feed(feed: list) -> None:
    """Hook 1 pass over one tick's feed: the feed IS the witnessed scene.
    speech tier 1 → event/heard1 (full) · tier 2 → event/heard2 (cutout fragment) ·
    tier 3 & murmur → skip. deed with a real actor pid → event/saw refs=[pid] ·
    ambient/'зал' deed (no pid) → skip. text is copied exactly, never rewritten."""
    for e in feed or []:
        if e.get("k") == "speech":
            tier = e.get("tier")
            if tier == 1:
                j_event("heard1", e.get("text", ""), refs=[])
            elif tier == 2:
                j_event("heard2", e.get("text", ""), refs=[])
        elif e.get("k") == "deed" and e.get("pid"):
            j_event("saw", e.get("text", ""), refs=[e["pid"]])
```

- [ ] **Step 4: Run the journal_feed test to verify it passes**

Run: `uv run pytest tests/play/test_journal_feed.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Stamp the actor `pid` onto each deed feed dict in `world.py`**

The deed feed dicts carry only a display `who`; add the raw actor `pid` so `journal_feed` can build `refs`. Make these seven edits in `src/aidnd/server/play/engine/world.py` (each adds one key, leaving `text` untouched):

At `:749-750` (NPC↔NPC settle — actor is `buyer`):

```python
            feed.append({"k": "deed", "who": b_disp, "pid": buyer,
                         "text": f"отсчитывает {price} зм — «{deal['good']}» переходит из рук в руки"})
```

At `:1080-1086` (pickpocket cuts the player's purse — actor `pid`):

```python
                        feed.append(
                            {
                                "k": "deed",
                                "who": _display(pid, people),
                                "pid": pid,
                                "text": f"ловко срезает твой кошель — минус {take} зм!",
                            }
                        )
```

At `:1094-1100` (pulls a named item from the player — actor `pid`):

```python
                        feed.append(
                            {
                                "k": "deed",
                                "who": _display(pid, people),
                                "pid": pid,
                                "text": f"вытягивает у тебя «{nm}»!",
                            }
                        )
```

At `:1116-1122` (NPC steals from another, player witnesses — actor `pid`):

```python
                    feed.append(
                        {
                            "k": "deed",
                            "who": _display(pid, people),
                            "pid": pid,
                            "text": f"тянет что-то из добра ({_display(vid, people)}) — ты это ВИДИШЬ",
                        }
                    )
```

At `:1212-1213` (promise — actor `pid`):

```python
                feed.append({"k": "deed", "who": who, "pid": pid,
                             "text": f"даёт слово: {str(a.get('what') or '')[:60]}"})
```

At `:1227-1228` (pays for food — actor `pid`):

```python
                        feed.append({"k": "deed", "who": _display(pid, people), "pid": pid,
                                     "text": f"кидает пару монет за {a['item']}"})
```

At `:1234` (free-action `does` narration — actor `pid`):

```python
            feed.append({"k": "deed", "who": who, "pid": pid, "text": does[:150]})
```

> Do NOT stamp the ambient/"зал" deeds (`:755`, `:758`, `:1237`, `:1241`) — those have no actor and must not journal.

- [ ] **Step 6: Call `journal_feed(feed)` once per tick in `_live_tick`**

Add the import to the `journal`-imports region near the top of `src/aidnd/server/play/engine/world.py` (after the existing engine imports, e.g. after `:58`):

```python
from aidnd.server.play.engine.journal import journal_feed
```

In `_live_tick`, immediately after the idle-ambient backstop block (`:1238-1241`) and before `if zones_l:` (`:1242`), insert:

```python
    journal_feed(feed)  # Hook 1: capture witnessed speech & deeds into the chronicle
```

- [ ] **Step 7: Run the full journal + a quick smoke of the play sound tests**

Run: `uv run pytest tests/play/test_journal_feed.py tests/play/test_overheard.py tests/play/test_sound.py -q`
Expected: PASS (journal_feed 6 + overheard/sound unchanged).

- [ ] **Step 8: Commit**

```bash
git add src/aidnd/server/play/engine/journal.py src/aidnd/server/play/engine/world.py tests/play/test_journal_feed.py
git commit -m "feat(play/journal): Hook 1 — journal_feed фиксирует услышанную речь (heard1/heard2) и увиденные деяния (saw); тир 3/ропот пропускаются"
```

---

### Task 4: Hook 2 — quest arc beats (pitch → told, accept → told, complete → saw)

**Files:**
- Modify: `src/aidnd/server/play/handlers/dialogue.py:181-182` (pitch shown in `say`)
- Modify: `src/aidnd/server/play/engine/world.py:167-180` (accept in `contract_accept`)
- Modify: `src/aidnd/server/play/mechanics/contracts.py:324-326` (outcome in `_contract_complete`)
- Test: `tests/play/test_journal_quests.py` (create)

**Interfaces:**
- Consumes: `j_quest(prov, text, cid)` (Task 2).
- Produces: three journal rows over a contract's life — `quest/told` when the pitch card is revealed (`refs=[contract["id"]]`, `text=contract["pitch"]`), `quest/told` on accept (`refs=[cid]`, the accept summary), `quest/saw` on completion (`refs=[ct["id"]]`, the outcome summary). The emergent-quest pipeline (separate plan) reuses the SAME `j_quest` for twist/foreshadow beats — no signature change.

> **Scope note (resolved ambiguity):** the spec §5 defines exactly these three beats and only `_contract_complete` as the outcome closer (its docstring: "Full payout of ANY completed contract"). The current code has **no distinct player-facing failed/expired closer** for improvised contracts (the `deals.py` `failed`/`done` writes belong to the separate deal-gate morning-batch subsystem, out of this spec's §5 scope). When a dedicated fail/expire closer lands it calls the same `j_quest("saw", …, cid)` — the helper needs no change.

- [ ] **Step 1: Write the failing test**

Create `tests/play/test_journal_quests.py`:

```python
"""Hook 2: a contract's beats land in the chronicle — pitch (told), accept (told),
complete (saw) — all sharing refs=[contract id], in id order."""

import asyncio
from types import SimpleNamespace

import pytest

from aidnd.server.play.engine import core, journal
from aidnd.server.play.engine import world as world_mod
from aidnd.server.play.engine.pc import hero as hero_mod
from aidnd.server.play.mechanics import contracts as ct_mod
from aidnd.worldgen import WorldStore


class _Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


@pytest.fixture
def wired(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    for mod in (core, journal, world_mod, hero_mod, ct_mod):  # hero: _pc_remember resolves store here
        monkeypatch.setattr(mod, "_store", lambda: st, raising=False)
        monkeypatch.setattr(mod, "_wid", lambda: 1, raising=False)
    monkeypatch.setattr(journal, "_gt", lambda: 514)
    core._S.clear()
    core._S["gt"] = 514
    return st


def test_accept_writes_quest_told(wired, monkeypatch):
    monkeypatch.setattr(world_mod, "_play", lambda: None, raising=False)
    wired.save_contract(1, "ct:odo:1", "offered",
                        {"giver": "odo", "giver_name": "Одо", "kind": "bring",
                         "want": "бочонок сидра", "where": "погреб"})
    asyncio.run(world_mod.contract_accept(_Req({"id": "ct:odo:1"})))
    r = wired.journal_list(1, kind="quest")
    assert len(r) == 1 and r[0]["prov"] == "told" and r[0]["refs"] == ["ct:odo:1"]
    assert r[0]["text"] == "взялся за дело для Одо: bring — бочонок сидра (погреб)"


def test_complete_writes_quest_saw(wired, monkeypatch):
    # _contract_complete pays out & closes; stub the heavy neighbours it calls.
    people = {"odo": SimpleNamespace(name="Одо", state=SimpleNamespace(
        rel=lambda who: {"trust": 0.0, "affinity": 0.0},
        memory=SimpleNamespace(add=lambda *a, **k: None)))}
    core._S["people"] = people
    monkeypatch.setattr(ct_mod, "_materialize_npc", lambda *a, **k: None)
    monkeypatch.setattr(ct_mod, "_npc_save", lambda *a, **k: None)
    monkeypatch.setattr(ct_mod, "_pc_remember", lambda *a, **k: None)
    monkeypatch.setattr(ct_mod, "_mt", lambda: 516, raising=False)
    import aidnd.server.play.engine.deeds as dd
    monkeypatch.setattr(dd, "record", lambda *a, **k: None, raising=False)
    wired.purse_add(1, "odo", 50)
    ct = {"id": "ct:odo:1", "giver": "odo", "kind": "bring",
          "want": "бочонок сидра", "reward": 5}
    ct_mod._contract_complete(ct)
    r = wired.journal_list(1, kind="quest")
    assert len(r) == 1 and r[0]["prov"] == "saw" and r[0]["refs"] == ["ct:odo:1"]
    assert r[0]["text"] == "выполнено для Одо: бочонок сидра доставлен"
```

> If the red phase shows `_contract_complete` reaching a neighbour not stubbed above (e.g. `_pc_coins`), stub it the same way — the assertion under test is only the `quest/saw` row.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_journal_quests.py -q`
Expected: FAIL — `journal_list(1, kind="quest")` is empty (hooks not wired).

- [ ] **Step 3: Wire the accept beat in `contract_accept`**

In `src/aidnd/server/play/engine/world.py`, add the import near the other engine imports (after `:58`, alongside the Task 3 `journal_feed` import):

```python
from aidnd.server.play.engine.journal import j_quest
```

Inside `contract_accept`, after the `_pc_remember(...)` call (`:174-179`) and before `return {...}` (`:180`), add:

```python
    j_quest("told", f"взялся за дело для {ct['giver_name']}: {ct.get('kind')} — "
                    f"{ct.get('want') or ct.get('target_name')} ({ct['where']})", cid)
```

- [ ] **Step 4: Wire the complete beat in `_contract_complete`**

In `src/aidnd/server/play/mechanics/contracts.py`, add near the top-of-module imports:

```python
from aidnd.server.play.engine.journal import j_quest
```

Inside `_contract_complete`, immediately after the `save_contract(... "done" ...)` call (`:324-326`), add (note: if the emergent-quest Inc 1 plan has already landed, `_contract_complete` also carries a `quest_writeback` block at its very tail — insert this `j_quest` right after the `done` `save_contract`, NOT at the function end):

```python
    _suf = " доставлен" if ct.get("kind") in ("bring", "deliver") else ""
    j_quest("saw", f"выполнено для {p.name}: "
                   f"{ct.get('want') or ct.get('target_name')}{_suf}", ct["id"])
```

> The outcome text is a deterministic non-LLM summary composed from contract fields (matches spec §5's `выполнено для Одо: бочонок сидра доставлен` for the bring case; the `доставлен` suffix is kind-scoped, omitted for non-bring/deliver kinds).

- [ ] **Step 5: Wire the pitch beat in `say`**

In `src/aidnd/server/play/handlers/dialogue.py`, add to the `core` import block (`:28-45`) — or a dedicated import line — :

```python
from aidnd.server.play.engine.journal import j_quest
```

Inside `say`, replace the pitch-reveal block (`:181-182`):

```python
    if _WORK_INTEREST_RE.search(text):  # player asked about work — reveal the stashed errand, if any
        contract = (_S.get("pending_offer") or {}).pop(npc, None)
```

with:

```python
    if _WORK_INTEREST_RE.search(text):  # player asked about work — reveal the stashed errand, if any
        contract = (_S.get("pending_offer") or {}).pop(npc, None)
        if contract:                    # the pitch is now SHOWN as the «Уговор» card → journal it
            j_quest("told", contract.get("pitch") or "", contract["id"])
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/play/test_journal_quests.py -q`
Expected: PASS (2 tests).

- [ ] **Step 7: Commit**

```bash
git add src/aidnd/server/play/handlers/dialogue.py src/aidnd/server/play/engine/world.py src/aidnd/server/play/mechanics/contracts.py tests/play/test_journal_quests.py
git commit -m "feat(play/journal): Hook 2 — вехи заказа в хронике: питч/приём (told), исполнение (saw), refs=[id заказа]"
```

---

### Task 5: Hooks 3–5 — first meeting (person/saw), first visit (place/saw), item reveal (event/saw)

**Files:**
- Modify: `src/aidnd/server/play/handlers/dialogue.py:82-85` (first meeting in `talk`)
- Modify: `src/aidnd/server/play/engine/pc/hero.py:176-181` (first visit in `_mark_seen`)
- Modify: `src/aidnd/server/play/handlers/inventory.py:118-127` (item reveal in `inspect_item`)
- Test: `tests/play/test_journal_hooks.py` (create)

**Interfaces:**
- Consumes: `j_person(prov, text, pid)`, `j_place(text, bid)`, `j_event(prov, text, refs=None)` (Task 2); `_binfo(bid) -> {"name":…}` (`engine/core.py:136`).
- Produces:
  - Hook 3: on first meeting (`talk`, `first == True`) → one `person/saw` row, `refs=[npc]`, `text="встретил {имя} — {роль}, {место}"`. A later fact about a known pid appends another `person` row sharing `refs=[pid]` (grouping mechanism — tested at the store level).
  - Hook 4: on first visit (`_mark_seen`, `seen|<bid>` newly set) → one `place/saw` row, `refs=[bid]`, `text="впервые вошёл в {название}"`. Revisit = no row.
  - Hook 5: on item inspection that grows the known-set (`inspect_item`) → one `event/saw` row, `refs=[iid]`, `text="{имя}: открылось — {новые атрибуты}"`. Unchanged known-set = no row.

- [ ] **Step 1: Write the failing test**

Create `tests/play/test_journal_hooks.py`:

```python
"""Hooks 3–5: first meeting (person/saw), first visit once (place/saw, no dup),
item reveal on known-set growth (event/saw, no dup). Person rows accumulate per pid."""

import asyncio
from types import SimpleNamespace

import pytest

from aidnd.server.play.engine import core, journal
from aidnd.server.play.engine.pc import hero as hero_mod
from aidnd.server.play.handlers import dialogue as dlg_mod
from aidnd.server.play.handlers import inventory as inv_mod
from aidnd.worldgen import WorldStore


class _Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


@pytest.fixture
def wired(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    for mod in (core, journal, hero_mod, dlg_mod, inv_mod):
        monkeypatch.setattr(mod, "_store", lambda: st, raising=False)
        monkeypatch.setattr(mod, "_wid", lambda: 1, raising=False)
    monkeypatch.setattr(journal, "_gt", lambda: 513)
    core._S.clear()
    return st


# --- Hook 4: first visit -------------------------------------------------------

def test_first_visit_writes_place_saw_once(wired, monkeypatch):
    core._S["seen"] = set()
    wired.save_building(1, "b:tav", True, 3, "Трактир", {"name": "Трактир «Пьяный вол»"})
    hero_mod._mark_seen("b:tav")
    hero_mod._mark_seen("b:tav")                               # revisit — adds nothing
    r = wired.journal_list(1, kind="place")
    assert len(r) == 1 and r[0]["prov"] == "saw" and r[0]["refs"] == ["b:tav"]
    assert r[0]["text"] == "впервые вошёл в Трактир «Пьяный вол»"


# --- Hook 5: item reveal -------------------------------------------------------

def test_item_reveal_writes_event_saw_on_growth(wired, monkeypatch):
    monkeypatch.setattr(inv_mod, "_play", lambda: (None, {}, None, None, None), raising=False)
    it = {"id": "dagger7", "name": "кинжал", "kind": "weapon", "form": "клинок",
          "attrs": {"острота": {"surface": 30, "true": 80},
                    "ценность": {"surface": 40, "true": 40}}, "hidden": []}
    wired.save_item(it)
    wired.inv_add(1, "dagger7", "pc", known=[])
    asyncio.run(inv_mod.inspect_item(_Req({"item": "dagger7", "via": "expert"})))
    r = wired.journal_list(1, kind="event")
    assert len(r) == 1 and r[0]["prov"] == "saw" and r[0]["refs"] == ["dagger7"]
    assert r[0]["text"].startswith("кинжал: открылось —")
    asyncio.run(inv_mod.inspect_item(_Req({"item": "dagger7", "via": "expert"})))  # nothing new
    assert len(wired.journal_list(1, kind="event")) == 1      # no duplicate row


# --- Hook 3: first meeting + person accumulation -------------------------------

def test_first_meeting_writes_person_saw(wired, monkeypatch):
    monkeypatch.setattr(journal, "j_person",
                        lambda prov, text, pid: wired.journal_add(1, "person", prov, [pid], text, 513))
    # exercise the composed text directly (talk() bootstraps a full session otherwise):
    journal.j_person("saw", "встретил Одо — трактирщик, Трактир «Пьяный вол»", "odo")
    r = wired.journal_list(1, kind="person")
    assert len(r) == 1 and r[0]["refs"] == ["odo"] and r[0]["prov"] == "saw"


def test_person_rows_accumulate_by_ref(wired):
    journal.j_person("saw", "встретил Одо — трактирщик", "odo")
    journal.j_person("heard1", "слышал про Одо: он в долгах", "odo")   # a later fact about odo
    r = wired.journal_list(1, kind="person")
    assert len(r) == 2 and all(x["refs"] == ["odo"] for x in r)        # grouped by the same pid
```

> `test_first_meeting_writes_person_saw` asserts the composed first-meeting **text** and the `person/saw` shape; it does not boot the full `talk()` session (which requires `_play`'s world bootstrap). `test_person_rows_accumulate_by_ref` covers the §7 "Person accumulation" invariant at the store level (multiple person rows share one `refs`).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_journal_hooks.py -q`
Expected: FAIL — `place`/`event` lists empty (`_mark_seen`/`inspect_item` not yet wired).

- [ ] **Step 3: Wire Hook 4 (first visit) in `_mark_seen`**

In `src/aidnd/server/play/engine/pc/hero.py`, add the import at the top of the module (with the other imports):

```python
from aidnd.server.play.engine.journal import j_place
```

Replace `_mark_seen` (`:176-181`):

```python
def _mark_seen(bid: str | None) -> None:
    """Fog of war: location becomes known (map marker) when player LEARNS it —
    came themselves or heard from people/info."""
    if bid and bid not in _seen():
        _S["seen"].add(bid)
        _store().flag_set(_wid(), f"seen|{bid}")
        from aidnd.server.play.engine.core import _binfo  # deferred: core imports hero (cycle)
        j_place(f"впервые вошёл в {_binfo(bid)['name']}", bid)
```

> `_binfo` is imported lazily inside the function because `core` imports `hero` (`_pc`), so a top-level `from …core import _binfo` in `hero.py` would form a load-time cycle. `j_place` (from `journal.py`, which imports only the session leaves) is cycle-free at top level.

- [ ] **Step 4: Wire Hook 5 (item reveal) in `inspect_item`**

In `src/aidnd/server/play/handlers/inventory.py`, add the import at the top of the module:

```python
from aidnd.server.play.engine.journal import j_event
```

In `inspect_item`, replace the known-set growth block (`:125-127`):

```python
    res = item_inspect(it, cap, via, observer=observer, known=known)
    known |= {h["prop"] for h in res["revealed"]} | set(res.get("attr_groups", []))
    _store().inv_set_known(_wid(), iid, known)
```

with:

```python
    known0 = set(known)                                        # snapshot BEFORE growth
    res = item_inspect(it, cap, via, observer=observer, known=known)
    known |= {h["prop"] for h in res["revealed"]} | set(res.get("attr_groups", []))
    _store().inv_set_known(_wid(), iid, known)
    new_attrs = known - known0                                 # what this inspection revealed
    if new_attrs:                                              # nothing new → no duplicate row
        j_event("saw", f"{it.get('name', 'предмет')}: открылось — "
                       f"{', '.join(sorted(new_attrs))}", refs=[iid])
```

- [ ] **Step 5: Wire Hook 3 (first meeting) in `talk`**

In `src/aidnd/server/play/handlers/dialogue.py`, add to the imports:

```python
from aidnd.server.play.engine.journal import j_person
```

and add `_binfo` to the existing `from …core import (…)` block (`:28-45`).

In `talk`, inside the existing `if first:` block (`:82-85`), after `_npc_save(npc)`, add:

```python
        place = (_binfo(_S.get("inside"))["name"] if _S.get("inside")
                 else ((_S.get("live") or {}).get("place") or ""))
        j_person("saw", f"встретил {p.name} — {p.role}, {place}", npc)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/play/test_journal_hooks.py -q`
Expected: PASS (5 tests). If `inspect_item`'s red phase reveals it needs a neighbour not present, note that `inv_mod._play` is stubbed to `(None, {}, None, None, None)`; adjust only the stub, not the assertions.

- [ ] **Step 7: Commit**

```bash
git add src/aidnd/server/play/handlers/dialogue.py src/aidnd/server/play/engine/pc/hero.py src/aidnd/server/play/handlers/inventory.py tests/play/test_journal_hooks.py
git commit -m "feat(play/journal): Hooks 3–5 — первая встреча (person/saw), первый вход (place/saw, без дублей), раскрытие предмета (event/saw при росте known)"
```

---

### Task 6: API — `GET /api/play/journal`

**Files:**
- Modify: `src/aidnd/server/play/handlers/misc.py:144-149` region (add endpoint after `deeds_list`)
- Test: `tests/play/test_journal_api.py` (create)

**Interfaces:**
- Consumes: `WorldStore.journal_list(world_id, kind=None, limit=200)` (Task 1); `_store()`/`_wid()` from `core` (local import, like `deeds_list`).
- Produces: `GET /api/play/journal?kind=&limit=` → `{"entries": [{"gt", "kind", "prov", "refs", "text"}]}` newest-first; `kind` filters; `limit` caps (hard ceiling 500).

- [ ] **Step 1: Write the failing test**

Create `tests/play/test_journal_api.py`:

```python
"""GET /api/play/journal: newest-first entries, kind filter, limit cap (misc.py pattern)."""

import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.handlers import misc as misc_mod
from aidnd.worldgen import WorldStore


@pytest.fixture
def wired(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(core, "_store", lambda: st, raising=False)
    monkeypatch.setattr(core, "_wid", lambda: 1, raising=False)
    monkeypatch.setattr(misc_mod, "_play", lambda: None, raising=False)
    st.journal_add(1, "event", "heard2", [], "… Марты …", 512)
    st.journal_add(1, "person", "saw", ["odo"], "встретил Одо", 513)
    st.journal_add(1, "quest", "told", ["ct:odo:1"], "взялся за дело", 514)
    return st


def test_entries_newest_first(wired):
    out = misc_mod.journal_endpoint()
    assert list(out.keys()) == ["entries"]
    assert [e["gt"] for e in out["entries"]] == [514, 513, 512]
    assert out["entries"][0]["kind"] == "quest" and out["entries"][0]["refs"] == ["ct:odo:1"]


def test_kind_filter(wired):
    out = misc_mod.journal_endpoint(kind="person")
    assert len(out["entries"]) == 1 and out["entries"][0]["refs"] == ["odo"]


def test_limit_caps_length(wired):
    assert len(misc_mod.journal_endpoint(limit=1)["entries"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_journal_api.py -q`
Expected: FAIL with `AttributeError: module 'aidnd.server.play.handlers.misc' has no attribute 'journal_endpoint'`.

- [ ] **Step 3: Add the endpoint**

In `src/aidnd/server/play/handlers/misc.py`, immediately after `deeds_list` (`:144-149`), add:

```python
@router.get("/api/play/journal")
def journal_endpoint(kind: str | None = None, limit: int = 200):
    """Player chronicle «Хроника»: journal rows newest-first (append-only capture; no LLM).
    Optional kind ∈ person|event|quest|place filter; limit hard-capped at 500."""
    _play()
    from aidnd.server.play.engine.core import _store, _wid
    return {"entries": _store().journal_list(_wid(), kind=kind, limit=min(int(limit), 500))}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/play/test_journal_api.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/aidnd/server/play/handlers/misc.py tests/play/test_journal_api.py
git commit -m "feat(play/journal): эндпоинт GET /api/play/journal — записи newest-first, фильтр kind, ограничение limit"
```

---

### Task 7: UI — `#journalpanel` (4 tabs, ✦/◐/◌ marks, People/Places grouped by refs)

**Files:**
- Modify: `src/aidnd/server/web/play.html` — new `#journalpanel` after `#magicpanel` (`:465`); `setView` map/toggle (`:642-647`); a top-bar opener (`:410`); a view-intent (`:654`); new `renderJournal()` + CSS.
- No pytest (frontend). Verification = the Task 6 API returning entries + a manual checklist.

**Interfaces:**
- Consumes: `GET /api/play/journal?kind=&limit=` (Task 6); the existing `setView(name)`, `$`, `api`, `esc` helpers (`play.html:569-582,637-648`).
- Produces: a working chronicle panel; `setView('journal')` toggles it; `renderJournal()` fills it.

- [ ] **Step 1: Add the panel markup**

In `src/aidnd/server/web/play.html`, immediately after the `#magicpanel` closing `</div>` (`:465`) and before the `</div>` that closes `.col.left` (`:466`), add:

```html
    <div id="journalpanel" class="workpanel">
      <div class="cap">&#10022; Хроника <span onclick="setView('explore')" style="cursor:pointer;color:var(--faint);float:right">✕</span></div>
      <div class="jtabs" id="jtabs">
        <button class="jtab on" data-k="event" onclick="jTab('event')">События</button>
        <button class="jtab" data-k="person" onclick="jTab('person')">Люди</button>
        <button class="jtab" data-k="quest" onclick="jTab('quest')">Дела</button>
        <button class="jtab" data-k="place" onclick="jTab('place')">Места</button>
      </div>
      <div class="jbody" id="jbody"></div>
    </div>
```

- [ ] **Step 2: Add the CSS**

In the `<style>` block of `play.html` (near the other `.workpanel` rules, e.g. after `:50`), add:

```css
  .jtabs{display:flex;gap:4px;padding:6px 12px;flex:0 0 auto}
  .jtab{background:none;border:1px solid var(--faint);color:var(--faint);border-radius:10px;padding:2px 10px;cursor:pointer;font-size:12px}
  .jtab.on{color:var(--gold);border-color:var(--gold)}
  .jbody{flex:1 1 auto;min-height:0;overflow:auto;padding:0 12px 12px}
  .jrow{padding:4px 0;border-bottom:1px solid rgba(255,255,255,.05);font-size:13px;line-height:1.4}
  .jmark{color:var(--gold);margin-right:6px}
  .jfrag{font-style:italic;color:var(--faint)}
  .jgrp{color:var(--gold);font-size:12px;margin:8px 0 2px}
  .jempty{color:var(--faint);padding:10px 0}
```

- [ ] **Step 3: Add the opener to the top bar**

In the top-bar `.right` span (`:410`), immediately before the `<a id="dbglog" …>` link, add:

```html
<a title="Хроника — что я видел, слышал, делал" style="color:var(--faint);text-decoration:none;cursor:pointer" onclick="setView('journal')">&#10022; хроника</a>
```

- [ ] **Step 4: Wire `setView` for `journal`**

In `setView` (`:642-647`), change the workpanel map and toggle list to include `journalpanel`, and refresh on open:

```javascript
    const wp={inv:'invpanel',magic:'magicpanel',journal:'journalpanel'}[name]||'mapwrap';  // which work panel fills the left column
    ['mapwrap','invpanel','magicpanel','journalpanel'].forEach(id=>{const e=$(id);if(e)e.classList.toggle('on',id===wp);});
```

and at the end of `setView` (after the `if(name==='inv')refreshInv();` line, `:647`), add:

```javascript
  if(name==='journal')renderJournal();
```

Also add `'journal'` to the Escape-closes-view guard (`:650`):

```javascript
  if(e.key==='Escape'&&(VIEW==='map'||VIEW==='inv'||VIEW==='magic'||VIEW==='journal')){setView('explore');e.preventDefault();}
```

- [ ] **Step 5: Add a view-intent (natural-language open)**

In the `VIEW_INTENTS` array (`:654`), add an entry:

```javascript
  {re:/(хроник|дневник|журнал|летопис|записк)/i, v:'journal', ack:'открываешь хронику'},
```

- [ ] **Step 6: Add `renderJournal()` + `jTab()`**

Near `renderJobs` (`:1257`), add:

```javascript
let JTAB='event';
const JMARK={saw:'✦',heard1:'◐',heard2:'◐',told:'◌'};   // ✦ ◐ ◐ ◌
function jTab(k){JTAB=k;document.querySelectorAll('.jtab').forEach(b=>b.classList.toggle('on',b.dataset.k===k));renderJournal();}
async function renderJournal(){
  const el=$('jbody');if(!el)return;
  const r=await api('/api/play/journal?kind='+encodeURIComponent(JTAB)+'&limit=400');
  const rows=(r.entries||[]);
  if(!rows.length){el.innerHTML='<div class="jempty">пока пусто — хроника пишется по ходу игры</div>';return;}
  const line=e=>{const m=JMARK[e.prov]||'';
    const t=e.prov==='heard2'?`<span class="jfrag">${esc(e.text)}</span>`:esc(e.text);
    return `<div class="jrow"><span class="jmark">${m}</span>${t}</div>`;};
  if(JTAB==='person'||JTAB==='place'){                       // group by refs-entity (newest-first within group)
    const seen=[],by={};
    rows.forEach(e=>{const k=(e.refs&&e.refs[0])||'—';if(!(k in by)){by[k]=[];seen.push(k);}by[k].push(e);});
    el.innerHTML=seen.map(k=>`<div class="jgrp">${esc(by[k][0].text.split(' — ')[0].replace(/^впервые вошёл в /,''))}</div>`
      +by[k].map(line).join('')).join('');
  }else{
    el.innerHTML=rows.map(line).join('');
  }
}
```

- [ ] **Step 7: Verify (no pytest — manual checklist)**

Run the API check first (fast, deterministic):

Run: `uv run pytest tests/play/test_journal_api.py -q`
Expected: PASS — confirms the panel's data source returns `{"entries":[…]}` newest-first with kind filtering.

Then a manual checklist (per spec §7 live-verify — do this against a running dev server if available):
- Open the app, click **✦ хроника** in the top bar (or type «хроника») → the `#journalpanel` fills the left column and the four tabs render.
- **События** lists event rows newest-first; a `heard2` fragment renders italic/faint (`.jfrag`) with its `…` ellipses; marks show ✦ for `saw`, ◐ for `heard1`/`heard2`.
- **Дела** shows quest rows with ◌ (told) / ✦ (saw).
- **Люди** / **Места** group rows under an entity header (the person's name / the place name).
- `Esc` returns to the scene; empty tabs show the «пока пусто» placeholder.

- [ ] **Step 8: Commit**

```bash
git add src/aidnd/server/web/play.html
git commit -m "feat(play/journal): панель #journalpanel — вкладки Люди/События/Дела/Места, метки ✦/◐/◌, группировка Люди/Места по refs"
```

---

### Task 8: Full-suite green gate

**Files:** none (verification only).

**Interfaces:** none.

- [ ] **Step 1: Run the whole suite**

Run: `uv run pytest tests -q`
Expected: PASS — the pre-quest baseline plus **+26 new** journal tests (store 4 + helper 6 + feed 6 + quests 2 + hooks 5 + api 3 = 26), 0 failed, ~2 min. Absolute total depends on execution order: on the `363` baseline it is `389`; if Inc 1 landed first (baseline `379`) it is `405`. Assert "+26 new, 0 failed", not the absolute number.

- [ ] **Step 2: If anything fails, fix inline**

Use `superpowers:systematic-debugging`. Common suspects: a hook fixture missing a stubbed neighbour (stub it, don't weaken the assertion); an `_S` left dirty between tests (each hook test calls `core._S.clear()` in its fixture); the lazy `PB` import path in `journal_add` (confirm `session/config.py` carries `journal_cap`).

- [ ] **Step 3: Commit only if a fix was needed**

```bash
git add -A
git commit -m "test(play/journal): зелёный прогон всего набора после интеграции хроники"
```

---

## Self-Review

**1. Spec coverage** — every §-requirement maps to a task:
- §4 table + `journal_add`/`journal_list` + cap-prune + `PB["journal_cap"]=2000` → **Task 1**.
- §3 helper `journal_add` funnel + no-op safety → **Task 2**.
- §3 Hook 1 (speech tier1/2 heard1/heard2, deed saw refs=[actor], tier3/murmur skip) + §5(a)(b)(c) + §7 epistemic-honesty/fidelity/unwitnessed → **Task 3**.
- §3 Hook 2 (pitch/accept told, complete saw, refs=[cid]) + §5(e) + §7 quest-beats-in-order → **Task 4**.
- §3 Hooks 3/4/5 + §5(d)(f) + §7 person-accumulation/first-visit-once/item-reveal-no-dup → **Task 5**.
- §3/§4 API `GET /api/play/journal` + §7 API-shape → **Task 6**.
- §3 `#journalpanel` (4 tabs, marks, grouping) + §5 tab table → **Task 7**.
- §7 full green + §5 boundary cases (cap-prune Task 1, unwitnessed Task 3, no-dup Tasks 3/5) → **Tasks 1/3/5/8**.

**2. Placeholder scan** — no `TBD`/`TODO`/"handle edge cases"/"similar to Task N"; every code step carries complete code; every test carries real assertions with concrete strings.

**3. Type consistency** — `journal_add(world_id, kind, prov, refs, text, gt)` / `journal_list(world_id, kind=None, limit=200)` and `j_event(prov, text, refs=None)` / `j_quest(prov, text, cid)` / `j_person(prov, text, pid)` / `j_place(text, bid)` / `journal_feed(feed)` are spelled identically in every task's interface block, code step, and test. `refs` is a `list` everywhere (JSON-encoded in the store, decoded on read). `journal_endpoint(kind=None, limit=200)` returns `{"entries":[…]}` consistently in Task 6 and the Task 7 UI fetch.
