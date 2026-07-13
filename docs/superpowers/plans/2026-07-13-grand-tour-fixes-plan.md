# Grand-tour fixes F4–F7 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four playability cracks the grand tour surfaced downstream of the P0 crowd-budget work: (F4) the player can walk to a building an NPC revealed, not only to landmarks; (F5) an incident-contract carries a real map binding so «дойти до инцидента» works through F4; (F6) the market hum stops erasing the player's personal chronicle; (F7) a free-form pickup never gets narrated before the mechanics grant it.

**Architecture:** Every fix bolts onto an EXISTING seam and reuses the geo module that already shipped (`engine/geo.py` — `direction_line`, `known_places`, `_mark_seen(prov="told")`, `j_place(prov=…)` are all live). No new module.
- **F4** widens the `verb=move place=…` resolver in `handlers/freeform.py` from geom-landmarks-only to a chain `geom.keys → seen buildings`, and teaches `assemble_context` (the arbiter's fact sheet) to name seen buildings so the intent parser can emit `place="дом Медовара"` in the first place.
- **F5** stamps `bid`+`node` onto the incident contract at build time (`engine/incidents.py`), appends a `direction_line` to the board pitch, and marks the incident's building `seen|<bid>` (prov `"told"`) when the player takes the job (`handlers/board.py`).
- **F6** makes `WorldStore.journal_add` prune kind-aware (only high-volume `event` rows) and drops the per-round haggle bid/counter speech from `journal_feed` so only settled deals reach the chronicle.
- **F7** adds a terminal `verb=take` guard in `_attempt` so an unresolved take (item not materialized in the zone) returns an honest refusal instead of falling through to the pure-narration `_say_aloud` arbiter.

**Tech Stack:** Python 3, FastAPI handlers, `aidnd.citygraph` (`City.route` A* + `Route`), `WorldStore` (sqlite), the shared `ModelManager` (`core._model()`), pytest via `uv run pytest`.

**Assumes P0 landed.** A concurrent agent is shipping F1/F2 (LOD crowd budget) — it edits `world.py:966-967`/`:1030`, `loop/tick.py:16-52`, `handlers/freeform.py:560` (the `_world_tick()` call at the tail of `act()`), and `handlers/dialogue.py` (say-path tick). This plan touches **different regions** of those files (F4 = `freeform.py:162-177` and the terminal fallback before `:466`; F6 = `world.py:788-791` haggle-feed emission). **Rebase every task onto P0 before running its tests**; if a cited line number shifted, re-locate the named anchor (function + literal) rather than trusting the number.

## Global Constraints

- **No LLM fallback.** No offline fallbacks at runtime; no LLM → error to the player, never a canned stub. (F4–F7 add code-only paths and honest refusals — none of them fabricate an LLM answer.)
- **Code owns numbers/geometry.** Every route fact (minutes, bearing, landmark, node) comes from `City.route` / `geo.direction_line`; the door node for a goto comes from `city.key_buildings`/`city.houses`, never invented.
- **No mechanical gates on NPC behavior.** Nothing here adds a cooldown/cap/roll to any NPC decision; F4–F7 are player-side resolution, contract data, chronicle pruning, and take routing.
- **Tunables in PB** (`engine/session/config.py`) — F6's event cap is a numeric PB key; nothing else needs a tunable.
- **Russian commits** in the form `feat(play/…): …` or `fix(play/…): …`. **NEVER** add a `Co-Authored-By: Claude` trailer.
- **Test-fixture discipline (hard-learned):** snapshot/restore the session dict with `saved = dict(core._S._d()); d = core._S._d(); … d.clear(); d.update(saved)`; root-patch `session.persist._STORE` with `monkeypatch.setattr(persist, "_STORE", store)` (journal/store resolve `_store()` lazily). `ruff` strips momentarily-unused imports — keep the lazy-import-inside-function pattern used across the play engine.
- **Live playtest per increment** — after each task's suite is green, run the `playtest` skill with the scenario named in the task's final step; deploy only a green + playtested increment.

---

## Seam quick-reference (verified `file:line`)

- `handlers/freeform.py:162-177` — `verb=move place=…` resolver (geom-keys-only today); `:182-214` — `verb=take item=…` branch; `:466` — `text = str(...)` → `_say_aloud` free-narration fallback; `_attempt` signature `:129`; `_play()` returns `(city, people, crof, cr2b, loc)`.
- `engine/action/arbiter.py:107` — `keys_pl = ", ".join(k["label"] for k in _S["geom"]["keys"])`; `:127-132` — the `МЕСТА ГОРОДА: {keys_pl}` fact line; `:37` PRIMITIVES row `{"verb":"move","targets":("place",),"when":"пойти к месту города"}`; `:62` field hint `"place":"<название из МЕСТА ГОРОДА или null>"`.
- `engine/geo.py` — `direction_line(from_node, bid) -> str` (`:201`), `known_places(pid)` (`:139`), `geo_answer` (`:265`). All live on prod.
- `engine/pc/hero.py:171` `_seen() -> set` (bids with `seen|` flag); `:177` `_mark_seen(bid, *, prov="saw", text=None)`.
- `engine/core.py:136` `_binfo(bid) -> {"name","kind","label"}`.
- `citygraph/graph.py` `City.route(a,b)` accepts node|house-id|key-building-id; `_resolve` maps a key-building id → `.interior`, a house id → `.node`. `city.key_buildings[bid].node` = door node; `city.houses[bid].node` = door node.
- `engine/worldbuild/assembly.py:101` `keynode = {bid: kb.node}` (key buildings only, NOT houses); `:167` `cr2b=n2b` (node→bid, key buildings AND houses, key wins).
- `engine/incidents.py:91` `_try_build(t, alive, dead, rng)` (sets `inc["place"]` prose + `inc["patron"]`); `:193` `incident_jobs()` (renders board rows); `:199` the job dict.
- `handlers/board.py:117` `board_take`; `:128-162` the guild/incident-job branch; incidents reach the board via `mechanics/combat.py:245-247` `_guild_board()` merging `incident_jobs()`.
- `worldgen/store.py:248-257` `journal_add` (blind prune to `PB["journal_cap"]`); `:259` `journal_list(world_id, kind=None, limit=200)`; `:87` `save_building(world_id, bid, is_key, node, sign, data)`.
- `engine/journal.py:72-85` `journal_feed(feed)` (one row per witnessed speech/deed); `j_place(text, bid, prov="saw")` `:68`.
- `engine/world.py:788-791` — the two per-round haggle bid/counter `feed.append({"k":"speech",…})` calls in `_npc_trade_step`; `:795-796` the settled-deal `{"k":"deed","pid":buyer,…}` line; `:1299` `journal_feed(feed)`.
- `engine/session/config.py:230-231` PB journal block (`"journal_cap": 2000`).

---

# TASK F4 — move-resolver knows revealed buildings

**Symptom (tour phase D):** Эмса shared the road, `seen|house:9:310_372` is set, a told-row exists — but «иду к дому Медовара» does not move the player: the resolver matches only geom landmarks, and the arbiter can't even name a non-landmark house.

**Root:** two gaps. (1) `handlers/freeform.py:162-177` resolves `place` ONLY against `_S["geom"]["keys"]` (landmarks). (2) `arbiter.py:107,129` lists ONLY geom-key labels under `МЕСТА ГОРОДА`, so the intent parser has no id/name to return for a revealed house — it emits `place=null` (or echoes raw prose the resolver then can't match).

**Fix:** teach `assemble_context` to also name seen non-landmark buildings, and widen the resolver to a chain `geom.keys → seen buildings (by _binfo name, door node from city) → honest refusal`.

**Files:**
- Modify: `src/aidnd/server/play/engine/action/arbiter.py:96-132`
- Modify: `src/aidnd/server/play/handlers/freeform.py:162-177`
- Test: `tests/play/test_freeform_move_seen.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_freeform_move_seen.py
"""F4: verb=move place=… resolves against REVEALED buildings, not just geom landmarks.
A seen house («дом Медовара») → goto=<its door node>; an unrevealed / unknown place → honest
refusal. The arbiter fact sheet must also NAME seen buildings so intent[place] can be produced."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.engine.action import arbiter
from aidnd.server.play.handlers import freeform


class _FakeCity:
    """Minimal City: door nodes for a key building and a residential house."""
    def __init__(self):
        self.key_buildings = {"key:1": SimpleNamespace(node=48)}
        self.houses = {"house:9:310_372": SimpleNamespace(node=372)}


@pytest.fixture
def world(tmp_path, monkeypatch):
    from aidnd.server.play.engine.session import persist
    from aidnd.worldgen import WorldStore

    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    st.save_building(1, "house:9:310_372", False, 372, "дом Медовара",
                     {"name": "дом Медовара", "type": "жилой дом"})
    city = _FakeCity()
    people, crof, cr2b = {}, {}, {372: "house:9:310_372", 48: "key:1"}
    monkeypatch.setattr(freeform, "_play", lambda: (city, people, crof, cr2b, 50))
    d = core._S._d(); saved = dict(d)
    try:
        d.clear()
        d.update(wid=1, gt=514, loc=50, city=city, cr2b=cr2b, keynode={"key:1": 48},
                 geom={"keys": [{"node": 48, "label": "кузня", "bid": "key:1"}]},
                 seen={"house:9:310_372"})
        yield st
    finally:
        d.clear(); d.update(saved)


def test_move_to_seen_house_sets_goto(world):
    res = freeform._attempt({"verb": "move", "place": "дом Медовара"}, {})
    assert res.get("goto") == 372                       # the house's door node
    assert not res.get("fail")


def test_move_to_landmark_still_works(world):
    res = freeform._attempt({"verb": "move", "place": "кузня"}, {})
    assert res.get("goto") == 48


def test_move_to_unknown_place_refuses(world):
    res = freeform._attempt({"verb": "move", "place": "дворец короля"}, {})
    assert res.get("fail") is True
    assert "Спроси у людей" in " ".join(res["narr"])


def test_arbiter_context_names_seen_buildings():
    # assemble_context must list the revealed house under МЕСТА ГОРОДА so the parser can emit it
    from aidnd.server.play.engine.session import state as _state
    d = _state._S._d(); saved = dict(d)
    from aidnd.server.play.engine.session import persist
    from aidnd.worldgen import WorldStore
    import pytest as _pt
    st = WorldStore(":memory:")
    try:
        d.clear()
        d.update(wid=1, loc=50, seen={"house:9:310_372"},
                 geom={"keys": [{"node": 48, "label": "кузня", "bid": "key:1"}]},
                 live={}, zone=None)
        persist._STORE = st
        st.save_building(1, "house:9:310_372", False, 372, "дом Медовара",
                         {"name": "дом Медовара", "type": "жилой дом"})
        sc = {"here": [], "location": {"name": "улица", "containers": []}, "ambient": {}}
        ctx = arbiter.assemble_context(sc)
        assert "дом Медовара" in ctx                     # revealed house is offered to the parser
    finally:
        d.clear(); d.update(saved)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_freeform_move_seen.py -q`
Expected: FAIL — `test_move_to_seen_house_sets_goto` gets `fail=True` (resolver only sees geom keys); `test_arbiter_context_names_seen_buildings` misses «дом Медовара».

- [ ] **Step 3: Widen the move resolver in `freeform.py`**

Replace the whole `if verb == "move" and intent.get("place"):` block (`freeform.py:162-177`):

```python
    if verb == "move" and intent.get("place"):
        want = str(intent["place"]).lower()
        # (1) geom landmarks — the existing path
        tgt = next(
            (
                k
                for k in _S["geom"]["keys"]
                if k["label"].lower() in want or want in k["label"].lower()
            ),
            None,
        )
        if tgt:
            out["goto"] = tgt["node"]  # front will execute normal move (with walking)
            return out
        # (2) buildings the player has been SHOWN (seen|<bid>) — reveal from a share/board-take.
        # Name match on the factsheet name (both directions, like the label match); door node from
        # the city (key-building OR residential house) — never invented.
        from aidnd.server.play.engine.pc.hero import _seen

        matches = []
        for bid in _seen():
            nm = _binfo(bid)["name"].lower()
            if nm and (nm in want or want in nm):
                nd = _door_node(city, bid)
                if nd is not None:
                    matches.append((bid, nd))
        if matches:
            if len(matches) > 1:  # several revealed buildings match the phrase → nearest by route
                matches.sort(key=lambda bn: _route_len(city, loc, bn[0]))
            out["goto"] = matches[0][1]
            return out
        out["narr"].append("Ты не знаешь, где это. Спроси у людей.")
        out["fail"] = True
        return out
```

Add these two module-level helpers near the top of `freeform.py` (after the regexes, before `_lethal_present_npc`):

```python
def _door_node(city, bid: str):
    """Walkable approach (door) node for ANY building id — key building or residential house.
    Matches what geom keys use (kb.node) and what the front's goto expects; never the interior."""
    kb = getattr(city, "key_buildings", {}).get(bid)
    if kb is not None:
        return kb.node
    ho = getattr(city, "houses", {}).get(bid)
    return ho.node if ho is not None else None


def _route_len(city, from_node, bid: str) -> float:
    """Route length from_node → bid for nearest-of-several tie-breaking; unreachable sorts last."""
    r = city.route(from_node, bid)
    return r.length if getattr(r, "found", False) else 1e30
```

- [ ] **Step 4: Teach the arbiter fact sheet to name seen buildings**

In `src/aidnd/server/play/engine/action/arbiter.py`, replace the `keys_pl = …` line (`:107`):

```python
    keys_pl = ", ".join(k["label"] for k in _S["geom"]["keys"])
    from aidnd.server.play.engine.pc.hero import _seen

    from ..core import _binfo
    _lm_bids = {k.get("bid") for k in _S["geom"]["keys"]}
    seen_names = [
        _binfo(b)["name"] for b in _seen()
        if b not in _lm_bids and b != "board:plaza"
    ]
    if seen_names:  # revealed non-landmark buildings the player can walk to (F4)
        keys_pl = (keys_pl + ", " if keys_pl else "") + ", ".join(seen_names)
```

(The `МЕСТА ГОРОДА: {keys_pl}` render at `:129` is untouched — it now carries the wider list.)

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/play/test_freeform_move_seen.py -q`
Expected: PASS (4 tests).

- [ ] **Step 6: Run the play suite (F4 gate)**

Run: `uv run pytest tests -q`
Expected: PASS — baseline + 4 new tests, no regressions (the landmark path is byte-for-byte the old behavior; the seen/refuse branches are additive).

- [ ] **Step 7: Live verification (curl)**

With the dev server up and a world where an NPC has shared a house (or manually `seen|`-flag one), drive:
```bash
curl -s localhost:8000/api/play/act -H 'content-type: application/json' \
  -d '{"text":"иду к дому Медовара"}' | python3 -m json.tool
```
Expected: the response carries `"goto": <int node>` (not the refusal line). An unknown place («иду ко дворцу») returns `"fail": true` + «…Спроси у людей.»

- [ ] **Step 8: Playtest + commit**

Run the `playtest` skill with a scenario: ask an NPC «где дом Медовара?», then «иду туда» / «иду к дому Медовара» — confirm the player actually walks and the map marker is honored.

```bash
git add src/aidnd/server/play/handlers/freeform.py \
        src/aidnd/server/play/engine/action/arbiter.py \
        tests/play/test_freeform_move_seen.py
git commit -m "feat(play/move): резолвер move знает открытые здания (seen|bid), арбитр их называет"
```

---

# TASK F5 — incident contracts carry a place binding

**Symptom (tour):** `ct:inc:*` names its target in prose («твари в подполе — дом семьи Медовар»); there are six Медоваров; the generator KNOWS the victim household but writes no id — so the board can't point anywhere and F4 has nothing to walk to.

**Root:** `engine/incidents.py:_try_build` sets `inc["place"]` as a formatted string only; `incident_jobs()` renders that prose; nothing stamps `bid`/`node`, and taking the job (`board.py:board_take`) never marks the building seen.

**Fix:** compute `bid`+`node` from the patron/victim at build time; append `geo.direction_line(loc, bid)` to the board pitch; on `board_take`, `_mark_seen(bid, prov="told", …)` — the same consequence as a geo-share, so F4 can then walk there.

**Files:**
- Modify: `src/aidnd/server/play/engine/incidents.py:91-159,193-203`
- Modify: `src/aidnd/server/play/handlers/board.py:154-162`
- Test: `tests/play/test_incident_place_bind.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_incident_place_bind.py
"""F5: an incident stamps bid+node onto its contract; incident_jobs appends a real direction to
the pitch; board_take marks the incident's building seen (prov='told') so F4's move-resolver and
the map both point at it."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core, incidents
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


def _person(pid, name, role, home, work):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    return SimpleNamespace(id=pid, name=name, role=role, home=home, work=work, persona={"a": 1},
                           state=st)


@pytest.fixture
def world(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    st.save_building(1, "house:medovar", False, 372, "дом семьи Медовар",
                     {"name": "дом семьи Медовар", "type": "жилой дом"})
    people = {"p_med": _person("p_med", "Ольд Медовар", "пасечник", 372, None)}
    cr2b = {372: "house:medovar"}
    d = core._S._d(); saved = dict(d)
    try:
        d.clear()
        d.update(wid=1, gt=600, people=people, cr2b=cr2b, keynode={}, loc=50, city=None)
        yield st
    finally:
        d.clear(); d.update(saved)


def test_home_incident_binds_bid_and_node(world):
    t = {"key": "vermin", "goal": "clear", "env": "cellar", "cr": [1, 2], "victim": "home",
         "foe": "beasts", "title": "твари в подполе — {place}", "pitch": "{patron} зовёт на подмогу"}
    import random
    inc = incidents._try_build(t, {"p_med": world and core._S["people"]["p_med"]}, set(),
                               random.Random("t"))
    assert inc is not None
    assert inc["bid"] == "house:medovar"
    assert inc["node"] == 372


def test_incident_jobs_appends_direction(world, monkeypatch):
    # a bound incident contract on the board → its pitch carries a geo direction_line
    core._S["people"]["p_med"]  # ensure fixture wired
    world.save_contract(1, "inc|0|vermin", "incident", {
        "type": "vermin", "goal": "clear", "cr": 1.5, "title": "твари в подполе",
        "pitch": "Ольд Медовар зовёт на подмогу", "patron": "p_med", "reward": 8,
        "bid": "house:medovar", "node": 372})

    class _City:
        def route(self, a, b):
            from aidnd.citygraph.model import Nearby, Route
            return Route(found=True, nodes=[50, 60, 372], bearing="З",
                         near_target=Nearby("b_well", "колодец", 30.0), landmarks=[])
    core._S["city"] = _City()
    jobs = incidents.incident_jobs()
    assert jobs and "ходу" in jobs[0]["pitch"]           # direction appended
    assert jobs[0]["bid"] == "house:medovar"


def test_board_take_marks_incident_building_seen(world, monkeypatch):
    from aidnd.server.play.engine.pc.hero import _seen
    from aidnd.server.play.handlers import board as B

    world.save_contract(1, "inc|0|vermin", "incident", {
        "type": "vermin", "goal": "clear", "cr": 1.5, "title": "твари в подполе",
        "pitch": "зов", "patron": "p_med", "reward": 8, "bid": "house:medovar", "node": 372})
    job = {"id": "ct:inc:inc|0|vermin", "lair": "inc|0|vermin", "name": "твари в подполе",
           "cr": 1.5, "reward": 8, "kind": "clear", "pitch": "зов",
           "incident": True, "bid": "house:medovar"}
    monkeypatch.setattr(B, "_guild_board", lambda: [job])
    monkeypatch.setattr(B, "_guild_gate", lambda cr: None)
    monkeypatch.setattr(B, "_accept_contract", lambda *a, **k: "")
    monkeypatch.setattr(B, "_pc_remember", lambda *a, **k: None)

    import asyncio

    class _Req:
        async def json(self):
            return {"id": "ct:inc:inc|0|vermin"}

    monkeypatch.setattr(B, "_play", lambda: (None, {}, {}, {}, 50))
    asyncio.run(B.board_take(_Req()))
    assert "house:medovar" in _seen()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_incident_place_bind.py -q`
Expected: FAIL — `KeyError: 'bid'` in `_try_build`, no `"ходу"` in the pitch, and `board_take` never marks the building.

- [ ] **Step 3: Stamp `bid`+`node` in `_try_build`**

In `src/aidnd/server/play/engine/incidents.py`, add a helper above `_try_build` (after `_fam`, `:61`):

```python
def _place_binding(inc: dict, t: dict) -> tuple[str | None, int | None]:
    """Resolve the incident's building id + door node from the victim/patron the generator already
    knows. Prose place stays; this adds the machine binding F4/board need. vacant/stash → no bid."""
    people = _S.get("people") or {}
    cr2b = _S.get("cr2b") or {}
    keynode = _S.get("keynode") or {}
    victim = t.get("victim")
    if victim == "work":
        pid = inc.get("patron")
        p = people.get(pid)
        bid = p.work if p is not None else None
        return bid, (keynode.get(bid) if bid else None)
    if victim in ("home", "dead_home"):
        # dead_home stores the dead resident's name; the home node is that resident's .home
        pid = inc.get("patron") if victim == "home" else None
        if victim == "dead_home":
            pid = next((k for k, pp in people.items()
                        if _fam(pp.name) == _fam(inc.get("dead_name", "")) ), None) or inc.get("patron")
        p = people.get(pid)
        node = getattr(p, "home", None) if p is not None else None
        return (cr2b.get(node) if node is not None else None), node
    return None, None
```

Then in `_try_build`, right before the `pn = people.get(inc["patron"])` line (`:149`), insert:

```python
    inc["bid"], inc["node"] = _place_binding(inc, t)   # machine binding for board/F4 (prose stays)
```

> Note on `dead_home`: the dead resident's home node lives on `people[vid].home`, and `vid` is chosen in `_try_build` but not kept on `inc`. The helper re-derives the home owner by surname from `dead_name` (already set at `:105`); if that misses, `bid` stays `None` (graceful — board shows prose only, no crash).

- [ ] **Step 4: Append the direction to the board pitch + carry `bid`/`node`**

In `incident_jobs()` (`:193-203`), replace the loop body:

```python
def incident_jobs() -> list:
    """Format incidents as guild board quests (alongside lairs) — with a real direction to the site."""
    from aidnd.server.play.engine import geo

    people = _S.get("people") or {}
    loc = _S.get("loc")
    out = []
    for inc in incidents_active():
        pn = people.get(inc.get("patron"))
        pitch = inc["pitch"]
        bid = inc.get("bid")
        if bid and loc is not None:                    # append the true way there (F5)
            d = geo.direction_line(loc, bid)
            if d and d != "это на другом конце города":
                pitch = f"{pitch} — {d}"
        out.append({"id": f"ct:inc:{inc['id']}", "lair": inc["id"], "name": inc["title"],
                    "cr": inc["cr"], "reward": inc.get("reward", 4),
                    "kind": inc["goal"], "pitch": pitch,
                    "giver_name": pn.name if pn else "гильдия", "incident": True,
                    "bid": bid, "node": inc.get("node")})
    return out
```

- [ ] **Step 5: Mark the building seen on `board_take`**

In `src/aidnd/server/play/handlers/board.py`, in the guild/incident branch, right after `_pc_remember(...)` (`:154-156`) and before the `stolen = …` line (`:157`), insert:

```python
    if job.get("incident") and job.get("bid"):         # F5 — taking the job reveals its building
        from aidnd.server.play.engine.pc.hero import _mark_seen

        _mark_seen(job["bid"], prov="told",
                   text=f"взялся за дело: {job['name']} — знаю, где искать")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/play/test_incident_place_bind.py -q`
Expected: PASS (3 tests).

- [ ] **Step 7: Run the play suite + live curl**

Run: `uv run pytest tests -q` → PASS (existing `tests/play/test_incidents.py` still green — `_try_build` output is a superset).
Then, with a spawned incident on the board:
```bash
curl -s localhost:8000/api/play/board | python3 -m json.tool | grep -A2 pitch   # pitch ends with «…ходу…»
curl -s localhost:8000/api/play/board_take -H 'content-type: application/json' \
  -d '{"id":"ct:inc:<id>"}'                                                     # → taken
curl -s localhost:8000/api/play/act -H 'content-type: application/json' \
  -d '{"text":"иду к дому семьи Медовар"}' | python3 -m json.tool               # → goto set (via F4)
```

- [ ] **Step 8: Playtest + commit**

`playtest` skill, quest preset: spawn/take an incident from the board, then walk to it (F4) and close it by combat.

```bash
git add src/aidnd/server/play/engine/incidents.py \
        src/aidnd/server/play/handlers/board.py \
        tests/play/test_incident_place_bind.py
git commit -m "feat(play/incidents): контракт несёт bid+node, доска даёт дорогу, взятие ставит метку"
```

---

# TASK F6 — kind-aware journal prune + market-hum damping

**Symptom (tour):** journal = 2000×`event`, oldest `gt`=3304 in a world that started at 1180 — a theft, meetings, told-rows all evicted within one market day.

**Root:** two. (a) `worldgen/store.py:250-257` prunes the oldest rows blind to `kind` (`PB["journal_cap"]=2000`), so a flood of `event` rows evicts `person`/`place`/`quest`. (b) `engine/world.py:788-791` emits a per-round haggle bid/counter as tier-1 `speech`, and `journal_feed` (`journal.py:81-83`) writes every tier-1 line as `event/heard1` — that IS the flood. The settled deal is already a `deed` with a `pid` → `event/saw`, which is the one line worth keeping.

**Fix:** (a) prune only `kind='event'`, to a dedicated `PB["journal_cap_event"]`; never prune `person`/`place`/`quest` (their row volume is bounded — a world has ≤1354 people, ~dozens of key buildings/quests — hundreds of rows, not thousands, so an unpruned tail is safe and keeps the personal chronicle whole). (b) tag the two haggle bid/counter feed items and skip them in `journal_feed` — only settled deals (the `deed`) reach the chronicle.

**Files:**
- Modify: `src/aidnd/server/play/engine/session/config.py:230-231`
- Modify: `src/aidnd/worldgen/store.py:248-257`
- Modify: `src/aidnd/server/play/engine/world.py:788-791`
- Modify: `src/aidnd/server/play/engine/journal.py:77-85`
- Test: `tests/play/test_journal_prune_kind.py`, `tests/play/test_journal_feed_haggle.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/play/test_journal_prune_kind.py
"""F6a: journal_add prunes ONLY high-volume event rows to journal_cap_event; person/place/quest
rows survive a flood of events (the player's real story is never evicted by market noise)."""
from __future__ import annotations

import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.engine.session.config import PB
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    d = core._S._d(); saved = dict(d)
    try:
        d.clear(); d.update(wid=1, gt=600)
        yield st
    finally:
        d.clear(); d.update(saved)


def test_events_pruned_to_event_cap(store, monkeypatch):
    monkeypatch.setitem(PB, "journal_cap_event", 5)
    for i in range(20):
        store.journal_add(1, "event", "heard1", [], f"шум {i}", 600 + i)
    events = store.journal_list(1, kind="event", limit=999)
    assert len(events) == 5                              # capped
    assert events[0]["text"] == "шум 19"                # newest kept


def test_personal_rows_survive_event_flood(store, monkeypatch):
    monkeypatch.setitem(PB, "journal_cap_event", 3)
    store.journal_add(1, "place", "told", ["b1"], "мне рассказали дорогу к кузнице", 600)
    store.journal_add(1, "person", "saw", ["p1"], "встретил Оду", 601)
    store.journal_add(1, "quest", "told", ["ct1"], "взял заказ", 602)
    for i in range(50):                                 # market roars all day
        store.journal_add(1, "event", "heard1", [], f"торг {i}", 700 + i)
    assert len(store.journal_list(1, kind="place", limit=999)) == 1
    assert len(store.journal_list(1, kind="person", limit=999)) == 1
    assert len(store.journal_list(1, kind="quest", limit=999)) == 1
    assert len(store.journal_list(1, kind="event", limit=999)) == 3
```

```python
# tests/play/test_journal_feed_haggle.py
"""F6b: journal_feed drops per-round haggle bid/counter speech (tagged bargain=True) but keeps a
settled deal (a deed with a pid → event/saw). Only the closed sale reaches the chronicle."""
from __future__ import annotations

import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.engine.journal import journal_feed
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    d = core._S._d(); saved = dict(d)
    try:
        d.clear(); d.update(wid=1, gt=600)
        yield st
    finally:
        d.clear(); d.update(saved)


def test_haggle_rounds_skipped_settled_deal_kept(store):
    feed = [
        {"k": "speech", "who": "Ода", "tier": 1, "to": "Горм", "bargain": True,
         "text": "— За «нож»? 4."},
        {"k": "speech", "who": "Горм", "tier": 1, "to": "Ода", "bargain": True,
         "text": "— 3, не больше."},
        {"k": "deed", "who": "Горм", "pid": "p_gorm",
         "text": "отсчитывает 3 зм — «нож» переходит из рук в руки"},
    ]
    journal_feed(feed)
    rows = store.journal_list(1, limit=999)
    assert len(rows) == 1                               # only the settled deal
    assert rows[0]["kind"] == "event" and rows[0]["prov"] == "saw"
    assert "отсчитывает" in rows[0]["text"]


def test_ordinary_speech_still_journaled(store):
    journal_feed([{"k": "speech", "tier": 1, "text": "— Слыхал про шайку у стены?"}])
    rows = store.journal_list(1, limit=999)
    assert len(rows) == 1 and rows[0]["prov"] == "heard1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/play/test_journal_prune_kind.py tests/play/test_journal_feed_haggle.py -q`
Expected: FAIL — prune is still blind (`journal_cap_event` KeyError once referenced / personal rows evicted); `journal_feed` writes the two bargain lines as `heard1` so the settled-deal test sees 3 rows.

- [ ] **Step 3: Add the event cap to PB**

In `src/aidnd/server/play/engine/session/config.py`, replace the journal block (`:230-231`):

```python
    # PLAYER JOURNAL «Хроника»: rows kept per world; kind-aware prune (docs/.../player-journal-design.md)
    "journal_cap": 2000,          # legacy total (unused by prune after F6 — kept for any reader)
    "journal_cap_event": 1500,    # F6: ONLY high-volume `event` rows are pruned to this
```

- [ ] **Step 4: Make `journal_add` prune kind-aware**

In `src/aidnd/worldgen/store.py`, replace `journal_add` (`:248-257`):

```python
    def journal_add(self, world_id: int, kind: str, prov: str, refs: list,
                    text: str, gt: int) -> None:
        """Append one chronicle row. Kind-aware prune (F6): only high-volume `event` rows are
        capped (to PB['journal_cap_event']); person/place/quest rows — the player's real story,
        bounded to hundreds — are NEVER pruned, so market noise can't evict them."""
        from aidnd.server.play.engine.core import PB  # lazy: PB is the single home of the cap
        with self._conn() as c:
            c.execute("INSERT INTO journal (world_id,gt,kind,prov,refs,text) VALUES (?,?,?,?,?,?)",
                      (world_id, gt, kind, prov, json.dumps(refs or [], ensure_ascii=False), text))
            c.execute("DELETE FROM journal WHERE world_id=? AND kind='event' AND id NOT IN "
                      "(SELECT id FROM journal WHERE world_id=? AND kind='event' "
                      "ORDER BY id DESC LIMIT ?)",
                      (world_id, world_id, PB["journal_cap_event"]))
```

> Migration: none. Existing rows stay; the new prune predicate applies going forward — the next `event` insert trims the event tail, personal rows are simply never touched again.

- [ ] **Step 5: Tag the haggle rounds + skip them in `journal_feed`**

In `src/aidnd/server/play/engine/world.py`, the two per-round feed appends (`:788-791`) gain a `"bargain": True` tag:

```python
        feed.append({"k": "speech", "who": s_disp, "tier": 1, "to": b_disp, "bargain": True,
                     "text": f"— За «{deal['good']}»? {int(round(deal['ask']))}."})
        feed.append({"k": "speech", "who": b_disp, "tier": 1, "to": s_disp, "bargain": True,
                     "text": f"— {int(round(deal['bid']))}, не больше."})
```

In `src/aidnd/server/play/engine/journal.py`, the speech branch of `journal_feed` (`:78-83`) skips tagged rounds:

```python
    for e in feed or []:
        if e.get("k") == "speech":
            if e.get("bargain"):        # F6: per-round haggle cry — ephemeral, never chronicled
                continue                #     (the settled deal is a deed → event/saw, kept below)
            tier = e.get("tier")
            if tier == 1:
                j_event("heard1", e.get("text", ""), refs=[])
            elif tier == 2:
                j_event("heard2", e.get("text", ""), refs=[])
        elif e.get("k") == "deed" and e.get("pid"):
            j_event("saw", e.get("text", ""), refs=[e["pid"]])
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/play/test_journal_prune_kind.py tests/play/test_journal_feed_haggle.py -q`
Expected: PASS (4 tests).

- [ ] **Step 7: Run the play suite (F6 gate)**

Run: `uv run pytest tests -q`
Expected: PASS — existing `tests/play/test_journal_feed.py` / `test_journal_store.py` still green (ordinary speech + deeds unchanged; only bargain-tagged speech is new and skipped).

- [ ] **Step 8: Live verification**

Sit the player at the market for a simulated day (several `/live` ticks), then read the chronicle:
```bash
curl -s localhost:8000/api/play/journal | python3 -m json.tool | grep -c '"kind": "event"'   # bounded, not a flood
curl -s localhost:8000/api/play/journal | python3 -m json.tool | grep '"kind": "place"'       # day-1 told-rows still present
```
Expected: `place`/`person`/`quest` rows from early in the run survive; no «— За …?»/«— N, не больше.» lines in the chronicle; settled «отсчитывает N зм…» lines present.

- [ ] **Step 9: Playtest + commit**

`playtest` skill, trade scenario near the market: confirm the chronicle keeps meetings/deeds/told-rows while the bid/counter chatter is gone.

```bash
git add src/aidnd/server/play/engine/session/config.py \
        src/aidnd/worldgen/store.py \
        src/aidnd/server/play/engine/world.py \
        src/aidnd/server/play/engine/journal.py \
        tests/play/test_journal_prune_kind.py \
        tests/play/test_journal_feed_haggle.py
git commit -m "fix(play/journal): kind-aware прунинг (только event) + гашение рыночного гула в хронике"
```

---

# TASK F7 — mechanics-before-narration on take

**Symptom (craft test):** «беру ржавый нож со стола» → the DM narrated «…хватаешь рукоять ржавого ножа… ощущая холод металла», inventory unchanged. Narration ran BEFORE (in place of) the mechanics.

**Root:** trace `verb=take item=…` (`freeform.py:182-214`). It returns ONLY inside `if iid in zone_fixed` (refuse) or `if iid in imap.values()` (real transfer). When the parser's `item` is not materialized in the zone (a hallucinated «ржавый нож», or `item=null`), NONE of the take branches return — control falls through every `if verb == "take"` / `say` / `give` / … block to the tail `text = str(...)` (`:466`) → `_say_aloud(text, sc)` → the DM freely narrates the pickup. This is the exact class the lethal-narration fix already closed for violence; take needs the same routing.

**Fix (routing, not prompt-begging):** a terminal `verb == "take"` guard just before the `_say_aloud` fallback — any take that reaches it has NO resolvable target, so it returns an honest refusal and never reaches the narration arbiter. Take-verbs can no longer describe an acquisition that didn't happen.

**Files:**
- Modify: `src/aidnd/server/play/handlers/freeform.py:463-474`
- Test: `tests/play/test_freeform_take_honest.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_freeform_take_honest.py
"""F7: a take that resolves to a REAL zone item transfers it (inventory + narr); a take of an
item not present in the zone (hallucinated / null) returns an honest refusal and NEVER reaches
the free-narration arbiter (_say_aloud / _model). No sensory prose for a phantom pickup."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core
from aidnd.server.play.engine.session import persist
from aidnd.server.play.handlers import freeform
from aidnd.worldgen import WorldStore


class _Stub:
    """Narrator manager — must NOT be called for a phantom take (routing, not narration)."""
    def __init__(self):
        self.called = False

    def call(self, role, messages, **kw):
        self.called = True
        return {"content": "…ты хватаешь холодную рукоять…"}


@pytest.fixture
def world(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    for mod in (core, freeform):
        monkeypatch.setattr(mod, "_store", lambda: st, raising=False)
        monkeypatch.setattr(mod, "_wid", lambda: 1, raising=False)
    monkeypatch.setattr(freeform, "_pc_remember", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(freeform, "_play", lambda: (None, {}, {}, {}, "loc:x"))
    # one REAL zone item: a mug on the player's zone
    st.save_item({"id": "it:mug", "name": "кружка", "kind": "vessel", "worth": 1})
    d = core._S._d(); saved = dict(d)
    try:
        d.clear()
        d.update(wid=1, gt=514, zone="z1",
                 live={"zone_names": {"z1": "у стойки"},
                       "zone_items": {"у стойки": {"кружка": "it:mug"}},
                       "zone_fixed": {}, "workers": {}})
        yield st
    finally:
        d.clear(); d.update(saved)


def test_real_zone_item_is_taken(world, monkeypatch):
    stub = _Stub()
    monkeypatch.setattr(freeform, "_model", lambda: stub, raising=False)
    res = freeform._attempt({"verb": "take", "item": "it:mug"}, {})
    assert any(r["item_id"] == "it:mug" for r in world.inventory(1, "pc"))   # really transferred
    assert not res.get("fail")
    assert not stub.called                                                  # no arbiter narration


def test_phantom_item_refused_without_narration(world, monkeypatch):
    stub = _Stub()
    monkeypatch.setattr(freeform, "_model", lambda: stub, raising=False)
    res = freeform._attempt({"verb": "take", "item": "it:ghost_knife",
                             "_text": "беру ржавый нож со стола"}, {})
    assert res.get("fail") is True
    assert not stub.called                                                  # NEVER free-narrated
    assert "холодную рукоять" not in " ".join(res["narr"])                  # no sensory prose
    assert world.inventory(1, "pc") == []                                   # inventory unchanged


def test_take_null_item_refused(world, monkeypatch):
    stub = _Stub()
    monkeypatch.setattr(freeform, "_model", lambda: stub, raising=False)
    res = freeform._attempt({"verb": "take", "item": None, "_text": "беру что-нибудь"}, {})
    assert res.get("fail") is True
    assert not stub.called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_freeform_take_honest.py -q`
Expected: FAIL — `test_phantom_item_refused_without_narration` and `test_take_null_item_refused` both see `stub.called is True` (control fell through to `_say_aloud`), and the phantom narration leaks into `narr`.

- [ ] **Step 3: Add the terminal take guard**

In `src/aidnd/server/play/handlers/freeform.py`, `_attempt`, replace the tail block (`:463-474`, from `if verb == "attack" and npc:` through the `return _say_aloud(...)`):

```python
    if verb == "attack" and npc:
        return _start_duel(npc, people, crof, loc, cr2b, out)

    if verb == "take":
        # A take that reached here resolved NO real target (item not materialized in the zone,
        # or item=null): honest refusal — NEVER let the narration arbiter describe a phantom
        # pickup. Mechanics decide the transfer; narration only ever renders a real result.
        out["narr"].append("Этого здесь нет — брать нечего.")
        out["fail"] = True
        return out

    text = str(intent.get("_text") or detail or "")
    if _S.get("combat"):  # a live encounter is already resolving — never free-narrate around it
        out["narr"].append("Бой уже идёт — действуй в бою.")
        out["combat"] = True
        return out
    lethal_npc = _lethal_present_npc(text, npc, people, loc, crof)
    if lethal_npc:  # unrecognized violent phrasing toward a real present NPC — no free narration
        return _start_duel(lethal_npc, people, crof, loc, cr2b, out)
    return _say_aloud(text, sc)
```

> This is placed AFTER the resolving take branches (`:179-294`): a real container/item/npc take has already returned; only an unresolved take falls to this guard. It mirrors the lethal-phrasing routing that keeps violence out of `_say_aloud`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/play/test_freeform_take_honest.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the play suite (F7 gate)**

Run: `uv run pytest tests -q`
Expected: PASS — real takes (`:179-294`) are unchanged; the multi-step chain guard (`_run_plan`, `freeform.py:527-530`) still handles chains; only the single-step phantom take changes from narration to refusal.

- [ ] **Step 6: Live verification (curl)**

```bash
# phantom take — honest refusal, no sensory prose
curl -s localhost:8000/api/play/act -H 'content-type: application/json' \
  -d '{"text":"беру ржавый нож со стола"}' | python3 -m json.tool     # → "fail": true, «Этого здесь нет…»
# a real zone item (whatever ПРЕДМЕТЫ РЯДОМ lists) — transfers
curl -s localhost:8000/api/play/act -H 'content-type: application/json' \
  -d '{"text":"беру кружку со стойки"}' | python3 -m json.tool        # → item enters bag, refresh
```

- [ ] **Step 7: Playtest + commit**

`playtest` skill, craft/take scenario: try to grab an item that isn't in the scene (expect an honest «нет»), then grab one that is (expect a real inventory change), and confirm the narrator never describes a pickup that didn't land.

```bash
git add src/aidnd/server/play/handlers/freeform.py \
        tests/play/test_freeform_take_honest.py
git commit -m "fix(play/act): честный take — механика решает перенос, ненайденное = отказ без прозы"
```

---

## Execution order

F4 → F5 (F5's «дойти до инцидента» rides on F4's move-resolver, so land F4 first) → F6 → F7. Each: suite-green + live playtest (with the matrix in its final step) + deploy. All four are independent of one another at the code level except the F4→F5 runtime dependency; sequence them so each ships on a green tree.

---

## Self-review (coverage vs F4–F7)

- **F4 covered:** resolver chain geom.keys → seen buildings → honest refusal (`freeform.py`); door node from `city.key_buildings`/`city.houses` (reuses the citygraph `_resolve` shape, never invents a node); name match via `_binfo(bid)["name"]` both-direction substring (mirrors the existing label match); multiple-seen tie-break by `city.route().length`; **the arbiter-context gap is closed** (`assemble_context` now names seen non-landmark buildings, so `intent["place"]` can carry «дом Медовара» — without this the resolver would never receive a match, a gap the fixes doc did not spell out).
- **F5 covered:** `bid`+`node` computed from patron/victim at build time for `home`/`work`/`dead_home`, graceful `None` for `vacant`/`stash`; `direction_line` appended to the board pitch; `board_take` marks `seen|<bid>` prov=`told`; F4 then walks there. `bid`/`node` carried on the job dict so `board_take` (which only has the job, not the raw contract) can mark.
- **F6 covered:** kind-aware prune (`event` only → `journal_cap_event=1500`; person/place/quest unpruned, with the bounded-volume reasoning stated); hum damping by tagging the two haggle round feed items `bargain=True` and skipping them in `journal_feed` (a mechanical predicate, not a text-pattern guess); settled deals already flow as `deed`→`event/saw` and are kept; no migration.
- **F7 covered:** terminal `verb=take` guard routes every unresolved take to honest refusal before `_say_aloud` — mechanically enforceable routing, not prompt-begging; real takes unchanged; null-item and hallucinated-item both caught.

**Type/name consistency checked against real code:** `save_building(world_id, bid, is_key, node, sign, data)` (6-arg — used correctly in every test fixture); `journal_list(world_id, kind, limit)` (not `journal_rows`); `_mark_seen(bid, *, prov, text)` keyword-only; `direction_line(from_node, bid)`; `_binfo` returns `{"name","kind","label"}`; `contracts()` flattens `data` to top-level (so `inc["bid"]` is read as `inc.get("bid")`, `job["bid"]`).

**Where the code contradicted the fixes doc:** (1) The doc says F4 fixes `freeform.py:164-178` — but that alone is insufficient: the arbiter fact sheet (`arbiter.py:107,129`) also had to learn seen buildings, else `intent["place"]` is never produced for a house. (2) The doc's F6 root cites `store.py:250-257` and `PB["journal_cap"]=2000` at `config.py:230` — the real cap literal is at `config.py:231` and the delete spans `:255-257`; minor line drift, anchors verified. (3) F6's "torговые выкрики дедупятся за тик" is unnecessary — dropping the per-round lines entirely (they are ephemeral negotiation) is simpler and fully satisfies "journal only settled deals"; no per-tick dedup logic is added. (4) The geo scaffolding the doc treats as future work (`geo.direction_line`, `_mark_seen(prov="told")`, `j_place(prov=)`) is ALREADY shipped in `engine/geo.py`/`hero.py`/`journal.py`, so F4/F5 reuse it rather than build it.
