# SIM-STITCHING «сшивка слоёв» — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stitch the passive city sim (ring B — `routine_step` relocates ~1354 residents every 30 game-min) to the player's live scene (ring A) so that people **arrive and leave the player's scene as visible, code-generated feed events**, venues have a **hard capacity with overflow**, town-crossing NPCs become **derived walkers the player can see pass on the street**, and a present NPC the routine moves **actually leaves** (no more pinning) — all with **zero new LLM calls**. The four seams close in four independently-green increments: **события** (who-diff → churn feed), **вместимость** (durable ledger + overflow), **транзит** (derived walkers), **анпин** (drop the pin + polite postpone).

**Architecture:** Four small edits to two hot paths plus two new in-memory `_S` structures. `engine/world.py` `_live_build` **diffs** the previous occupant set against the new one, classifies each joiner/leaver by **salience** (all real fields), and stashes `churn` feed items that `_live_tick` prepends to `feed`; the existing `scene_digest` narrates them — **no new LLM call** (Inc1). `engine/worldsim.py` `routine_step` gains a **durable load ledger** recomputed from `crof`+player, capacity-respecting commitments, and an **overflow chain** down same-kind venues (Inc2). A settled reassignment of ≥ `PB["transit_min_steps"]` nodes writes a **transit row** into `_S["transit"]` instead of an instant `crof` flip; `engine/core.py` `_here` becomes transit-aware (lazy flip at `arrive_gt`, mid-transit walkers surface at their derived node), while the rebuild trigger and scene-build read a **settled-only** view so brief walkers never thrash a rebuild (Inc3). Finally the `pin` parameter is **dropped** — present NPCs relocate, with a one-slot **polite postpone** for anyone mid-conversation with the player; departure events ride Inc1's diff, transit rides Inc3 (Inc4). Nothing new calls the LLM anywhere.

**Tech Stack:** Python 3, the play engine session dict `_S` (`engine/session/core` via `engine/core`), `PB` tunables in `engine/session/config.py`, `aidnd.society` routine/needs/places, `City.route` (graph A*), the existing `scene_digest` narrator seam, `WorldStore` (`contracts` for salience), pytest via `uv run pytest`. **No new table, no schema migration** — `_S["transit"]` and the ledger are pure functions of the durable `crof`, exactly like `crof`/`commit`/`crof_kind` already are.

## Global Constraints

- **No mechanical gates on NPC behavior.** Capacity is a **world constraint** (a room physically holds N), not a cooldown on any mind — a full venue reroutes via the missing world piece (overflow to the next real venue), the [[no-mechanical-gates]] pattern. The polite postpone is a **one-slot, bounded world rule** («не срывается на полуслове»), never a per-NPC timer that suppresses a decision. Minds are unchanged; no `_attempt` verb is added.
- **No LLM fallback.** Every increment is pure code (diff, `Counter`, node math, derivation). The only model call in the whole flow is the **pre-existing** `scene_digest` that already runs every non-empty-feed tick; there is no new LLM path, so no fallback and no canned stub is ever emitted. `NO_LLM_TICKS`/no-model still raise honestly to the player via the existing `_world_tick` handler (`loop/tick.py:45`).
- **Zero new LLM calls in this whole program.** Inc1/2/4 are pure code; Inc3 is pure derivation. A test in every increment asserts the churn/transit path invokes no model (the `scene_digest` call count is unchanged by churn).
- **Tunables in PB (`engine/session/config.py`).** `churn_named_max`, `overflow_max_hops`, `transit_min_steps`, `depart_postpone_slots` are added to `PB`; `step_min` (`config.py:19`) is reused. No literals scattered in the hot paths.
- **Russian commits** in the form `feat(play/sim): …` or `fix(play/sim): …`. **NEVER** add a `Co-Authored-By: Claude` trailer.
- **Test-fixture discipline (hard-learned):** snapshot/restore the session dict with `saved = dict(core._S._d()); d = core._S._d(); … d.clear(); d.update(saved)` in a `try/finally`; **AND** root-patch `session.persist._STORE` with `monkeypatch.setattr(persist, "_STORE", store)` (leaf resolvers `_store()`/`_wid()`/`_gt()` resolve lazily). Keep the lazy-import-inside-function pattern used across the play engine so `ruff` does not strip momentarily-unused imports.
- **Live playtest per increment** via the `/playtest` skill (haiku player-agent), then ship via the `/deploy` skill (autonomous prod deploy). Each increment is independently green and deployable.

---

## Settled decisions (spec §10 open questions + reading ambiguities — CLOSED)

- **Wound salience field path (DRIFT — see table).** The spec §4.3/§6 writes `p.state.hp < p.state.max_hp`, but `max_hp` lives on the **config**: `NpcState.hp` exists (`model.py:63`), `max_hp` is `NpcConfig.max_hp` (`model.py:35`). The predicate uses **`p.state.hp < p.state.config.max_hp`**. (Passive residents rarely drop below max — this signal mostly lies dormant, as §10 notes; guard/acquaintance/quest signals carry salience meanwhile.)
- **`предикт «в пути»` vs `crosses` unchanged (§10).** To honor §10 ("spec leaves `crosses` on the forecast path unchanged; only `_here` becomes transit-aware"), `predict`/`crosses` are **NOT** touched. The «в пути к X» answer is surfaced by a small **`transit_of(pid)`** helper read by the schedule card (`handlers/misc.py:76`), so a live transit row is reported without perturbing the forecast utility or ambush planning.
- **Transit walker is "en route", not "at origin".** While a transit row is live, `crof` still stores the walker's **origin** (restart-safe, §4.2), but every *here*-query treats the pid as **not settled anywhere** — a **settled** view is `crof`-occupants **minus** pids with a live transit row; the transit-aware `_here` adds them back at their **derived** node. This resolves the §5-C1 tension (a departing scene NPC who gets a transit row leaves the who-set **this slot**, so the departure event fires now) and prevents an origin double-count.
- **Rebuild trigger & scene-build read the settled view.** Per §3.3 ("`who` counts only settled occupants, never transit walkers"), the `tick.py:33/65` trigger, `_live_build`'s occupant enumeration, and Inc1's diff use a new **`_here_settled`**; transit-aware `_here` serves the street pass-through scan and `transit_of`. A brief walker crossing the player's street node surfaces only as a **pass-through feed line**, never as a scene occupant or a who-set member.
- **Churn diff gated to the same scene.** The who-diff runs **only when `prev.get("loc") == loc`** (occupant set changed within the same room). On a fresh location (player travelled) there is no churn — the digest already describes the new room; otherwise every first entry would flood as "joins".
- **Churn leads the feed.** `feed = live.pop("churn", []) + list(zone_feed)` — door events («вошла Мара») precede ambient hum, matching the §5-A prose and `scene_digest`'s nearest→farthest ordering.
- **Named churn uses the person's name directly** (`people[pid].name`), not `_display` — a salient joiner is by definition known/notable, and this keeps the diff a pure function (no `_S["live"].descr` dependency for unit tests).
- **Commitment-to-full → «у входа», not a phantom stack.** An appointment/commitment whose node is at cap does **not** flip `crof` into the full node this slot; `crof_kind[pid]` is labelled «у входа (ждёт)» and load is not incremented. Simplest honest option (§5 boundary "Committed venue full").
- **Overflow chain is proximity-ordered for `tavern`.** The local-pub selection already sorts by distance-to-home (`worldsim.py:97-98`); overflow walks that sorted list to the next non-full same-kind node, bounded by `overflow_max_hops`, then falls back to a `street` candidate (always node-available). `temple`/`market` keep their single hashed node (no second instance to overflow to in practice).

---

## Drift found vs. the spec's file:line snapshot (re-verified against HEAD `96e7958`)

The spec was authored at HEAD `96e7958` (the same commit these anchors are re-verified against). All worldsim/core/contracts anchors are exact; the drift is confined to two field-path / path-prefix items and one off-by-one, plus one existing test file the plan must rewrite.

| Spec anchor | HEAD | Status |
|---|---|---|
| `worldsim.py:208` `routine_step`, `:251` `load={}`, `:253` order, `:255` pin-skip, `:277-281` place | **exact** at all five | ✅ exact |
| `worldsim.py:61-68` `_building_cap`, `:101-104` cap-skip in `_candidates`, `:266-269` commit bypass | **exact** | ✅ exact |
| `worldsim.py:134` `predict`, `:161` `city.route`, `:171` `crosses` | **exact** | ✅ exact |
| `core.py:243` `_here(node, spot)` (pure `crof` comprehension) | **`core.py:243`** | ✅ exact |
| `world.py:363` `_live_build`, `:429` `here_all` (no-LOD comment), `:1090` `feed, address = list(zone_feed), []` | **exact** | ✅ exact |
| `world.py:576` `"who": frozenset(here)` | **`world.py:575`** (`here` defined `:529`) | ⚠️ off-by-one (575) |
| `loop/tick.py:33` rebuild trigger, `:55` `_world_tick_fast` (`:65` its trigger) | **`engine/loop/tick.py:33` / `:55` / `:65`** | ⚠️ path prefix: `engine/loop/`, not `loop/`; lines exact |
| `loop/routine.py:61` routine-key, `:82` `routine_step(…, pin=set(_here(…)))` | **`engine/loop/routine.py:61` / `:82`** | ⚠️ path prefix: `engine/loop/`; lines exact |
| `scene_digest.py:56` | **`narrator/scene_digest.py`**: `def scene_digest` `:51`, `_model().call` `:59`, feed consumed by `_event_lines` `:35-47` (`{k:"deed", who, text}` → `- действие/звук: {who}: {text}`) | ⚠️ digest call at `:59` (`:56` is inside the fn); feed-shape compat confirmed exact |
| `contracts.py:243` `ct["giver"]`, `:286` `ct["target"]`; `contracts(wid, status)` | **`:243` `"giver": npc`, `:286` `"target": ct.get("target")`**; `store.py:399 contracts(world_id, status=None)` | ✅ exact |
| §4.3 salience `p.state.hp < p.state.max_hp` | **`p.state.hp` exists (`model.py:63`); `max_hp` is `NpcConfig.max_hp` (`model.py:35`)** — no `state.max_hp` attr | ❗ **field path wrong** — use `p.state.hp < p.state.config.max_hp` |
| `config.py:19` `PB["step_min"]=1` (reused), `PB` `:16` | **`config.py:19` / `:16`** | ✅ exact |
| `_S["cr2b"]` node→bid (spec calls it `n2b` locally, built `worldsim.py:249` `n2b = _S.get("cr2b")`) | **`world.py:363` param `cr2b`; `worldsim.py:249`** | ✅ exact (two names, one map) |

**Test drift (the important one):** `tests/play/test_pin.py` exercises the exact `pin` behaviour Inc4 removes — `test_apply_routine_pins_present` (asserts `_apply_routine` passes the present-set as `pin`) and `test_routine_step_skips_pinned` (asserts a pinned NPC is not moved). **Inc4 rewrites this file** to the unpin + postpone contract. Baseline: **`uv run pytest tests -q --co` → 586 tests**.

---

## File structure

- **Modify `src/aidnd/server/play/engine/world.py`** — Inc1: add `_salient`, `_ru_count`, `_churn_items`; wire the diff into `_live_build` (after `prev` is read, `:555`) stashing `live["churn"]`; prepend churn in `_live_tick` (`:1090`). Inc3: repoint the three occupant-enumeration sites (`:415` `known_by`, `:429` `here_all`, `:529` `here`) to `_here_settled`; add the street pass-through scan in `_live_tick`.
- **Modify `src/aidnd/server/play/engine/core.py`** — Inc3: add `_here_settled`; make `_here` transit-aware (lazy flip + mid-transit walkers). `_transit_node` imported from worldsim.
- **Modify `src/aidnd/server/play/engine/worldsim.py`** — Inc2: durable ledger (replace `:251`), overflow in `_candidates` (`:101-104` region), commitment cap (`:266-269`). Inc3: `_transit_node`, `transit_of`, transit-row write at the `crof` flip (`:277-278`). Inc4: drop the `pin` param + `:255` skip; add the postpone guard.
- **Modify `src/aidnd/server/play/engine/loop/tick.py`** — Inc3: `_here` → `_here_settled` in both rebuild triggers (`:33`, `:65`).
- **Modify `src/aidnd/server/play/engine/loop/routine.py`** — Inc4: `routine_step(_S["people"], _S["crof"])` (drop `pin=…`, `:82`).
- **Modify `src/aidnd/server/play/handlers/misc.py`** — Inc3: schedule card (`:76`) prefers `transit_of(npc)` → «в пути к X».
- **Modify `src/aidnd/server/play/engine/session/config.py`** — add the four PB keys (`:16` block).
- **Tests:** add `tests/play/test_churn_events.py` (Inc1), `tests/play/test_capacity_overflow.py` (Inc2), `tests/play/test_transit.py` (Inc3); **rewrite** `tests/play/test_pin.py` → `test_unpin_postpone` content (Inc4).

### Seam quick-reference (verified `file:line` at HEAD)

- `worldsim.py:208` `routine_step(people, crof, pin=None)`; `:249` `n2b = _S.get("cr2b")`; `:251` `load: dict = {}`; `:253` `order = sorted(people.items(), key=…work is None…)`; `:255` `if pin and pid in pin: continue`; `:266` `cnode = appts.get(pid) or _commit_node(…)`; `:277-281` `crof[pid]=node; kind_of[pid]=akind; … load[node]+=1`.
- `worldsim.py:61` `_building_cap(bid)` (Σ social-zone caps, min 6, dflt 14); `:79 _candidates(p, place_idx, keynode, kps, rng, work_kinds, load, n2b, xy)`; `:94-105` tavern/temple/market branch (cap-skip `:101-104`); `:134 predict`; `:161 city.route(cur, node)` → `.nodes`/`.found`.
- `core.py:243` `_here(node, spot) -> [pid for pid,s in spot.items() if s==node]`; `_gt`/`_S` imported at top; `_display` `:371`.
- `world.py:363 _live_build(city, people, crof, cr2b, loc)`; `:415 known_by`, `:429 here_all`, `:529 here` (all `_here(loc, crof)`); `:555 prev = _S.get("live") or {}`; `:567 _S["live"] = {…}`, `:575 "who": frozenset(here)`; `:813 _live_tick(people)`; `:875 zone_feed = []`; `:1090 feed, address = list(zone_feed), []`.
- `loop/tick.py:33` `if not lv or lv["loc"] != loc or lv.get("who") != frozenset(_here(loc, crof)): _live_build(…)`; `:44` `scene_digest(feed, …)`; `:65` same trigger in `_world_tick_fast`.
- `loop/routine.py:82` `routine_step(_S["people"], _S["crof"], pin=set(_here(_S["loc"], _S["crof"])))`.
- `store.py:399 contracts(world_id, status=None) -> [{id, status, **data}]` (data carries `giver`, `target`, `giver_name`, `kind`, `want`, `where`, `reward`).
- `narrator/scene_digest.py:51 scene_digest(feed, place)`; `_event_lines` `:35` renders `{k:"deed", who, text}` as `- действие/звук: {who}: {text}` — churn items ride this shape unchanged.
- `config.py:16 PB = {…}`, `:19 "step_min": 1`.
- session leaf resolvers: `core._S`, `core._gt`, `core._store`, `core._wid`, `core.PLAYER`; `session.persist._STORE` is the root patch target.

---

# INCREMENT 1 — события (who-diff → churn feed)

`_live_build` diffs the previous occupant set against the new one; salient joiners/leavers become **named** feed items (`churn_named_max` per direction), the rest collapse into **one summary line** with a RU numeral; `_live_tick` prepends them; `scene_digest` narrates — zero new LLM. **No pin change yet** (Inc4). Ships the churn machinery.

---

## Task 1: salience + churn helpers, wired into the scene diff

**Files:**
- Modify: `src/aidnd/server/play/engine/session/config.py:16` (add `churn_named_max`)
- Modify: `src/aidnd/server/play/engine/world.py` (add `_salient`/`_ru_count`/`_churn_items`; wire into `_live_build` after `:555`; prepend in `_live_tick` `:1090`)
- Test: `tests/play/test_churn_events.py`

**Interfaces:**
- `_salient(pid, people, active_givers: set, active_targets: set) -> bool` — `PLAYER ∈ p.state.relationships` OR `pid ∈ active_givers` OR `pid ∈ active_targets` OR `p.role == "стражник"` OR `p.state.hp < p.state.config.max_hp`.
- `_ru_count(n: int) -> str` — `двое/трое/четверо/пятеро/шестеро`, fallback «N человек».
- `_churn_items(prev_who, here, people, active_givers, active_targets) -> list[dict]` — named items (capped `PB["churn_named_max"]` per direction) + one summary per non-empty direction; each `{"k":"deed", "who":…, "text":…}` (named also carry `"pid"`).

- [ ] **Step 1: add the PB tunable**

In `src/aidnd/server/play/engine/session/config.py`, inside the `PB = {` block (near `:19`, next to `step_min`), add:

```python
    # sim-stitching (docs/superpowers/plans/2026-07-14-sim-stitching.md)
    "churn_named_max": 2,       # max NAMED join/leave feed items per direction per tick; rest → summary
```

- [ ] **Step 2: write the failing test**

```python
# tests/play/test_churn_events.py
"""Inc1 — scene churn as feed events. Pure-function unit tests over _salient / _churn_items:
salient joiners are NAMED (capped by churn_named_max), the rest collapse into one summary line per
direction; an empty diff yields no items. No LLM, no session mutation beyond a snapshot restore."""
from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core
from aidnd.server.play.engine.core import PLAYER
from aidnd.server.play.engine.world import _churn_items, _ru_count, _salient


def _npc(pid, name, role="горожанин", knows_player=False, hp=None):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    if knows_player:
        st.relationships[PLAYER] = {"trust": 0.2, "affinity": 0.3, "fear": 0.0}
    if hp is not None:
        st.hp = hp
    return SimpleNamespace(id=pid, name=name, role=role, state=st, work=None, home=None, persona={})


def _people(*npcs):
    return {n.id: n for n in npcs}


def test_salient_by_each_signal():
    ppl = _people(
        _npc("p_ac", "Мара", knows_player=True),          # acquaintance
        _npc("p_gv", "Роза", role="лавочник"),            # giver (via set)
        _npc("p_tg", "Тор", role="кузнец"),               # contract target (via set)
        _npc("p_guard", "Гром", role="стражник"),         # guard
        _npc("p_hurt", "Пал", hp=3),                      # wounded (hp<max, default max 10)
        _npc("p_bg", "Йорг"),                             # plain civilian
    )
    givers, targets = {"p_gv"}, {"p_tg"}
    assert _salient("p_ac", ppl, givers, targets)
    assert _salient("p_gv", ppl, givers, targets)
    assert _salient("p_tg", ppl, givers, targets)
    assert _salient("p_guard", ppl, givers, targets)
    assert _salient("p_hurt", ppl, givers, targets)
    assert not _salient("p_bg", ppl, givers, targets)


def test_empty_diff_no_items():
    who = frozenset({"a", "b"})
    assert _churn_items(who, who, _people(_npc("a", "A"), _npc("b", "B")), set(), set()) == []


def test_five_joins_two_salient_two_named_plus_summary():
    # 5 join, 2 salient (acquaintance + giver), 3 background → 2 named + 1 summary «вошли трое»
    ppl = _people(
        _npc("host", "Гром", role="трактирщик"),          # already present
        _npc("p_mara", "Мара", knows_player=True),
        _npc("p_roza", "Роза Медовар", role="лавочник"),
        _npc("p_yorg", "Йорг"), _npc("p_pal", "Пал"), _npc("p_tim", "Тим"),
    )
    prev = frozenset({"host"})
    here = frozenset({"host", "p_mara", "p_roza", "p_yorg", "p_pal", "p_tim"})
    items = _churn_items(prev, here, ppl, {"p_roza"}, set())
    named = [i for i in items if i.get("pid")]
    summary = [i for i in items if not i.get("pid")]
    assert {i["who"] for i in named} == {"Мара", "Роза Медовар"}   # 2 named (== churn_named_max)
    assert len(summary) == 1                                        # one arrival summary
    assert _ru_count(3) in summary[0]["text"]                       # «трое»
    assert all(i["k"] == "deed" for i in items)                    # feed-shape compat (scene_digest)


def test_leavers_symmetric_summary():
    ppl = _people(_npc("host", "Гром"), _npc("p_vit", "Витольд"), _npc("p_x", "Икс"))
    prev = frozenset({"host", "p_vit", "p_x"})
    here = frozenset({"host"})                                     # two left, neither salient
    items = _churn_items(prev, here, ppl, set(), set())
    assert len(items) == 1 and items[0].get("pid") is None
    assert _ru_count(2) in items[0]["text"]                        # «зал редеет — вышли двое»


def test_named_cap_folds_extra_salient_into_summary():
    # 3 salient joiners, churn_named_max=2 → 2 named + summary counting the 3rd
    ppl = _people(
        _npc("host", "Гром"),
        _npc("g1", "Роза", role="лавочник"), _npc("g2", "Тор", role="кузнец"),
        _npc("g3", "Влас", role="писарь"),
    )
    prev = frozenset({"host"})
    here = frozenset({"host", "g1", "g2", "g3"})
    items = _churn_items(prev, here, ppl, {"g1", "g2", "g3"}, set())
    named = [i for i in items if i.get("pid")]
    summary = [i for i in items if not i.get("pid")]
    assert len(named) == 2 and len(summary) == 1
```

- [ ] **Step 3: run test to verify it fails**

Run: `uv run pytest tests/play/test_churn_events.py -q`
Expected: FAIL — `ImportError: cannot import name '_salient' from '…world'`.

- [ ] **Step 4: add the three helpers to `world.py`**

Add near the other module-level scene helpers (e.g. just above `_live_build`, `:362`). `PLAYER` and `PB` are already imported at the top of `world.py` (`:19-26`, and `PB` from core).

```python
_RU_COUNT = {1: "один", 2: "двое", 3: "трое", 4: "четверо", 5: "пятеро", 6: "шестеро"}


def _ru_count(n: int) -> str:
    """Small RU count word for the churn summary; fallback «N человек» past шестеро."""
    return _RU_COUNT.get(n, f"{n} человек")


def _salient(pid, people, active_givers: set, active_targets: set) -> bool:
    """Is this joiner/leaver worth a NAMED churn line? All signals are real fields (no invention):
    acquaintance (PLAYER∈relationships, same signal as _live_build known_by), an active/offered
    contract's giver or target, a guard, or a wounded person. NB: max_hp lives on the CONFIG
    (NpcState has no max_hp attr)."""
    p = people.get(pid)
    if p is None:
        return False
    st = p.state
    return (
        PLAYER in st.relationships
        or pid in active_givers
        or pid in active_targets
        or p.role == "стражник"
        or st.hp < st.config.max_hp
    )


def _churn_items(prev_who, here, people, active_givers: set, active_targets: set) -> list[dict]:
    """Diff prev occupant set vs new → feed items: NAMED for salient (capped churn_named_max per
    direction), the rest folded into ONE summary line per non-empty direction. Feed shape
    {k:'deed', who, text} — exactly what scene_digest._event_lines consumes. Pure; no LLM."""
    prev_s, here_s = set(prev_who or ()), set(here or ())
    joined = [p for p in (here_s - prev_s) if p in people]
    left = [p for p in (prev_s - here_s) if p in people]
    cap = PB["churn_named_max"]
    out: list[dict] = []
    for pids, arriving in ((joined, True), (left, False)):
        if not pids:
            continue
        sal = [q for q in pids if _salient(q, people, active_givers, active_targets)]
        named = sal[:cap]
        for q in named:
            verb = "вошёл(ла) в зал" if arriving else "поднялся(лась) и вышел(ла)"
            hint = ", ищет тебя взглядом" if (q in active_givers and arriving) else ""
            out.append({"k": "deed", "who": people[q].name, "pid": q,
                        "text": f"{verb}{hint}"})
        rest = len(pids) - len(named)                     # background + salient over the cap
        if rest > 0:
            phrase = (f"народ прибывает — вошли {_ru_count(rest)}" if arriving
                      else f"зал редеет — вышли {_ru_count(rest)}")
            out.append({"k": "deed", "who": "зал", "text": phrase})
    return out
```

- [ ] **Step 5: run test to verify it passes**

Run: `uv run pytest tests/play/test_churn_events.py -q`
Expected: PASS (5 tests).

- [ ] **Step 6: wire the diff into `_live_build`**

In `src/aidnd/server/play/engine/world.py`, after `prev = _S.get("live") or {}` (`:555`) and before the `_S["live"] = {…}` assembly (`:567`), compute the churn (gated to the same scene). Use `here` (the settled occupant list built at `:529`):

```python
    prev = _S.get("live") or {}
    # ── Inc1: churn as feed events — diff prev occupant set vs now (same scene only) ──
    churn: list = []
    if prev.get("loc") == loc and prev.get("who"):
        cs = _store().contracts(_wid(), "active") + _store().contracts(_wid(), "offered")
        givers = {c["giver"] for c in cs if c.get("giver")}
        targets = {c["target"] for c in cs if c.get("target")}
        churn = _churn_items(prev["who"], frozenset(here), people, givers, targets)
```

Then add `"churn": churn,` to the `_S["live"] = {…}` dict literal (alongside `"who": frozenset(here),` at `:575`):

```python
        "who": frozenset(here),
        "churn": churn,          # Inc1: prepended to the feed by _live_tick, narrated by scene_digest
```

- [ ] **Step 7: prepend churn in `_live_tick`**

At `world.py:1090`, replace `feed, address = list(zone_feed), []` with:

```python
    feed, address = _S["live"].pop("churn", []) + list(zone_feed), []   # Inc1: door events lead the feed
```

(`lv` is `_S["live"]`; `pop` consumes the stash so it narrates once. The existing `scene_digest` call at `loop/tick.py:44` weaves it — no digest change.)

- [ ] **Step 8: full-suite gate + no-new-LLM check**

Run: `uv run pytest tests -q`
Expected: PASS — 586 baseline + 5 new = 591, zero regressions (churn is additive; `scene_digest` is unchanged and only runs when the feed is non-empty, exactly as before).

Run: `uv run pytest tests/play/test_scene_digest.py -q`
Expected: PASS — the digest still consumes `{k:"deed", who, text}` items unchanged.

- [ ] **Step 9: commit**

```bash
git add src/aidnd/server/play/engine/world.py \
        src/aidnd/server/play/engine/session/config.py \
        tests/play/test_churn_events.py
git commit -m "feat(play/sim): события входа/выхода — who-diff в _live_build, именованные + сводка (churn), zero new LLM"
```

---

## Inc1 close — playtest + deploy

- [ ] **Live playtest** (`/playtest` skill): drop the haiku player-agent into a tavern and **sit for ~5 ticks** across an evening. Verify:
  - the scene digest narrates **arrivals** as prose — a named acquaintance/quest-giver «вошла в зал», background crowd as one «народ прибывает — вошли трое» beat;
  - a still room (no occupant change) narrates **no** churn — no spam;
  - the per-tick model-call count is unchanged (churn adds none — only the pre-existing digest runs). Quote the digest line narrating an arrival in the playtest note.
- [ ] **Deploy** (`/deploy` skill): once green and the playtest reads right, ship to prod (commit already made; the skill pushes `origin main` + `git reset --hard` + restart systemd `aidnd`, verifies `active`). No `Co-Authored-By` trailer.

---

# INCREMENT 2 — вместимость (durable ledger + overflow)

The `load` ledger is recomputed **from `crof` for all residents + the player** at the top of `routine_step` (counts pinned/scene NPCs the per-call reset ignored); a full venue routes the mover down an **overflow chain** to the next same-kind node (bounded `overflow_max_hops`, then `street`); commitments/appointments respect capacity («у входа», no phantom stack). Bounds the 134-душ spikes. Pure code; unit-tested.

---

## Task 2: durable-from-crof ledger + overflow chain + commitment cap

**Files:**
- Modify: `src/aidnd/server/play/engine/session/config.py:16` (add `overflow_max_hops`)
- Modify: `src/aidnd/server/play/engine/worldsim.py` (ledger `:251`; overflow in `_candidates` `:94-105`; commitment cap `:266-281`)
- Test: `tests/play/test_capacity_overflow.py`

**Interfaces:**
- Ledger: `load = Counter(crof.values()); load[_S["loc"]] += 1` at the top of `routine_step` (replaces the empty `load = {}` at `:251`); per-slot placements still `load[node] += 1` (`:281`) so later movers see the filling venue.
- Overflow: `_candidates`' tavern/temple/market branch, given `load`+`n2b`, returns the **next non-full** same-kind node (proximity order for tavern), skipping up to `PB["overflow_max_hops"]` full ones; if none free within the chain, offers **no** venue candidate of that kind (mover falls back to `street`, always node-available).
- Commitment cap: a `cnode` (appt/commit) at/over cap is **not** flipped into; `crof_kind[pid]` = «у входа (ждёт)», `crof` unchanged, load not incremented.

- [ ] **Step 1: add the PB tunable**

`config.py` PB block, under the sim-stitching comment:

```python
    "overflow_max_hops": 2,     # full venue → try this many next same-kind candidates before street
```

- [ ] **Step 2: write the failing test**

```python
# tests/play/test_capacity_overflow.py
"""Inc2 — hard capacity + overflow. The load ledger counts EVERYONE (incl. pinned + player), a full
venue overflows to the next same-kind node, an exhausted chain falls back to street, and the player
is counted but never a mover (never blocked). No LLM."""
import os
import tempfile
from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core, worldsim
from aidnd.server.play.engine import world as W
from aidnd.server.play.engine.core import PLAYER, PB
from aidnd.server.play.engine.session import persist


def _mover(pid, home):
    st = NpcState.from_config(NpcConfig(id=pid, name=pid, role="горожанин"))
    return SimpleNamespace(id=pid, name=pid, role="горожанин", state=st, work=None, home=home,
                           persona={}, keys=[])


@pytest.fixture
def world(monkeypatch):
    from aidnd.worldgen import WorldStore
    monkeypatch.setattr(persist, "_STORE", WorldStore(os.path.join(tempfile.mkdtemp(), "live.db")))
    core._S["city"] = None
    W._play()
    core._S["gt"] = 20 * 60
    return core._S


def test_candidates_overflow_to_next_same_kind_when_full(monkeypatch):
    # two taverns; nearest (47) is full → candidate is the next one (63), not skipped entirely
    p = _mover("p1", home=10)
    place_idx = {"tavern": [47, 63]}
    n2b = {47: "tav1", 63: "tav2"}
    xy = {10: (0, 0), 47: (1, 1), 63: (5, 5)}
    monkeypatch.setattr(worldsim, "_building_cap", lambda bid: 8)
    load = {47: 8}                                   # 47 at cap
    cands = worldsim._candidates(p, place_idx, {}, [10, 47, 63], __import__("random").Random(1),
                                 work_kinds={}, load=load, n2b=n2b, xy=xy)
    tav = [c for c in cands if c.kind == "tavern"]
    assert tav and tav[0].node == 63                 # overflowed to the second tavern


def test_candidates_no_venue_when_chain_exhausted(monkeypatch):
    p = _mover("p1", home=10)
    place_idx = {"tavern": [47, 63]}
    n2b = {47: "tav1", 63: "tav2"}
    xy = {10: (0, 0), 47: (1, 1), 63: (5, 5)}
    monkeypatch.setattr(worldsim, "_building_cap", lambda bid: 8)
    load = {47: 8, 63: 8}                             # both full
    cands = worldsim._candidates(p, place_idx, {}, [10, 47, 63], __import__("random").Random(1),
                                 work_kinds={}, load=load, n2b=n2b, xy=xy)
    assert [c for c in cands if c.kind == "tavern"] == []   # no tavern → mover falls to street/home
    assert any(c.kind == "street" for c in cands)


def test_ledger_counts_pinned_and_player(world):
    # seed a full venue in crof (pinned scene NPCs included) → a mover targeting it must NOT stack
    crof = core._S["crof"]
    core._S["loc"] = 47
    for i in range(8):
        crof[f"seed{i}"] = 47                          # 8 already at node 47 (some are 'present')
    from collections import Counter
    ledger = Counter(crof.values())
    ledger[core._S["loc"]] += 1                        # + the player
    assert ledger[47] >= 9                             # everyone counted, incl. the player


def test_player_is_never_a_mover(world):
    # routine_step iterates people only; PLAYER is not in people → never placed, never blocked
    worldsim.routine_step(core._S["people"], core._S["crof"])
    assert PLAYER not in core._S["people"]
    assert PLAYER not in core._S["crof"]               # ring B never writes the player's node
```

- [ ] **Step 3: run test to verify it fails**

Run: `uv run pytest tests/play/test_capacity_overflow.py -q`
Expected: FAIL — `test_candidates_overflow_to_next_same_kind_when_full` fails: current `_candidates` (`:101-104`) `continue`s past a full node instead of walking to the next same-kind one.

- [ ] **Step 4: overflow in `_candidates` (`worldsim.py:94-105`)**

Replace the `for kind in ("tavern", "temple", "market"):` branch (`:94-105`) with an overflow-aware version. `PB` is imported into `worldsim` via `core`? — add `from aidnd.server.play.engine.core import PB` to the top import (`:28` already imports `_S, _gt, _phase, _store, _wid`; extend it with `PB`).

```python
    for kind in ("tavern", "temple", "market"):  # tied to buildings places
        nodes = place_idx.get(kind)
        if nodes and _gate_ok(kind, p):
            if kind == "tavern" and xy and home in xy:   # local pub — nearest first, then overflow out
                ordered = sorted(nodes, key=lambda n: _sqd(xy, home, n))
            else:
                ordered = [nodes[hash((p.state.config.id, kind)) % len(nodes)]]
            node = ordered[0]
            if load is not None and n2b is not None:     # capacity: walk to the next non-full venue
                node = None
                for cand in ordered[:1 + PB["overflow_max_hops"]]:
                    bid = n2b.get(cand)
                    if bid and load.get(cand, 0) >= _building_cap(bid):
                        continue                          # full — try the next same-kind node
                    node = cand
                    break
            if node is not None:
                out.append(society.Candidate(kind, node))
```

- [ ] **Step 5: durable ledger (`worldsim.py:251`)**

Replace `load: dict = {}` (`:251`) with the recompute-from-crof ledger (add `from collections import Counter` at the top of the module, near `import random` `:25`):

```python
    load: dict = Counter(crof.values())               # durable: every resident (incl. pinned/scene)
    ploc = _S.get("loc")
    if ploc is not None:
        load[ploc] = load.get(ploc, 0) + 1            # + the player (counted, never a mover — §6)
```

> Note: placements inside the loop still `load[node] += 1` (`:280-281`) so later movers in the same slot see the venue filling. The ledger is not persisted — it is a pure function of the durable `crof`, correct after any restart.

- [ ] **Step 6: commitment respects capacity (`worldsim.py:266-281`)**

In the loop, where a commitment/appointment node is chosen (`cnode`, `:266-269`), refuse to phantom-stack a full venue. Replace the `if cnode is not None:` block so a full `cnode` yields the «у входа» outcome instead of a placement:

```python
        cnode = appts.get(pid) or _commit_node(pid, phase, people, crof)  # commitment?
        if cnode is not None:                         # override: meeting place/shift/after player
            cbid = n2b.get(cnode)
            if cbid and load.get(cnode, 0) >= _building_cap(cbid):
                kind_of[pid] = "у входа (ждёт)"        # venue full — waits outside, not stacked (§5)
                last[pid] = gt
                continue                               # crof unchanged this slot; load not bumped
            node, akind = cnode, ((_S.get("commit") or {}).get(pid, {}).get("kind")
                                  or "appointment")
        else:
```

(The regular `choose` path already honours capacity via the overflow-aware `_candidates`.)

- [ ] **Step 7: run tests to verify they pass**

Run: `uv run pytest tests/play/test_capacity_overflow.py -q`
Expected: PASS (4 tests).

- [ ] **Step 8: full-suite gate**

Run: `uv run pytest tests -q`
Expected: PASS — 591 + 4 = 595, zero regressions (`test_pin.py` still green — `pin` is untouched until Inc4; the ledger only tightens NPC routing).

- [ ] **Step 9: commit**

```bash
git add src/aidnd/server/play/engine/worldsim.py \
        src/aidnd/server/play/engine/session/config.py \
        tests/play/test_capacity_overflow.py
git commit -m "feat(play/sim): жёсткая вместимость — прочный ledger из crof+игрок, перелив по цепочке, обязательства «у входа»"
```

---

## Inc2 close — playtest + deploy

- [ ] **Live playtest** (`/playtest`): sit in a small tavern (low `_building_cap`) across a busy evening and confirm the room **stops filling past its cap** — no 134-душ pile-up; latecomers are routed elsewhere (they simply don't appear). Cross-check the scene «душ=N» debug log (`world.py:601`) stays ≤ cap for the player's venue.
- [ ] **Deploy** (`/deploy`): ship to prod, verify systemd `aidnd` active.

---

# INCREMENT 3 — транзит (derived walkers)

A cross-town reassignment writes a **transit row** into `_S["transit"]` instead of an instant `crof` flip; position is **derived on demand** (`_transit_node`, O(1)); `_here` becomes transit-aware (lazy flip at `arrive_gt`, mid-transit walkers at their derived node) while the rebuild trigger / scene-build read a **settled-only** `_here_settled`; a street scene shows walkers as **pass-through** feed lines; `transit_of` answers «в пути к X». Adds motion you can see. Pure derivation, zero ticking.

---

## Task 3: transit rows, derived position, transit-aware `_here` + settled split, pass-through

**Files:**
- Modify: `src/aidnd/server/play/engine/session/config.py:16` (add `transit_min_steps`)
- Modify: `src/aidnd/server/play/engine/worldsim.py` (`_transit_node`, `transit_of`; transit-row write at the `crof` flip `:277-278`)
- Modify: `src/aidnd/server/play/engine/core.py` (`_here_settled`; transit-aware `_here` `:243`)
- Modify: `src/aidnd/server/play/engine/loop/tick.py:33,65` (`_here` → `_here_settled` in both triggers)
- Modify: `src/aidnd/server/play/engine/world.py` (`:415/:429/:529` → `_here_settled`; street pass-through in `_live_tick`)
- Modify: `src/aidnd/server/play/handlers/misc.py:76` (schedule card → `transit_of`)
- Test: `tests/play/test_transit.py`

**Interfaces:**
- `_S["transit"]: dict[str, dict]` — `{pid: {"from", "to", "depart_gt", "arrive_gt", "path"}}`.
- `worldsim._transit_node(row, gt) -> int` — `to` if `gt ≥ arrive_gt`, else `path[min((gt-depart_gt)//PB["step_min"], len(path)-1)]`.
- `worldsim.transit_of(pid) -> dict | None` — `{"node", "to", "kind": "в пути"}` from a live row (else `None`).
- `core._here_settled(node, spot) -> list` — lazy-flips arrived rows into `spot` + deletes them, then returns `crof`-occupants at `node` **minus** any pid with a live transit row (settled only).
- `core._here(node, spot) -> list` — `_here_settled` result **plus** mid-transit walkers whose `_transit_node == node`.

- [ ] **Step 1: add the PB tunable**

`config.py` PB block:

```python
    "transit_min_steps": 3,     # reassignment shorter than this many nodes = instant crof flip (no walker)
```

- [ ] **Step 2: write the failing test**

```python
# tests/play/test_transit.py
"""Inc3 — transit as derived state. A short hop is an instant crof flip; a long hop writes a transit
row and defers the flip to arrive_gt. _transit_node derives position O(1); _here is transit-aware
(mid-transit at the derived node; lazy flip on arrival) while _here_settled excludes walkers so a
venue who-set is unaffected. A street scene sees a pass-through walker. No LLM."""
from aidnd.server.play.engine import core, worldsim
from aidnd.server.play.engine.core import _here, _here_settled
from aidnd.server.play.engine.session.config import PB


def _reset():
    d = core._S._d()
    saved = dict(d)
    d.clear()
    d.update(gt=21360, transit={})
    return saved, d


def test_transit_node_derivation_at_three_timestamps():
    row = {"from": 12, "to": 47, "depart_gt": 21360, "arrive_gt": 21365,
           "path": [12, 19, 26, 33, 40, 47]}
    assert worldsim._transit_node(row, 21360) == 12          # step 0
    assert worldsim._transit_node(row, 21362) == 26          # step 2 (step_min=1)
    assert worldsim._transit_node(row, 21365) == 47          # arrived → destination
    assert worldsim._transit_node(row, 99999) == 47          # clamped past the end


def test_here_transit_aware_and_lazy_flip():
    saved, d = _reset()
    try:
        crof = {"p_mara": 12}                                # origin still in crof
        d["crof"] = crof
        d["transit"] = {"p_mara": {"from": 12, "to": 47, "depart_gt": 21360, "arrive_gt": 21365,
                                   "path": [12, 19, 26, 33, 40, 47]}}
        d["gt"] = 21362
        assert "p_mara" in _here(26, crof)                   # mid-transit: at derived node 26
        assert "p_mara" not in _here(47, crof)               # not yet at destination
        assert _here_settled(12, crof) == []                 # settled view: NOT at origin (en route)
        d["gt"] = 21365
        assert "p_mara" in _here(47, crof)                   # arrival → at destination
        assert crof["p_mara"] == 47                          # lazy flip mutated crof
        assert "p_mara" not in d["transit"]                  # row deleted on flip
    finally:
        d.clear(); d.update(saved)


def test_short_hop_is_instant_no_row():
    saved, d = _reset()
    try:
        assert PB["transit_min_steps"] == 3
        # a 1-step hop [44,47] < 3 → routine_step must flip crof immediately, write no row.
        # (verified structurally: worldsim._plan_move returns instant for a short path — see impl)
        node, row = worldsim._plan_move("p_roza", 44, [44, 47], 21360)
        assert row is None and node == 47                    # instant flip, no transit row
        # a 5-step hop ≥ 3 → a row, crof stays at origin (node None means 'do not flip now')
        node2, row2 = worldsim._plan_move("p_mara", 12, [12, 19, 26, 33, 40, 47], 21360)
        assert node2 is None and row2 is not None
        assert row2["arrive_gt"] == 21360 + 5 * PB["step_min"]
    finally:
        d.clear(); d.update(saved)


def test_venue_who_set_unaffected_by_a_cross_town_walker():
    saved, d = _reset()
    try:
        crof = {"host": 47, "guest": 47, "p_mara": 12}
        d["crof"] = crof
        d["transit"] = {"p_mara": {"from": 12, "to": 99, "depart_gt": 21360, "arrive_gt": 21400,
                                   "path": [12, 19, 26, 99]}}   # crosses none of {47}
        d["gt"] = 21362
        assert set(_here_settled(47, crof)) == {"host", "guest"}   # venue who-set: settled only
    finally:
        d.clear(); d.update(saved)


def test_transit_of_reports_in_transit():
    saved, d = _reset()
    try:
        d["transit"] = {"p_mara": {"from": 12, "to": 47, "depart_gt": 21360, "arrive_gt": 21365,
                                   "path": [12, 19, 26, 33, 40, 47]}}
        d["gt"] = 21362
        t = worldsim.transit_of("p_mara")
        assert t and t["kind"] == "в пути" and t["node"] == 26 and t["to"] == 47
        assert worldsim.transit_of("nobody") is None
    finally:
        d.clear(); d.update(saved)
```

- [ ] **Step 3: run test to verify it fails**

Run: `uv run pytest tests/play/test_transit.py -q`
Expected: FAIL — `AttributeError: module '…worldsim' has no attribute '_transit_node'` (and `_here_settled` import error).

- [ ] **Step 4: `_transit_node`, `transit_of`, `_plan_move` in `worldsim.py`**

Add near `predict` (`:130`, where the route/city logic lives). `PB` is now imported (Inc2).

```python
def _transit_node(row: dict, gt: int) -> int:
    """Derived position of a walker at time gt — O(1), nothing ticks. `to` once arrived."""
    if gt >= row["arrive_gt"]:
        return row["to"]
    i = (gt - row["depart_gt"]) // PB["step_min"]
    return row["path"][min(i, len(row["path"]) - 1)]


def transit_of(pid: str) -> dict | None:
    """A live walker's «в пути» summary for read paths (schedule card / geo) — None if settled.
    Honors §10: does NOT touch predict/crosses (forecast stays on the utility path)."""
    row = (_S.get("transit") or {}).get(pid)
    if not row:
        return None
    return {"kind": "в пути", "node": _transit_node(row, _gt()), "to": row["to"]}


def _plan_move(pid: str, origin, path: list, gt: int):
    """Decide instant flip vs transit row for a settled reassignment. Returns (node, row):
      • short hop (< transit_min_steps) or no usable path → (dest, None): caller flips crof now;
      • long hop → (None, row): caller writes _S['transit'][pid]=row and does NOT flip crof."""
    if not path or len(path) < 2:
        return (path[-1] if path else None), None
    steps = len(path) - 1
    if steps < PB["transit_min_steps"]:
        return path[-1], None
    return None, {"from": origin, "to": path[-1], "depart_gt": gt,
                  "arrive_gt": gt + steps * PB["step_min"], "path": list(path)}
```

- [ ] **Step 5: write the transit row at the `crof` flip (`worldsim.py:277-281`)**

Replace the placement block. Where a `node` is chosen for a mover (`:277`), route from the origin and decide instant-vs-transit. The city is already fetched via `_S.get("city")`:

```python
        if node is not None:
            cur = crof.get(pid)
            city = _S.get("city")
            path = []
            if city is not None and cur is not None and cur != node:
                r = city.route(cur, node)
                path = list(r.nodes) if getattr(r, "found", False) else [cur, node]
            flip, row = _plan_move(pid, cur, path, gt) if path else (node, None)
            if row is not None:
                _S.setdefault("transit", {})[pid] = row   # walker: crof stays at origin until arrive_gt
            else:
                crof[pid] = flip                          # instant (short hop / same node / no route)
            kind_of[pid] = akind
        if node is not None and n2b.get(node):            # committed to the venue → counts vs capacity now
            load[node] = load.get(node, 0) + 1
```

> The destination counts toward `load` immediately (the walker is committed there), matching §5-A where Мара's placement fills the tavern even mid-transit.

- [ ] **Step 6: `_here_settled` + transit-aware `_here` (`core.py:243`)**

Replace `_here` (`:243`) with the settled/transit-aware pair. `_S`/`_gt` are already imported at the top of `core.py`; import `_transit_node` lazily to avoid a cycle (worldsim imports from core).

```python
def _flip_arrived(spot: dict) -> None:
    """Lazy, query-shaped: any transit row past its arrive_gt flips into crof and is deleted.
    Nothing ticks — this runs only when a here-query is made."""
    tr = _S.get("transit")
    if not tr:
        return
    from aidnd.server.play.engine.worldsim import _transit_node  # deferred: avoid import cycle
    gt = _gt()
    for pid, row in list(tr.items()):
        if gt >= row["arrive_gt"]:
            spot[pid] = row["to"]
            del tr[pid]


def _here_settled(node, spot):
    """Occupants SETTLED at node: crof members at node MINUS anyone en route (a transit walker is
    not settled anywhere). Flips arrived walkers first. Used by the rebuild trigger / scene build so
    brief walkers never thrash a rebuild (§3.3)."""
    _flip_arrived(spot)
    tr = _S.get("transit") or {}
    return [pid for pid, s in spot.items() if s == node and pid not in tr]


def _here(node, spot):
    """Everyone AT node right now: settled occupants + walkers whose derived transit position == node."""
    out = _here_settled(node, spot)
    tr = _S.get("transit")
    if tr:
        from aidnd.server.play.engine.worldsim import _transit_node
        gt = _gt()
        for pid, row in tr.items():
            if _transit_node(row, gt) == node and pid not in out:
                out.append(pid)
    return out
```

- [ ] **Step 7: rebuild triggers read settled (`loop/tick.py:33,65`)**

In `engine/loop/tick.py`, both `_world_tick` (`:33`) and `_world_tick_fast` (`:65`) import `_here, _live_build` (`:29`, `:61`). Add `_here_settled` to those imports and swap the trigger comparison:

```python
    from ..world import _here_settled, _live_build   # (drop _here here — trigger uses settled)
    ...
    if not lv or lv["loc"] != loc or lv.get("who") != frozenset(_here_settled(loc, crof)):
        _live_build(city, people, crof, cr2b, loc)
```

Re-export `_here_settled` from `world.py` if `tick.py` imports scene helpers from `..world` (it already imports `_here` from there — confirm `world.py` imports `_here_settled` from core at its top import block `:19-26` and lists it, so `from ..world import _here_settled` resolves). If `world.py` does not currently re-export core's `_here`, import `_here_settled` directly `from aidnd.server.play.engine.core import _here_settled` in `tick.py`.

- [ ] **Step 8: scene build reads settled (`world.py:415,429,529`)**

In `_live_build`, the three occupant enumerations must exclude transit walkers (a cross-town walker is not a scene occupant — §3.4). Change:
- `:415` `for pid in _here(loc, crof)` (known_by) → `_here_settled(loc, crof)`
- `:429` `here_all = _here(loc, crof)` → `here_all = _here_settled(loc, crof)`
- `:529` `here = _here(loc, crof)` → `here = _here_settled(loc, crof)`

Ensure `_here_settled` is in `world.py`'s top core import (`:19-26`, alongside `_here`, `_display`).

- [ ] **Step 9: street pass-through in `_live_tick` (`world.py`, near the `feed` assembly `:1090`)**

For a **street** scene (no `bid`), append a pass-through line for each transit walker co-located with the player right now. Add after the churn/zone_feed `feed` assembly:

```python
    if not lv.get("bid"):                                  # street scene — show walkers passing
        from aidnd.server.play.engine.worldsim import _transit_node
        gt = _gt()
        for pid, row in (_S.get("transit") or {}).items():
            if _transit_node(row, gt) == lv["loc"] and pid in people:
                feed.append({"k": "deed", "who": people[pid].name, "pid": pid,
                             "text": "проходит мимо, не задерживаясь"})
```

(Not added to the who-set → no rebuild thrash, per §3.4.)

- [ ] **Step 10: schedule card answers «в пути» (`handlers/misc.py:76`)**

At `misc.py:76` (`"now": RU.get(predict(npc)["kind"], "?")`), prefer a live transit summary:

```python
    from aidnd.server.play.engine.worldsim import transit_of
    _t = transit_of(npc)
    now = _t["kind"] if _t else RU.get(predict(npc)["kind"], "?")   # «в пути» while a row is live
    ...  # use `now` where the card previously inlined RU.get(predict(npc)["kind"], "?")
```

- [ ] **Step 11: run tests to verify they pass**

Run: `uv run pytest tests/play/test_transit.py -q`
Expected: PASS (5 tests).

- [ ] **Step 12: full-suite gate**

Run: `uv run pytest tests -q`
Expected: PASS — 595 + 5 = 600. Watch `test_pin.py` (still `pin`-based, green until Inc4) and any test asserting `_here` semantics — a settled-empty `_S["transit"]` makes `_here_settled ≡ _here ≡` the old comprehension, so untransited worlds behave identically.

- [ ] **Step 13: commit**

```bash
git add src/aidnd/server/play/engine/worldsim.py \
        src/aidnd/server/play/engine/core.py \
        src/aidnd/server/play/engine/loop/tick.py \
        src/aidnd/server/play/engine/world.py \
        src/aidnd/server/play/handlers/misc.py \
        src/aidnd/server/play/engine/session/config.py \
        tests/play/test_transit.py
git commit -m "feat(play/sim): транзит — производные пешеходы (_S[transit]), transit-aware _here + settled-вид, проход по улице, «в пути»"
```

---

## Inc3 close — playtest + deploy

- [ ] **Live playtest** (`/playtest`): **stand on a street node** during a busy phase and watch a **named walker pass through** toward another quarter («…проходит мимо, не задерживаясь»); open an NPC's schedule card mid-journey and confirm it reads **«в пути к …»** rather than a fixed location; confirm the street scene does **not** rebuild-thrash (the walker never becomes a seated occupant).
- [ ] **Deploy** (`/deploy`): ship to prod, verify systemd `aidnd` active.

---

# INCREMENT 4 — анпин (drop the pin + polite postpone)

`routine_step` no longer skips scene NPCs: the `pin` parameter is **dropped**, so a present NPC the routine moves **leaves** — its departure surfaces automatically through Inc1's leaver-diff and Inc3's transit. The one exception: a pid **mid-conversation with the player** (`_S["dlg"]==pid`) has its move **postponed one slot** (`depart_postpone_slots`), a bounded world politeness. Ships last — it depends on Inc1's events and Inc3's transit to look right.

---

## Task 4: drop the pin, add the polite postpone, rewrite the pin test

**Files:**
- Modify: `src/aidnd/server/play/engine/session/config.py:16` (add `depart_postpone_slots`)
- Modify: `src/aidnd/server/play/engine/worldsim.py:208,255` (drop `pin` param + skip; add postpone guard)
- Modify: `src/aidnd/server/play/engine/loop/routine.py:82` (call `routine_step` without `pin`)
- Rewrite: `tests/play/test_pin.py` (→ unpin + postpone contract)

**Interfaces:**
- `routine_step(people: dict, crof: dict) -> None` — the `pin` parameter is removed.
- Postpone: before a chosen `node != crof.get(pid)` is applied, if `_S.get("dlg") == pid` and `_S.get("depart_postpone", {}).get(pid, 0) < PB["depart_postpone_slots"]`, the move is **skipped this slot**, the counter is bumped, and `crof` is unchanged (no departure event); the next slot clears the counter and moves normally. Bounded so it can never trap an NPC.

- [ ] **Step 1: add the PB tunable**

`config.py` PB block:

```python
    "depart_postpone_slots": 1,  # slots a mid-conversation NPC's departure is postponed (world politeness)
```

- [ ] **Step 2: rewrite the pin test to the unpin + postpone contract**

Replace the whole of `tests/play/test_pin.py` (new filename kept for git history clarity; content is the unpin contract):

```python
# tests/play/test_pin.py
"""Inc4 — unpin: scene NPCs are NO LONGER pinned out of the sim. routine_step has no `pin` param;
a present NPC the routine moves actually leaves (its departure rides Inc1's leaver-diff). The one
exception is polite postpone: a pid mid-conversation with the player (_S['dlg']==pid) has its move
skipped ONE slot, then leaves. No LLM."""
import os
import tempfile

import pytest

from aidnd.server.play.engine import core, worldsim
from aidnd.server.play.engine import world as W
from aidnd.server.play.engine.core import PB
from aidnd.server.play.engine.loop import routine as loop_routine
from aidnd.server.play.engine.session import persist


@pytest.fixture
def world(monkeypatch):
    from aidnd.worldgen import WorldStore
    monkeypatch.setattr(persist, "_STORE", WorldStore(os.path.join(tempfile.mkdtemp(), "live.db")))
    core._S["city"] = None
    W._play()
    core._S["gt"] = 8 * 60
    return core._S


def test_routine_step_has_no_pin_param():
    import inspect
    assert "pin" not in inspect.signature(worldsim.routine_step).parameters


def test_apply_routine_calls_without_pin(world, monkeypatch):
    captured = {}
    monkeypatch.setattr(loop_routine, "routine_step",
                        lambda people, crof: captured.update(called=True))
    core._S["routine_key"] = None
    core._S["gt"] = core._S["gt"] + 60
    W._apply_routine()
    assert captured.get("called")               # invoked with (people, crof) only — no pin kwarg


def test_present_npc_is_moved(world):
    # a present NPC (at the player's loc) is NOT skipped: over enough slots the sim may relocate it
    crof, loc = core._S["crof"], core._S["loc"]
    present = [pid for pid, n in crof.items() if n == loc]
    assert present, "fixture must place someone at the player's node"
    victim = present[0]
    core._S.pop("dlg", None)                     # not in conversation → eligible to move
    moved = False
    for k in range(1, 40):                        # advance several 30-min slots
        core._S["routine_key"] = None
        core._S["gt"] = 8 * 60 + k * 60
        before = crof.get(victim)
        worldsim.routine_step(core._S["people"], crof)
        if crof.get(victim) != before or victim in (core._S.get("transit") or {}):
            moved = True
            break
    assert moved                                  # ring B is free to move a present NPC now


def test_mid_conversation_postpones_one_slot(world):
    crof, loc = core._S["crof"], core._S["loc"]
    victim = next(pid for pid, n in crof.items() if n == loc)
    core._S["dlg"] = victim                        # talking to the player → polite postpone
    core._S["depart_postpone"] = {}
    before = crof.get(victim)
    worldsim.routine_step(core._S["people"], crof)
    # this slot: skipped (still at loc, not in transit), counter bumped
    assert crof.get(victim) == before and victim not in (core._S.get("transit") or {})
    assert core._S["depart_postpone"].get(victim) == PB["depart_postpone_slots"]
```

> Note: `W._play()` populates a real pooled world, so `present` is non-empty. If a particular seed leaves the player's node empty, seed one deterministically before the loop (`crof[next(iter(core._S['people']))] = loc`). `test_present_npc_is_moved` asserts *eventual* movement across slots (routine is utility-driven, not guaranteed each slot), which is the honest behavioral claim.

- [ ] **Step 3: run the rewritten test to verify it fails**

Run: `uv run pytest tests/play/test_pin.py -q`
Expected: FAIL — `routine_step` still declares `pin` (so `test_routine_step_has_no_pin_param` fails) and `_apply_routine` still passes `pin=…` (so the 2-arg stub raises `TypeError`).

- [ ] **Step 4: drop the `pin` parameter + skip (`worldsim.py:208,255`)**

Change the signature (`:208`) and docstring: `def routine_step(people: dict, crof: dict) -> None:` (remove `pin: set | None = None` and the pin paragraph). Delete the skip at `:255`:

```python
    for pid, p in order:
        # (Inc4) NO pin skip — scene NPCs relocate; ring A/ring B overlap resolved by the postpone
        # guard below + Inc1's leaver-diff (a departing present NPC surfaces as a leave event).
        st = p.state
```

- [ ] **Step 5: add the polite postpone guard (`worldsim.py`, at the placement `:277`)**

Immediately before the chosen `node` is applied (the Inc3 block from Task 3 Step 5), insert the one-slot postpone for a mid-conversation departure:

```python
        if node is not None and node != crof.get(pid):    # this is a real DEPARTURE from where they stand
            post = _S.setdefault("depart_postpone", {})
            if _S.get("dlg") == pid and post.get(pid, 0) < PB["depart_postpone_slots"]:
                post[pid] = post.get(pid, 0) + 1           # «не срывается на полуслове» — one slot only
                last[pid] = gt
                continue                                   # skip the move; no crof change, no event
            post.pop(pid, None)                            # bound reached / not talking → move normally
        # … (Inc3 route/plan-move block applies the departure: transit row or instant flip) …
```

- [ ] **Step 6: call `routine_step` without `pin` (`loop/routine.py:82`)**

Replace the call at `engine/loop/routine.py:82`:

```python
    routine_step(_S["people"], _S["crof"])   # Inc4: no pin — scene NPCs relocate (postpone guard inside)
```

(The `from ..world import _here` at `:59` is now unused here — remove it if nothing else in `routine.py` references `_here`; verify with `grep -n "_here" src/aidnd/server/play/engine/loop/routine.py`.)

- [ ] **Step 7: run tests to verify they pass**

Run: `uv run pytest tests/play/test_pin.py -q`
Expected: PASS (4 tests).

- [ ] **Step 8: full-suite gate + lint**

Run: `uv run pytest tests -q`
Expected: PASS — 600 (net: `test_pin.py` rewritten in place, transit-count 5 already added in Inc3). Zero regressions: a present NPC leaving now emits an Inc1 leaver event on the next rebuild.

Run: `uv run ruff check src/aidnd/server/play/engine src/aidnd/server/play/handlers/misc.py`
Expected: clean — no unused `_here`/`pin` leftovers.

- [ ] **Step 9: commit**

```bash
git add src/aidnd/server/play/engine/worldsim.py \
        src/aidnd/server/play/engine/loop/routine.py \
        src/aidnd/server/play/engine/session/config.py \
        tests/play/test_pin.py
git commit -m "feat(play/sim): анпин сцены — снят pin, present-NPC уходит (событие+транзит), вежливый postpone на один слот"
```

---

## Inc4 close — playtest + deploy

- [ ] **Live playtest** (`/playtest`): sit in a tavern and **watch a scene NPC leave** — over an evening a present patron gets up and departs (a named/summary leave beat in the digest, and «в пути» if their home is across town). Then **talk to an NPC whose routine wants to send him home**: he **stays for the conversation** and leaves the **following** slot (postpone), never mid-sentence. Confirm a conversation-free NPC leaves immediately when the routine moves him.
- [ ] **Deploy** (`/deploy`): ship the final increment to prod, verify systemd `aidnd` active. The room now truly breathes — people arrive, fill to capacity, cross town in view, and leave.

---

## Self-review notes (writing-plans checklist)

- **Spec coverage:** §2/§3.1/§3.2/§4.3/§4.4/§7-Inc1 → **Inc1** (`_salient`+`_churn_items`+`_ru_count`, diff in `_live_build`, prepend in `_live_tick`, `churn_named_max`, empty-diff/5-join/leaver/cap tests). §2/§3/§4.1/§6/§7-Inc2 → **Inc2** (durable `Counter(crof)+player` ledger, overflow chain `overflow_max_hops`, commitment «у входа», pinned+player counted, player-never-mover). §2/§3/§3.3/§3.4/§4.2/§7-Inc3 → **Inc3** (`_S["transit"]`, `_transit_node`, `_plan_move`, `_here`/`_here_settled` split, street pass-through, `transit_of` «в пути», `transit_min_steps`, all six sub-tests). §2/§3/§3.3/§5-C/§7-Inc4 → **Inc4** (drop `pin`, postpone guard, `depart_postpone_slots`, rewritten pin test). Non-goals honored: no mind «уйти» tool, no NPC↔NPC street encounters, no schedule-window change, no transit interruption (walker arrives regardless), player never blocked, no new table/migration.
- **Zero new LLM calls:** every helper is pure code/derivation; only the pre-existing `scene_digest` runs. Inc1 Step 8 asserts `test_scene_digest` unchanged and churn adds no call; Inc2/3/4 tests instantiate no model. The no-LLM-fallback rule is untouched (nothing to fall back from).
- **Independent green + deployable:** Inc1 is additive (591), `pin` untouched; Inc2 tightens NPC routing only (595), `test_pin` still green; Inc3 is inert on an untransited world (`_here_settled ≡ _here`) (600), `pin` still green; Inc4 rewrites `test_pin` in the same commit as the unpin so the boundary is never red. Each ends with a full-suite gate + live playtest + `/deploy`.
- **Type/name consistency vs real code:** feed items `{k:"deed", who, text[, pid]}` match `scene_digest._event_lines` (`:35-47`) verbatim. Ledger `Counter(crof.values())` keys are nodes (crof is pid→node), `load[_S["loc"]]` is the player's node — correct. `_candidates(p, place_idx, keynode, kps, rng, work_kinds, load, n2b, xy)` and `Candidate(kind, node)` match `worldsim.py:79-113`/`society/routine.py:28`. `contracts(wid, "active"|"offered")` returns dicts with `giver`/`target` (`store.py:399`, `contracts.py:243/286`). `NpcState.hp` / `NpcConfig.max_hp` used via `p.state.hp < p.state.config.max_hp` (the corrected path). `city.route(a,b).nodes`/`.found` per `worldsim.py:161`. `PB` extended in `config.py` and read via `core.PB`.
- **No placeholders:** every code step carries complete code; every test step carries real assertions and load-bearing expected values (`26`, `47`, `21365`, `_ru_count(3)`). The two soft spots are flagged inline, not hidden: (a) Inc3 Step 7's `_here_settled` import route in `tick.py` (re-export from `world.py` vs direct-from-core) — resolve by whichever `world.py` already exposes; (b) Inc4 Step 2's `present`-set may need a deterministic seed if a pooled seed empties the player's node — the note gives the one-liner.

## Task list

- **Inc1 / Task 1** — salience + churn helpers (`_salient`/`_ru_count`/`_churn_items`), wired into `_live_build` diff + `_live_tick` prepend; `PB["churn_named_max"]`. `tests/play/test_churn_events.py` (5).
- **Inc2 / Task 2** — durable `Counter(crof)+player` ledger, overflow chain in `_candidates`, commitment «у входа»; `PB["overflow_max_hops"]`. `tests/play/test_capacity_overflow.py` (4).
- **Inc3 / Task 3** — `_S["transit"]`, `_transit_node`/`_plan_move`/`transit_of`, `_here_settled` + transit-aware `_here`, settled triggers/scene-build, street pass-through, schedule «в пути»; `PB["transit_min_steps"]`. `tests/play/test_transit.py` (5).
- **Inc4 / Task 4** — drop `pin` from `routine_step`/`_apply_routine`, one-slot postpone guard; `PB["depart_postpone_slots"]`. Rewrite `tests/play/test_pin.py` (4).

## Spec ↔ HEAD drift found (summary)

1. **❗ Salience field path is wrong in the spec (§4.3/§6).** `p.state.max_hp` does not exist — `NpcState.hp` is `model.py:63`, but `max_hp` is `NpcConfig.max_hp` (`model.py:35`). The plan uses **`p.state.hp < p.state.config.max_hp`**. (Consistent with §10's own note that this wound signal mostly lies dormant for passive residents.)
2. **⚠️ Path prefix.** The spec writes `loop/tick.py` / `loop/routine.py`; the real paths are `engine/loop/tick.py` / `engine/loop/routine.py`. All cited line numbers (`tick.py:33/55/65`, `routine.py:61/82`) are exact.
3. **⚠️ Off-by-one.** `"who": frozenset(here)` is `world.py:575` (spec says `:576`); `here` is defined at `:529`.
4. **⚠️ `scene_digest` anchor.** `def scene_digest` is `:51` and the `_model().call` is `:59` (spec's `:56` points inside the function); the feed-shape compat via `_event_lines` (`:35-47`) is exact — churn items ride it unchanged.
5. **⚠️ Test drift.** `tests/play/test_pin.py` exercises the exact `pin` behaviour Inc4 removes (`test_apply_routine_pins_present`, `test_routine_step_skips_pinned`); Inc4 rewrites it. Baseline is **586** tests (not stated in the spec).
6. **Reading ambiguities resolved (see Settled decisions), not code drift:** predict «в пути» surfaced via `transit_of` (honoring §10's "crosses/predict unchanged"); a departing scene NPC leaves the settled who-set the same slot (transit walker treated as en-route, not at origin), reconciling §5-C1 with §4.2; churn diff gated to `prev.loc == loc` to avoid flooding on travel.

All other worldsim/core/contracts/config anchors verified **exact** at HEAD `96e7958`.
