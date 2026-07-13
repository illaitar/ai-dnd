# NPC geographic knowledge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an NPC answer «где …?» / «где купить X?» / «где дом Y?» with a geometry-true direction the player can trust — code computes every route fact, the LLM only decides whether to help and which place/person to name (clamped to a code-provided set), and a share reveals the building on the map + writes a `prov="told"` journal row.

**Architecture:** One new pure module `engine/geo.py` (three query functions + a router) sits between the city geometry (`citygraph.City.route`, placements, relationships) and the say-path. `handlers/dialogue.py` `say()` gets a single stable seam — it calls `geo.geo_answer(...)` and passes the result into `_voice(... geo_line=...)`; consequences (`_mark_seen` + `j_place(prov="told")`) fire only on a validated share. Inc 1 ships the geometry + consequence wiring behind a trivial exact-name matcher; Inc 2 swaps the matcher body for a persona-driven mind-router (share/refer/refuse/deflect) and adds quest-framer grounding. The say() seam does not change between increments — only `geo.geo_answer`'s body does.

**Tech Stack:** Python 3, FastAPI say-handler, `aidnd.citygraph` (A* + `Route`), `aidnd.society` place kinds, `WorldStore` (sqlite), the shared `ModelManager` (`core._model()`), pytest via `uv run pytest`.

## Global Constraints

- **Code owns every geographic fact; the LLM only DECIDES and SPEAKS.** Every distance/bearing/landmark comes from `City.route` (`citygraph/graph.py:464`); the LLM authors no geography. Its chosen `bid`/`refer_pid` are clamped to code-provided sets before anything is spoken or revealed.
- **No mechanical gates on NPC behavior.** Willingness lives entirely in the mind-prompt (persona + aff/trust/fear + memories) — one mind-call, no formula, no cooldown, no cap, no roll. **No new PB willingness key.**
- **No LLM fallback.** Parse failure / no model → honest deflection or the existing 503 (`app.py:47`); never canned directions, never a stub answer.
- **Tunables in PB only if truly numeric.** Add `geo_neighbor_hops = 2` (geometric) and `geo_friend_aff = 0.3` (reuses the existing `0.3` affinity literal); reuse `step_min`. No willingness key.
- **Russian commits** in the form `feat(play/geo): …` (or `fix(play/geo): …`). **NEVER** add a `Co-Authored-By: Claude` trailer.
- **Tests run via `uv run pytest`.** Baseline before Inc 1 = 523 passing.
- **Test-fixture discipline (hard-learned):** snapshot/restore the session dict with `saved = dict(core._S._d()); d = core._S._d(); … d.clear(); d.update(saved)`; root-patch `session.persist._STORE` with `monkeypatch.setattr(persist, "_STORE", store)` (journal/store resolve `_store()` lazily). `ruff` strips momentarily-unused imports — keep the lazy-import-inside-function pattern used across the play engine.

---

## File structure

- **Create `src/aidnd/server/play/engine/geo.py`** — pure geo module. No stored state; every function computes per query from `_S` (`city`, `people`, `keynode`, `cr2b`, `loc`) + `_store()` building data + relationships.
- **Modify `src/aidnd/server/play/engine/journal.py`** — `j_place` gains a `prov` param (default `"saw"`).
- **Modify `src/aidnd/server/play/engine/pc/hero.py`** — `_mark_seen` gains keyword `prov`/`text` so a "told" reveal journals once with the right provenance; existing positional call stays valid.
- **Modify `src/aidnd/server/play/engine/session/config.py`** — two new numeric PB keys.
- **Modify `src/aidnd/server/play/engine/narrator/voice.py`** — `_voice` gains an optional `geo_line` param, injected into `bits` like `offer_pitch`.
- **Modify `src/aidnd/server/play/handlers/dialogue.py`** — `say()` calls `geo.geo_answer(...)` before `_voice`, wires `geo_line`, and fires consequences on a share.
- **Modify `src/aidnd/server/play/engine/quests/pipeline.py`** — `_allowed` gains the giver's known-place names.
- **Modify `src/aidnd/server/play/engine/quests/framing.py`** — `framer` appends `direction_line` to a pitch that names a known place.
- **Tests:** `tests/play/test_geo_known_places.py`, `tests/play/test_geo_direction_line.py`, `tests/play/test_geo_journal_prov.py`, `tests/play/test_geo_say_share.py` (Inc 1); `tests/play/test_geo_router.py`, `tests/play/test_geo_referral.py`, `tests/play/test_geo_framer.py` (Inc 2).

### Seam quick-reference (verified `file:line`)

- `citygraph/graph.py:464` `City.route(a,b) -> Route`; `:394` `_heading` → 8-wind `["В","СВ","С","СЗ","З","ЮЗ","Ю","ЮВ"]`; `:485` `_nearest_other_building`; `:498` `_landmarks_at`.
- `citygraph/model.py:112` `Route(found, nodes, edges, steps, crossroads, length, signs, bearing, near_target, landmarks)`; `:104` `Nearby(id, name, dist)`.
- `_S` holds: `city` (City), `people` (pid→Townsperson with `.home` node int, `.work` bid, `.name`, `.role`, `.persona`, `.state`), `keynode` (bid→door node), `cr2b` (node→bid, keys before houses), `loc` (player node int). Set in `worldbuild/assembly.py:163`.
- `core._binfo(bid) -> {"name","kind","label"}` (`core.py:136`); `core._model()` (`core.py`); `society.kinds_of(building_data) -> list[str]` over `{"tavern","temple","market",…}` (`society/places.py:87`).
- `quests/seeds.py:28` `_fam(name)` = surname token; `:32` `_aff(person, other)` = affinity float.
- `journal.py:68` `j_place(text, bid)`; `pc/hero.py:177` `_mark_seen(bid)` (sets `seen|<bid>` flag, calls `j_place`).
- `voice.py:51` `_voice(p, rel, kind, player_text=None, has_offer=False, offer_pitch=None, twist_line=None, active_pitch=None)`; `offer_pitch` injection at `voice.py:138-149`; parse idiom at `voice.py:164`.
- `quests/pipeline.py:101` `_allowed(seed) -> set`; `quests/framing.py:265` `framer(seed, allowed, manager, reward=None)`.

---

# INCREMENT 1 — geo core + exact-name ask-flow

Ships standalone: exact-place questions («где дом Горма») get real, map-marking directions, unit-tested end to end. No mind-router yet — a trivial name matcher stands in.

---

## Task 1: `geo.known_places(pid)` + neighbor/friend PB keys

**Files:**
- Create: `src/aidnd/server/play/engine/geo.py`
- Modify: `src/aidnd/server/play/engine/session/config.py` (PB dict)
- Test: `tests/play/test_geo_known_places.py`

**Interfaces:**
- Consumes: `_S["people"]` (pid→person with `.home:int`, `.work:str|None`, `.name`, `.state.relationships`), `_S["keynode"]` (bid→node), `_S["cr2b"]` (node→bid), `_S["city"]` (`._adj: dict[int,set]`), `core._binfo`, `society.kinds_of`, `seeds._fam`/`_aff`, `PB["geo_neighbor_hops"]`, `PB["geo_friend_aff"]`.
- Produces: `known_places(pid: str) -> list[dict]` — each entry `{"bid": str, "node": int|None, "name": str, "kind": str, "goods": str, "why_known": str}` where `why_known ∈ {"живу","работаю","хожу","все знают","свои","соседи"}`. First rule to claim a `bid` wins; a bid appears once.

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_geo_known_places.py
"""known_places(pid): the 6 source rules compose an NPC's known-set; a far arbitrary
house is NOT in it; the smithy landmark carries its goods hint. Fixture = Ода Вент (spec §5)."""
from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core, geo
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


class _FakeCity:
    """Minimal City surface geo.py depends on: adjacency for neighbor BFS + route() stub."""
    def __init__(self, adj):
        self._adj = adj


def _person(pid, name, role, home, work):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    return SimpleNamespace(id=pid, name=name, role=role, home=home, work=work,
                           persona={}, state=st)


@pytest.fixture
def town(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    # buildings (factsheets drive _binfo name/kind + society.kinds_of detect)
    def _b(bid, name, btype):
        st.save_building(1, bid, {"name": name, "type": btype})
    _b("b_house_oda", "дом Оды", "жилой дом")
    _b("b_market_stall", "лавка Оды", "лавка тканей")
    _b("b_tavern_goose", "«Пьяный гусь»", "таверна")
    _b("b_smithy", "кузница «Молот и мех»", "кузница оружейная")
    _b("b_market", "рыночная площадь", "рынок")
    _b("b_well", "колодец", "колодец")
    _b("b_house_gorm", "дом Горма", "жилой дом")
    _b("b_house_pekka", "дом Пёкка", "жилой дом")
    _b("b_house_vetl", "дом Ветла", "жилой дом")   # arbitrary far house — MUST be excluded
    keynode = {"b_house_oda": 42, "b_market_stall": 55, "b_tavern_goose": 60, "b_smithy": 48,
               "b_market": 54, "b_well": 51, "b_house_gorm": 40, "b_house_pekka": 43,
               "b_house_vetl": 90}
    cr2b = {n: b for b, n in keynode.items()}
    # adjacency: Ода's home 42 neighbours 43 (Пёкка, 1 hop) and 41; 90 is far (unreachable in 2 hops)
    adj = {42: {41, 43}, 43: {42}, 41: {42}, 90: {91}, 91: {90}}
    people = {
        "p_oda": _person("p_oda", "Ода Вент", "лавочница", 42, "b_market_stall"),
        "p_gorm": _person("p_gorm", "Горм Вент", "кузнец", 40, "b_smithy"),
        "p_pekka": _person("p_pekka", "Пёкка Луд", "рыбак", 43, None),
        "p_vetl": _person("p_vetl", "Ветл Кор", "бродяга", 90, None),
    }
    saved = dict(core._S._d()); d = core._S._d()
    try:
        d.clear()
        d.update(wid=1, city=_FakeCity(adj), people=people, keynode=keynode, cr2b=cr2b, loc=50)
        yield people
    finally:
        d.clear(); d.update(saved)


def _by_why(entries):
    out = {}
    for e in entries:
        out.setdefault(e["why_known"], []).append(e)
    return out


def test_all_six_rules_fire(town):
    entries = geo.known_places("p_oda")
    buckets = _by_why(entries)
    assert set(buckets) == {"живу", "работаю", "хожу", "все знают", "свои", "соседи"}


def test_home_and_work_entries(town):
    entries = {e["bid"]: e for e in geo.known_places("p_oda")}
    assert entries["b_house_oda"]["why_known"] == "живу"
    assert entries["b_market_stall"]["why_known"] == "работаю"


def test_smithy_landmark_carries_goods(town):
    entries = {e["bid"]: e for e in geo.known_places("p_oda")}
    assert entries["b_smithy"]["why_known"] == "все знают"
    assert entries["b_smithy"]["goods"] == "оружие, доспехи"


def test_kin_home_included_neighbor_home_included(town):
    entries = {e["bid"]: e for e in geo.known_places("p_oda")}
    assert entries["b_house_gorm"]["why_known"] == "свои"      # kin (same surname Вент)
    assert entries["b_house_pekka"]["why_known"] == "соседи"   # 1 hop from home node 42


def test_far_arbitrary_house_excluded(town):
    bids = {e["bid"] for e in geo.known_places("p_oda")}
    assert "b_house_vetl" not in bids                          # not home/work/kin/neighbor/landmark
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_geo_known_places.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'aidnd.server.play.engine.geo'` (and `PB` missing the two keys once the import resolves).

- [ ] **Step 3: Add the two numeric PB keys**

In `src/aidnd/server/play/engine/session/config.py`, inside the `PB = { … }` dict, add near the other thresholds (e.g. after `"step_min": 1,`):

```python
    # geo (NPC geographic knowledge) — geometric/social tunables, NOT willingness
    "geo_neighbor_hops": 2,     # a home within this many graph hops of yours = "сосед"
    "geo_friend_aff": 0.3,      # affinity above this = friend (reuses seeds.py:203 literal)
```

- [ ] **Step 4: Write `geo.py` with `known_places` + its private helpers**

```python
# src/aidnd/server/play/engine/geo.py
"""NPC geographic knowledge (pure). Code owns every geo fact — this module derives, per query,
which places an NPC could plausibly know, the true route to a place, and who he could refer you
to. The LLM only DECIDES and SPEAKS (Inc 2 router); everything here is deterministic.

No stored state. Reads _S (city/people/keynode/cr2b/loc) + _store() building factsheets +
relationships. See docs/superpowers/specs/2026-07-13-npc-geo-knowledge-design.md."""

from __future__ import annotations

from aidnd import society

from .session.config import PB
from .session.state import _S

# goods hint by building kind keyword (rule 4 landmarks + rule 2 work) — spec §4.1
_GOODS = (
    ("кузн", "оружие, доспехи"),
    ("оружейн", "оружие, доспехи"),
    ("рынок", "всякий товар"),
    ("рыноч", "всякий товар"),
    ("лавк", "ткани, снедь"),
    ("таверн", "выпивка, слухи"),
    ("трактир", "выпивка, слухи"),
    ("постоял", "выпивка, слухи"),
    ("храм", "свечи, благословение"),
    ("часовн", "свечи, благословение"),
    ("колодец", "вода"),
    ("колод", "вода"),
)
# landmark building kinds "everyone knows" beyond society tavern/temple/market (rule 4)
_LANDMARK_WORDS = ("колод", "гильди", "ворот", "мельниц")
_LANDMARK_SOC = {"tavern", "temple", "market"}
_ROUTINE_KINDS = ("tavern", "temple", "market")   # rule 3 routine-venue approximation


def _goods_for(info: dict) -> str:
    blob = (info.get("kind", "") + " " + info.get("name", "")).lower()
    return next((g for w, g in _GOODS if w in blob), "")


def _bdata(bid: str) -> dict:
    from .session.persist import _store
    from .session.state import _wid
    return (_store().get_building(_wid(), bid) or {}).get("data") or {}


def _is_landmark(bid: str) -> bool:
    data = _bdata(bid)
    if set(society.kinds_of(data)) & _LANDMARK_SOC:
        return True
    blob = (str(data.get("type", "")) + " " + str(data.get("name", ""))).lower()
    return any(w in blob for w in _LANDMARK_WORDS)


def _node2bid(node) -> str | None:
    return (_S.get("cr2b") or {}).get(node)


def _home_bid(pid: str) -> str | None:
    p = (_S.get("people") or {}).get(pid)
    return _node2bid(p.home) if p is not None and p.home is not None else None


def _landmark_bids() -> list[str]:
    return [bid for bid in (_S.get("keynode") or {}) if _is_landmark(bid)]


def _routine_venues(p) -> list[str]:
    """Approximation (spec §4.3): the nearest tavern/temple/market to the NPC's home, by route
    length. No clean frequents() accessor exists; this matches what worldsim._candidates seeds."""
    city, keynode = _S.get("city"), _S.get("keynode") or {}
    if city is None or p.home is None:
        return []
    by_kind: dict[str, list[str]] = {}
    for bid in keynode:
        for k in society.kinds_of(_bdata(bid)):
            if k in _ROUTINE_KINDS:
                by_kind.setdefault(k, []).append(bid)
    out = []
    for kind in _ROUTINE_KINDS:
        cands = by_kind.get(kind) or []
        if not cands:
            continue
        best, bd = None, 1e30
        for bid in cands:
            r = city.route(p.home, bid)
            if r.found and r.length < bd:
                bd, best = r.length, bid
        if best is not None:
            out.append(best)
    return out


def _kin_and_friends(pid: str) -> list[str]:
    from .quests.seeds import _aff, _fam
    people = _S.get("people") or {}
    p = people.get(pid)
    if p is None:
        return []
    surname = _fam(p.name)
    out = []
    for other, op in people.items():
        if other == pid:
            continue
        is_kin = surname and _fam(op.name) == surname
        is_friend = _aff(p, other) > PB["geo_friend_aff"]
        is_coworker = bool(p.work) and getattr(op, "work", None) == p.work
        if is_kin or is_friend or is_coworker:
            out.append(other)
    return out


def _neighbor_home_bids(p) -> list[str]:
    """Homes whose node is within PB[geo_neighbor_hops] graph hops of the NPC's home node."""
    city = _S.get("city")
    if city is None or p.home is None:
        return []
    adj = getattr(city, "_adj", {})
    seen, frontier = {p.home}, {p.home}
    for _ in range(int(PB["geo_neighbor_hops"])):
        nxt = set()
        for n in frontier:
            nxt |= set(adj.get(n, ()))
        frontier = nxt - seen
        seen |= nxt
    out = []
    for n in seen:
        if n == p.home:
            continue
        bid = _node2bid(n)
        if bid:
            out.append(bid)
    return out


def known_places(pid: str) -> list[dict]:
    """The NPC's plausibly-known places — 6 source rules (spec §4.1). First rule to claim a bid
    wins; a bid appears once. Each entry: {bid, node, name, kind, goods, why_known}."""
    from .core import _binfo
    people = _S.get("people") or {}
    p = people.get(pid)
    if p is None:
        return []
    keynode = _S.get("keynode") or {}
    out: dict[str, dict] = {}

    def add(bid, why):
        if not bid or bid in out:
            return
        info = _binfo(bid)
        out[bid] = {"bid": bid, "node": keynode.get(bid), "name": info["name"],
                    "kind": info["kind"], "goods": _goods_for(info), "why_known": why}

    if p.home is not None:                              # rule 1 — home
        add(_node2bid(p.home), "живу")
    if p.work:                                          # rule 2 — work
        add(p.work, "работаю")
    for bid in _routine_venues(p):                      # rule 3 — routine venues (approx §4.3)
        add(bid, "хожу")
    for bid in _landmark_bids():                        # rule 4 — town landmarks
        add(bid, "все знают")
    for other in _kin_and_friends(pid):                 # rule 5 — kin & friend homes
        add(_home_bid(other), "свои")
    for bid in _neighbor_home_bids(p):                  # rule 6 — neighbors
        add(bid, "соседи")
    return list(out.values())
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/play/test_geo_known_places.py -q`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add src/aidnd/server/play/engine/geo.py \
        src/aidnd/server/play/engine/session/config.py \
        tests/play/test_geo_known_places.py
git commit -m "feat(play/geo): known_places — 6 правил гео-знания NPC + PB-тюнеры соседей/друзей"
```

---

## Task 2: `geo.direction_line` + `geo.acquaintances`

**Files:**
- Modify: `src/aidnd/server/play/engine/geo.py`
- Test: `tests/play/test_geo_direction_line.py`

**Interfaces:**
- Consumes: `_S["city"].route(from_node, bid) -> Route` (fields `found`, `nodes`, `bearing`, `near_target: Nearby|None`, `landmarks: list[str]`), `PB["step_min"]`, `known_places`, `_S["people"]`.
- Produces:
  - `direction_line(from_node: int, bid: str) -> str` — one always-true RU sentence, or «это на другом конце города» when the route is not found.
  - `acquaintances(pid: str, from_node: int) -> list[dict]` — each `{"pid": str, "name": str, "role": str, "home": int|None, "where_line": str}`; the referrable people (kin/friend/coworker) whose home the NPC knows.

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_geo_direction_line.py
"""direction_line: a thin formatter over City.route — minutes (steps × step_min → RU numeral) +
compass side + nearest landmark. Exact arithmetic from spec §5 Example A step 6."""
from types import SimpleNamespace

import pytest

from aidnd.citygraph.model import Nearby, Route
from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core, geo
from aidnd.server.play.engine.session.config import PB


class _RouteCity:
    """City stub whose route() returns a canned Route keyed by (from_node, bid)."""
    def __init__(self, table):
        self.table = table

    def route(self, a, b):
        return self.table.get((a, b), Route(found=False))


def _person(pid, name, role, home, work):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    return SimpleNamespace(id=pid, name=name, role=role, home=home, work=work,
                           persona={}, state=st)


@pytest.fixture
def wired(monkeypatch):
    saved = dict(core._S._d()); d = core._S._d()
    table = {
        # spec §5 step 6: 5 steps, bearing С, nearest = рыночная площадь
        (50, "b_smithy"): Route(found=True, nodes=[50, 52, 53, 47, 46, 48], bearing="С",
                                near_target=Nearby("b_market", "рыночная площадь", 42.7),
                                landmarks=[]),
        # example C: 2 steps, bearing З, nearest = колодец
        (50, "b_house_gorm"): Route(found=True, nodes=[50, 51, 40], bearing="З",
                                    near_target=Nearby("b_well", "колодец", 30.0), landmarks=[]),
    }
    try:
        d.clear()
        d.update(wid=1, city=_RouteCity(table), loc=50, people={})
        yield d
    finally:
        d.clear(); d.update(saved)


def test_exact_direction_sentence(wired):
    assert geo.direction_line(50, "b_smithy") == "минут пять ходу к северу, за рыночной площадью"


def test_step_min_scaling(wired, monkeypatch):
    monkeypatch.setitem(PB, "step_min", 2)                 # 5 steps × 2 → 10 минут
    assert geo.direction_line(50, "b_smithy") == "минут десять ходу к северу, за рыночной площадью"


def test_west_two_steps(wired):
    assert geo.direction_line(50, "b_house_gorm") == "в паре минут ходу к западу, у колодца"


def test_disconnected_target(wired):
    assert geo.direction_line(50, "b_nowhere") == "это на другом конце города"


def test_bearing_all_eight_winds():
    assert geo._SIDE["С"] == "к северу"
    assert geo._SIDE["СВ"] == "к северо-востоку"
    assert geo._SIDE["В"] == "к востоку"
    assert geo._SIDE["ЮВ"] == "к юго-востоку"
    assert geo._SIDE["Ю"] == "к югу"
    assert geo._SIDE["ЮЗ"] == "к юго-западу"
    assert geo._SIDE["З"] == "к западу"
    assert geo._SIDE["СЗ"] == "к северо-западу"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_geo_direction_line.py -q`
Expected: FAIL — `AttributeError: module 'aidnd.server.play.engine.geo' has no attribute 'direction_line'`.

- [ ] **Step 3: Add `direction_line`, `acquaintances`, and the RU tables to `geo.py`**

Append to `src/aidnd/server/play/engine/geo.py`:

```python
# minutes → RU numeral word for small counts (spec §10 resolved: numeral words 1–10, else «минут N»)
_MIN_WORD = {
    1: "минуту", 2: "пару минут", 3: "минуты три", 4: "минуты четыре", 5: "минут пять",
    6: "минут шесть", 7: "минут семь", 8: "минут восемь", 9: "минут девять", 10: "минут десять",
}
# City._heading 8-wind code → RU "к <side>" (graph.py:399 dirs order)
_SIDE = {
    "С": "к северу", "СВ": "к северо-востоку", "В": "к востоку", "ЮВ": "к юго-востоку",
    "Ю": "к югу", "ЮЗ": "к юго-западу", "З": "к западу", "СЗ": "к северо-западу",
}
# landmark tag (Route.landmarks) → RU clause appended after the near_target
_LM_WORD = {"river": "у реки", "wall": "у городской стены", "gate": "у ворот", "bridge": "у моста"}


def _minutes_phrase(steps: int) -> str:
    m = max(1, steps) * int(PB["step_min"])
    return _MIN_WORD.get(m, f"минут {m}")


def direction_line(from_node, bid: str) -> str:
    """One always-true RU sentence for the route from_node → bid. Thin formatter over City.route:
    minutes (steps × step_min) + compass side + nearest landmark. Voice may wrap, never alter."""
    city = _S.get("city")
    r = city.route(from_node, bid) if city is not None else None
    if r is None or not r.found:
        return "это на другом конце города"
    steps = max(1, len(r.nodes) - 1)
    parts = [f"{_minutes_phrase(steps)} ходу"]
    if r.bearing and r.bearing in _SIDE:
        parts.append(_SIDE[r.bearing])
    # "за рыночной площадью" reads better for an open square; "у <name>" for a point landmark.
    # Spec §5 uses «за рыночной площадью» for the market and «у колодца» for the well.
    tail = ""
    if r.near_target is not None:
        name = r.near_target.name
        prep = "за" if ("площад" in name or "рынок" in name or "рыноч" in name) else "у"
        tail = f", {prep} {_loc_form(name, prep)}"
    lm = next((_LM_WORD[t] for t in (r.landmarks or []) if t in _LM_WORD), "")
    sentence = " ".join(parts) + tail
    if lm:
        sentence += f", {lm}"
    return sentence


def _loc_form(name: str, prep: str) -> str:
    """Instrumental/prepositional case for the landmark noun phrase. The citygraph names are fixed
    strings; map the few real forms, fall back to the raw name (voice smooths any rough edge)."""
    forms = {
        ("за", "рыночная площадь"): "рыночной площадью",
        ("у", "колодец"): "колодца",
        ("у", "рыночная площадь"): "рыночной площади",
    }
    return forms.get((prep, name), name)


def acquaintances(pid: str, from_node) -> list[dict]:
    """Referrable people — kin/friend/coworker whose HOME the NPC knows — with a where_line the NPC
    can speak. Bounds the router's refer_pid choice (spec §4.2 validation)."""
    people = _S.get("people") or {}
    out = []
    for other in _kin_and_friends(pid):
        op = people.get(other)
        if op is None or getattr(op, "home", None) is None:
            continue
        hb = _home_bid(other)
        where = direction_line(from_node, hb) if hb else "где-то в городе"
        out.append({"pid": other, "name": op.name, "role": op.role,
                    "home": op.home, "where_line": where})
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/play/test_geo_direction_line.py -q`
Expected: PASS (5 tests). If `test_exact_direction_sentence` fails on the «за рыночной площадью» form, confirm `_loc_form(("за","рыночная площадь"))` returns «рыночной площадью» — that mapping is what produces the exact spec string.

- [ ] **Step 5: Commit**

```bash
git add src/aidnd/server/play/engine/geo.py tests/play/test_geo_direction_line.py
git commit -m "feat(play/geo): direction_line (маршрут → одна истинная фраза) + acquaintances"
```

---

## Task 3: `j_place`/`_mark_seen` gain a provenance param

**Files:**
- Modify: `src/aidnd/server/play/engine/journal.py:68`
- Modify: `src/aidnd/server/play/engine/pc/hero.py:177-184`
- Test: `tests/play/test_geo_journal_prov.py`

**Interfaces:**
- Consumes: `_store().journal_rows`/`journal_add`, `_store().flags_prefix(wid,"seen|")`.
- Produces:
  - `j_place(text: str, bid: str, prov: str = "saw") -> None` — existing positional call `j_place(text, bid)` unchanged.
  - `_mark_seen(bid: str | None, *, prov: str = "saw", text: str | None = None) -> None` — existing positional call `_mark_seen(bid)` unchanged; a "told" reveal journals ONE `place/told` row with custom text.

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_geo_journal_prov.py
"""j_place gains a prov param (default 'saw' — regression-safe); _mark_seen can journal a
'told' reveal in one row. hero.py's default first-visit call stays 'saw'."""
import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.engine.journal import j_place
from aidnd.server.play.engine.pc.hero import _mark_seen, _seen
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    st.save_building(1, "b_smithy", {"name": "кузница «Молот и мех»", "type": "кузница"})
    saved = dict(core._S._d()); d = core._S._d()
    try:
        d.clear(); d.update(wid=1, gt=600, seen=None)
        yield st
    finally:
        d.clear(); d.update(saved)


def _place_rows(st):
    return [r for r in st.journal_rows(1) if r["kind"] == "place"]


def test_j_place_default_prov_is_saw(store):
    j_place("впервые вошёл в кузницу", "b_smithy")
    rows = _place_rows(store)
    assert rows and rows[-1]["prov"] == "saw"


def test_j_place_told_prov(store):
    j_place("Ода рассказала дорогу к кузнице", "b_smithy", prov="told")
    rows = _place_rows(store)
    assert rows[-1]["prov"] == "told"
    assert "рассказала" in rows[-1]["text"]


def test_mark_seen_told_reveals_and_journals_once(store):
    _mark_seen("b_smithy", prov="told", text="Ода рассказала дорогу к кузнице «Молот и мех»")
    assert "b_smithy" in _seen()
    rows = _place_rows(store)
    assert len(rows) == 1 and rows[0]["prov"] == "told"       # ONE row, right provenance


def test_mark_seen_default_still_saw(store):
    _mark_seen("b_smithy")
    rows = _place_rows(store)
    assert len(rows) == 1 and rows[0]["prov"] == "saw"
    assert "впервые вошёл" in rows[0]["text"]
```

Confirm the row-reader name: check `grep -n "def journal_rows\|def journal_add" src/aidnd/worldgen/*.py` and use the real accessor (the store already backs `journal_add`; `journal_rows(wid)` is used by `tests/play/test_journal_store.py` — mirror whatever that test calls).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_geo_journal_prov.py -q`
Expected: FAIL — `test_j_place_told_prov` raises `TypeError: j_place() got an unexpected keyword argument 'prov'`; `_mark_seen` told-test fails likewise.

- [ ] **Step 3: Add the `prov` param to `j_place`**

In `src/aidnd/server/play/engine/journal.py` replace lines 68-69:

```python
def j_place(text: str, bid: str, prov: str = "saw") -> None:
    return _emit("place", prov, [bid], text)
```

- [ ] **Step 4: Extend `_mark_seen` with keyword `prov`/`text`**

In `src/aidnd/server/play/engine/pc/hero.py` replace the `_mark_seen` body (lines 177-184):

```python
def _mark_seen(bid: str | None, *, prov: str = "saw", text: str | None = None) -> None:
    """Fog of war: location becomes known (map marker) when player LEARNS it — came themselves
    (prov='saw') or heard from people (prov='told'). Journals ONE place row with that provenance."""
    if bid and bid not in _seen():
        _S["seen"].add(bid)
        _store().flag_set(_wid(), f"seen|{bid}")
        from aidnd.server.play.engine.core import _binfo  # deferred: core imports hero (cycle)
        j_place(text or f"впервые вошёл в {_binfo(bid)['name']}", bid, prov=prov)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/play/test_geo_journal_prov.py -q`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add src/aidnd/server/play/engine/journal.py \
        src/aidnd/server/play/engine/pc/hero.py \
        tests/play/test_geo_journal_prov.py
git commit -m "feat(play/geo): j_place/_mark_seen — провенанс 'told' для рассказанной дороги"
```

---

## Task 4: `_voice` gains a `geo_line` param

**Files:**
- Modify: `src/aidnd/server/play/engine/narrator/voice.py:51-54,138-149`
- Test: `tests/play/test_geo_voice_line.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `_voice(p, rel, kind, player_text=None, has_offer=False, offer_pitch=None, twist_line=None, active_pitch=None, geo_line: str | None = None) -> str`. When `geo_line` is set, its text is injected verbatim into the system prompt as a fixed-fact instruction (mirrors `offer_pitch`, `voice.py:138`).

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_geo_voice_line.py
"""_voice injects geo_line into the system prompt as fixed facts the voice may wrap but not alter."""
from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core
from aidnd.server.play.engine.narrator import voice as V
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


class _Capture:
    def __init__(self):
        self.calls = []

    def call(self, role, messages, **kw):
        self.calls.append(messages)
        return {"content": '{"say": "Ступай к кузнице.", "player_tone": "neutral"}'}


def _npc():
    st = NpcState.from_config(NpcConfig(id="npc:oda", name="Ода Вент", role="лавочница"))
    return SimpleNamespace(id="npc:oda", name="Ода Вент", role="лавочница", state=st,
                           persona={}, portraits={}, work=None, keys=[])


@pytest.fixture
def wired(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    saved = dict(core._S._d()); d = core._S._d()
    try:
        d.clear(); d.update(wid=1, gt=600, city_name="Городок")
        yield
    finally:
        d.clear(); d.update(saved)


def test_geo_line_injected(wired, monkeypatch):
    stub = _Capture()
    monkeypatch.setattr(core, "_model", lambda: stub)
    dline = "минут пять ходу к северу, за рыночной площадью"
    line = V._voice(_npc(), {"affinity": 0.2}, "reply", "где кузница?",
                    geo_line=f"ты знаешь место кузница: {dline} — посоветуй дорогу")
    assert line == "Ступай к кузнице."
    sys = stub.calls[-1][0]["content"]
    assert dline in sys


def test_no_geo_line_leaves_prompt_clean(wired, monkeypatch):
    stub = _Capture()
    monkeypatch.setattr(core, "_model", lambda: stub)
    V._voice(_npc(), {"affinity": 0.2}, "reply", "как дела?")
    sys = stub.calls[-1][0]["content"]
    assert "посоветуй дорогу" not in sys
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_geo_voice_line.py -q`
Expected: FAIL — `TypeError: _voice() got an unexpected keyword argument 'geo_line'`.

- [ ] **Step 3: Add the param + injection**

In `src/aidnd/server/play/engine/narrator/voice.py`, extend the signature (lines 51-54):

```python
def _voice(
    p, rel, kind, player_text=None, has_offer: bool = False, offer_pitch: str | None = None,
    twist_line: str | None = None, active_pitch: str | None = None, geo_line: str | None = None,
) -> str:
```

Then, right after the `if active_pitch:` block (currently ending at line 149, before `if twist_line:`), add:

```python
    if geo_line:  # code-computed geo facts — the voice wraps them in character but MUST NOT alter
        bits.append(
            f"ГЕО-ФАКТ (это ИСТИНА от кода — передай суть, НЕ меняй направление, минуты и ориентир, "
            f"не выдумывай своих): {geo_line}"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/play/test_geo_voice_line.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/aidnd/server/play/engine/narrator/voice.py tests/play/test_geo_voice_line.py
git commit -m "feat(play/geo): _voice — kwarg geo_line, гео-факты в промпт как offer_pitch"
```

---

## Task 5: `geo.geo_answer` (exact-name) + `say()` wiring + consequences

**Files:**
- Modify: `src/aidnd/server/play/engine/geo.py`
- Modify: `src/aidnd/server/play/handlers/dialogue.py:216-228`
- Test: `tests/play/test_geo_say_share.py`

**Interfaces:**
- Consumes: `known_places`, `direction_line`, `_S["loc"]`, `_voice(..., geo_line=...)`, `_mark_seen(bid, prov="told", text=...)`.
- Produces:
  - `geo_question(text: str) -> bool` — intent regex hit.
  - `match_known_place(pid: str, text: str) -> dict | None` — a `known_places` entry whose name/kind tokens appear in the text (exact-name matcher; Inc 1 stand-in for the router).
  - `geo_answer(pid: str, text: str, from_node) -> dict | None` — `None` when not a geo question; else `{"geo_line": str, "reveal": {"bid": str, "text": str} | None}`. This is the **stable seam** `say()` consumes in both increments.

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_geo_say_share.py
"""End-to-end Inc 1: a where-question with an exact place name → say() speaks a real direction,
reveals the building (seen|<bid>), and writes a place/told journal row. A non-place line does
neither (regression-safe)."""
import asyncio
from types import SimpleNamespace

import pytest

from aidnd.citygraph.model import Nearby, Route
from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core, geo
from aidnd.server.play.engine.session import persist
from aidnd.server.play.handlers import dialogue as dlg
from aidnd.worldgen import WorldStore


class _Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


class _Voice:
    def call(self, role, messages, **kw):
        # echo whether a geo-fact reached the prompt, so the test can assert wiring
        sys = messages[0]["content"]
        say = "Ступай к кузнице." if "ГЕО-ФАКТ" in sys else "Не знаю, о чём ты."
        return {"content": f'{{"say": "{say}", "player_tone": "neutral"}}'}


class _RouteCity:
    def __init__(self, table):
        self.table = table
        self._adj = {}

    def route(self, a, b):
        return self.table.get((a, b), Route(found=False))


def _npc(pid, name, role, home, work):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    return SimpleNamespace(id=pid, name=name, role=role, home=home, work=work,
                           persona={}, portraits={}, state=st, keys=[])


@pytest.fixture
def town(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    st.save_building(1, "b_smithy", {"name": "кузница «Молот и мех»", "type": "кузница оружейная"})
    st.save_building(1, "b_house_oda", {"name": "дом Оды", "type": "жилой дом"})
    keynode = {"b_smithy": 48, "b_house_oda": 42}
    cr2b = {48: "b_smithy", 42: "b_house_oda"}
    table = {(50, "b_smithy"): Route(found=True, nodes=[50, 52, 53, 47, 46, 48], bearing="С",
                                     near_target=Nearby("b_market", "рыночная площадь", 42.7),
                                     landmarks=[])}
    people = {"npc:oda": _npc("npc:oda", "Ода Вент", "лавочница", 42, "b_smithy")}
    crof = {"npc:oda": 50}
    monkeypatch.setattr(dlg, "_play", lambda: (people["npc:oda"], people, crof, cr2b, 50))
    monkeypatch.setattr(dlg, "_world_tick", lambda: {})
    monkeypatch.setattr(dlg, "_pc_coins", lambda: 0)
    monkeypatch.setattr(dlg, "_here", lambda loc, crof_: list(people))
    monkeypatch.setattr(core, "_model", lambda: _Voice())
    saved = dict(core._S._d()); d = core._S._d()
    try:
        d.clear()
        d.update(wid=1, gt=600, city_name="Городок", city=_RouteCity(table), people=people,
                 keynode=keynode, cr2b=cr2b, loc=50, seen=None)
        yield st
    finally:
        d.clear(); d.update(saved)


def _place_rows(st):
    return [r for r in st.journal_rows(1) if r["kind"] == "place"]


def test_where_question_shares_direction_and_reveals(town):
    res = asyncio.run(dlg.say(_Req({"npc": "npc:oda", "text": "где кузница?"})))
    assert res["line"] == "Ступай к кузнице."                # geo fact reached the voice
    from aidnd.server.play.engine.pc.hero import _seen
    assert "b_smithy" in _seen()                             # map reveal
    rows = _place_rows(town)
    assert rows and rows[-1]["prov"] == "told" and "b_smithy" in rows[-1]["refs"]


def test_ordinary_line_no_geo_no_mark(town):
    res = asyncio.run(dlg.say(_Req({"npc": "npc:oda", "text": "как твои дела?"})))
    assert res["line"] == "Не знаю, о чём ты."               # no geo fact injected
    from aidnd.server.play.engine.pc.hero import _seen
    assert "b_smithy" not in _seen()
    assert _place_rows(town) == []


def test_geo_question_regex():
    assert geo.geo_question("где кузница?")
    assert geo.geo_question("как пройти к храму")
    assert geo.geo_question("где я могу купить оружие")
    assert not geo.geo_question("как твои дела")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_geo_say_share.py -q`
Expected: FAIL — `AttributeError: module '...geo' has no attribute 'geo_question'`.

- [ ] **Step 3: Add the intent regex, matcher, and `geo_answer` to `geo.py`**

Append to `src/aidnd/server/play/engine/geo.py` (add `import re` to the top-of-file imports):

```python
import re

# where-question intent — spec §3.2 (где|куда|как найти|как пройти|где купить|у кого)
_GEO_RE = re.compile(
    r"\b(где|куда|как\s+найти|как\s+пройти|как\s+добраться|где\s+купить|у\s+кого)\b",
    re.IGNORECASE,
)


def geo_question(text: str) -> bool:
    return bool(_GEO_RE.search(text or ""))


def _stem_tokens(s: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[а-яё]+", (s or "").lower()) if len(w) >= 4}


def match_known_place(pid: str, text: str) -> dict | None:
    """Inc 1 exact-name matcher: the known_places entry whose name/kind shares a 4+ char token
    with the question. Longest-name match wins (most specific). Superseded by the router in Inc 2."""
    q = _stem_tokens(text)
    best, score = None, 0
    for e in known_places(pid):
        hit = len(_stem_tokens(e["name"] + " " + e["kind"]) & q)
        if hit > score:
            best, score = e, hit
    return best if score else None


def geo_answer(pid: str, text: str, from_node) -> dict | None:
    """Stable say() seam. None → not a geo question (say() runs unchanged). Otherwise a dict with
    a geo_line for _voice and an optional reveal {bid,text} to _mark_seen. Inc 1 body = exact-name
    matcher → share or deflect; Inc 2 rewrites this body to the persona-driven router."""
    if not geo_question(text):
        return None
    place = match_known_place(pid, text)
    if place is None:
        return {"geo_line": "ты уклончив и не выдаёшь точных мест — отговорись общими словами",
                "reveal": None}
    dline = direction_line(from_node, place["bid"])
    if dline == "это на другом конце города":
        return {"geo_line": f"ты знаешь про {place['kind']} «{place['name']}», но это далеко: "
                            f"{dline} — так и скажи",
                "reveal": None}
    teller = (_S.get("people") or {}).get(pid)
    tname = teller.name if teller is not None else "NPC"
    return {
        "geo_line": f"ты знаешь место {place['kind']} «{place['name']}»: {dline} — посоветуй "
                    "дорогу игроку по-своему",
        "reveal": {"bid": place["bid"],
                   "text": f"{tname} рассказал(а) дорогу к {place['name']}"},
    }
```

- [ ] **Step 4: Wire `say()` to `geo_answer`**

In `src/aidnd/server/play/handlers/dialogue.py`, replace the single `_voice` line at 228 with the geo branch (insert just before it):

```python
    geo_line = None
    from aidnd.server.play.engine import geo
    ga = geo.geo_answer(npc, text, _S.get("loc"))
    if ga:
        geo_line = ga["geo_line"]
        rv = ga.get("reveal")
        if rv:                                            # share only — reveal + told journal row
            _mark_seen(rv["bid"], prov="told", text=rv["text"])
    line = _voice(p, rel, "reply", text, offer_pitch=offer_pitch, active_pitch=active_pitch,
                  geo_line=geo_line)
```

Confirm `_mark_seen` is importable in `dialogue.py` (`grep -n "_mark_seen\|from .*hero" src/aidnd/server/play/handlers/dialogue.py`); if not already imported, add `from aidnd.server.play.engine.pc.hero import _mark_seen` to the module imports (lazy-import inside `say()` if a cycle appears — mirror how `emergent_offer` is imported inside the function at `dialogue.py:136`).

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/play/test_geo_say_share.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Run the full play suite (Inc 1 gate)**

Run: `uv run pytest tests -q`
Expected: PASS — baseline 523 + the Inc 1 tests (no regressions; the non-place branch leaves the existing say-path byte-for-byte).

- [ ] **Step 7: Commit**

```bash
git add src/aidnd/server/play/engine/geo.py \
        src/aidnd/server/play/handlers/dialogue.py \
        tests/play/test_geo_say_share.py
git commit -m "feat(play/geo): say() — вопрос-о-месте → реальная дорога, метка на карте, запись в журнал"
```

---

# INCREMENT 2 — mind-router + referral + framer

Inc 1 proved the geometry + consequence wiring with a trivial matcher. Inc 2 swaps `geo_answer`'s body for a persona-driven mind-router (share/refer/refuse/deflect), adds referral, and grounds the quest-framer. The `say()` seam does not change.

---

## Task 6: `geo.route_geo_ask` — the ONE mind-call + validation clamps

**Files:**
- Modify: `src/aidnd/server/play/engine/geo.py`
- Test: `tests/play/test_geo_router.py`

**Interfaces:**
- Consumes: `known_places`, `acquaintances`, `core._model().call("narrator", msgs, options={"temperature":0.2})`, the `voice.py:164` `_parse` idiom (first `{`…last `}` → `json.loads`).
- Produces: `route_geo_ask(pid: str, question: str, from_node) -> dict` — a validated decision `{"kind": "share"|"refer"|"refuse"|"deflect", "place": dict|None, "refer": dict|None, "манера": str}`. `place` is a `known_places` entry (share); `refer` is an `acquaintances` entry (refer). Clamps: `bid ∉ known set → None`; `refer_pid ∉ acquaintances → None`; parse fail / non-dict → deflect.

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_geo_router.py
"""route_geo_ask: ONE mind-call decides help + which place/person; code clamps the chosen ids to
its own sets. Stub manager feeds canned JSON: share / refuse / refer / out-of-set / parse-fail."""
from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core, geo
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


class _Stub:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def call(self, role, messages, **kw):
        self.calls.append(messages)
        return {"content": self.content}


def _person(pid, name, role, home, work):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    return SimpleNamespace(id=pid, name=name, role=role, home=home, work=work,
                           persona={"нрав": "практичная"}, state=st)


class _FakeCity:
    def __init__(self):
        self._adj = {42: {43}, 43: {42}}

    def route(self, a, b):
        from aidnd.citygraph.model import Nearby, Route
        return Route(found=True, nodes=[a, 1, b if isinstance(b, int) else 40], bearing="З",
                     near_target=Nearby("b_well", "колодец", 30.0), landmarks=[])


@pytest.fixture
def town(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    st.save_building(1, "b_house_oda", {"name": "дом Оды", "type": "жилой дом"})
    st.save_building(1, "b_smithy", {"name": "кузница «Молот и мех»", "type": "кузница оружейная"})
    st.save_building(1, "b_house_gorm", {"name": "дом Горма", "type": "жилой дом"})
    keynode = {"b_house_oda": 42, "b_smithy": 48, "b_house_gorm": 40}
    cr2b = {42: "b_house_oda", 48: "b_smithy", 40: "b_house_gorm"}
    people = {
        "p_oda": _person("p_oda", "Ода Вент", "лавочница", 42, "b_smithy"),
        "p_gorm": _person("p_gorm", "Горм Вент", "кузнец", 40, "b_smithy"),
    }
    saved = dict(core._S._d()); d = core._S._d()
    try:
        d.clear()
        d.update(wid=1, gt=600, city=_FakeCity(), people=people, keynode=keynode, cr2b=cr2b, loc=50)
        yield
    finally:
        d.clear(); d.update(saved)


def _run(monkeypatch, content):
    stub = _Stub(content)
    monkeypatch.setattr(core, "_model", lambda: stub)
    return geo.route_geo_ask("p_oda", "где купить оружие?", 50), stub


def test_share(town, monkeypatch):
    dec, _ = _run(monkeypatch, '{"help":"да","bid":"b_smithy","refer_pid":null,"манера":"по-деловому"}')
    assert dec["kind"] == "share" and dec["place"]["bid"] == "b_smithy"


def test_refuse(town, monkeypatch):
    dec, _ = _run(monkeypatch, '{"help":"нет","bid":null,"refer_pid":null,"манера":"отвернувшись"}')
    assert dec["kind"] == "refuse" and dec["place"] is None


def test_refer(town, monkeypatch):
    dec, _ = _run(monkeypatch, '{"help":"да","bid":null,"refer_pid":"p_gorm","манера":"пожав плечами"}')
    assert dec["kind"] == "refer" and dec["refer"]["pid"] == "p_gorm"


def test_out_of_set_bid_clamps_to_deflect(town, monkeypatch):
    dec, _ = _run(monkeypatch, '{"help":"да","bid":"b_castle","refer_pid":null,"манера":"махнув рукой"}')
    assert dec["kind"] == "deflect" and dec["place"] is None


def test_parse_failure_deflects(town, monkeypatch):
    dec, _ = _run(monkeypatch, "не JSON вовсе")
    assert dec["kind"] == "deflect" and dec["place"] is None and dec["refer"] is None


def test_prompt_lists_only_known_places(town, monkeypatch):
    _, stub = _run(monkeypatch, '{"help":"да","bid":"b_smithy","refer_pid":null,"манера":"x"}')
    sys = stub.calls[-1][0]["content"]
    assert "кузница «Молот и мех»" in sys and "b_castle" not in sys
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_geo_router.py -q`
Expected: FAIL — `AttributeError: module '...geo' has no attribute 'route_geo_ask'`.

- [ ] **Step 3: Add `route_geo_ask` to `geo.py`**

Append to `src/aidnd/server/play/engine/geo.py` (add `import json` to the top imports):

```python
import json

_ROUTER_SYS = (
    "Ты — {name} ({role}). Нрав: {nrav}. Перед тобой ЧУЖАК. Твоё отношение к нему: "
    "приязнь={aff:.2f}, доверие={trust:.2f}, страх={fear:.2f}. Что помнишь о нём: {mem}. "
    "Он спрашивает: «{q}». МЕСТА, КОТОРЫЕ ТЫ ЗНАЕШЬ (выбирай ТОЛЬКО из них, не выдумывай):\n{places}\n"
    "КОГО МОЖЕШЬ ПОСОВЕТОВАТЬ, если места нет: {acq}. "
    "Реши ПО СВОЕМУ НРАВУ И ОТНОШЕНИЮ: помочь ли, и если да — какое МЕСТО из списка назвать "
    "(bid), или кого посоветовать (refer_pid). Ответь СТРОГО JSON: "
    '{{"help":"да|нет|уклончиво","bid":"<id из списка или null>",'
    '"refer_pid":"<id из совета или null>","манера":"<1 фраза, как ты это скажешь>"}}'
)


def _parse_json(content: str):
    i, j = content.find("{"), content.rfind("}")
    if 0 <= i < j:
        try:
            return json.loads(content[i:j + 1])
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def route_geo_ask(pid: str, question: str, from_node) -> dict:
    """The ONE mind-call: the router IS the mind, deciding BOTH willingness AND which place/person,
    from persona + relationship + memories, bounded to code-provided sets. No PB willingness key,
    no roll (constraint §8). Code clamps the chosen ids before anything is spoken or revealed."""
    from .core import _model
    people = _S.get("people") or {}
    p = people.get(pid)
    places = known_places(pid)
    acq = acquaintances(pid, from_node)
    deflect = {"kind": "deflect", "place": None, "refer": None, "манера": ""}
    if p is None:
        return deflect
    rel = (getattr(p.state, "relationships", {}) or {}).get("pc", {})
    mems = [m.text for m in p.state.memory.items if "pc" in (m.about or [])][-3:]
    place_lines = "\n".join(
        f"  - {e['name']} · {e['kind']}" + (f" · {e['goods']}" if e["goods"] else "") for e in places
    ) or "  (ты не знаешь мест)"
    acq_line = ", ".join(f"{a['name']} ({a['role']})" for a in acq) or "никого"
    sys = _ROUTER_SYS.format(
        name=p.name, role=p.role, nrav=(p.persona or {}).get("нрав", "обычный"),
        aff=rel.get("affinity", 0.0), trust=rel.get("trust", 0.0), fear=rel.get("fear", 0.0),
        mem="; ".join(mems) or "ничего", q=question, places=place_lines, acq=acq_line,
    )
    resp = _model().call("narrator", [{"role": "system", "content": sys},
                                      {"role": "user", "content": question}],
                         options={"temperature": 0.2})
    d = _parse_json((resp.get("content") if resp else "") or "")
    if not isinstance(d, dict):
        return deflect
    bid = d.get("bid")
    refer_pid = d.get("refer_pid")
    manera = str(d.get("манера") or "")
    place = next((e for e in places if e["bid"] == bid), None)          # clamp bid ∈ set
    refer = next((a for a in acq if a["pid"] == refer_pid), None)       # clamp refer_pid ∈ acq
    if d.get("help") == "нет":
        return {"kind": "refuse", "place": None, "refer": None, "манера": manera}
    if place is not None:
        return {"kind": "share", "place": place, "refer": None, "манера": manera}
    if refer is not None:
        return {"kind": "refer", "place": None, "refer": refer, "манера": manera}
    return {"kind": "deflect", "place": None, "refer": None, "манера": manera}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/play/test_geo_router.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/aidnd/server/play/engine/geo.py tests/play/test_geo_router.py
git commit -m "feat(play/geo): route_geo_ask — один mind-call (помочь+что назвать) с клампом id в набор"
```

---

## Task 7: `geo_answer` rewired to the router + referral construction

**Files:**
- Modify: `src/aidnd/server/play/engine/geo.py` (`geo_answer` body)
- Test: `tests/play/test_geo_referral.py`

**Interfaces:**
- Consumes: `route_geo_ask`, `direction_line`, the reveal/geo_line contract that `say()` already consumes (unchanged from Inc 1).
- Produces: rewritten `geo_answer(pid, text, from_node) -> dict | None` — share → geo_line + reveal; refer → geo_line with the acquaintance's `where_line`, **no reveal**; refuse/deflect → geo_line, no reveal. `say()` is untouched.

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_geo_referral.py
"""geo_answer via the router: share reveals; refer names a real findable person with NO map mark;
refuse/deflect stay mark-free; a non-place line returns None (say() runs unchanged)."""
from types import SimpleNamespace

import pytest

from aidnd.citygraph.model import Nearby, Route
from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core, geo
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


class _Stub:
    def __init__(self, content):
        self.content = content

    def call(self, role, messages, **kw):
        return {"content": self.content}


def _person(pid, name, role, home, work):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    return SimpleNamespace(id=pid, name=name, role=role, home=home, work=work,
                           persona={"нрав": "практичная"}, state=st)


class _City:
    def __init__(self):
        self._adj = {42: {43}, 43: {42}}

    def route(self, a, b):
        return Route(found=True, nodes=[50, 51, 40], bearing="З",
                     near_target=Nearby("b_well", "колодец", 30.0), landmarks=[])


@pytest.fixture
def town(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    st.save_building(1, "b_house_oda", {"name": "дом Оды", "type": "жилой дом"})
    st.save_building(1, "b_smithy", {"name": "кузница «Молот и мех»", "type": "кузница оружейная"})
    st.save_building(1, "b_house_gorm", {"name": "дом Горма", "type": "жилой дом"})
    keynode = {"b_house_oda": 42, "b_smithy": 48, "b_house_gorm": 40}
    cr2b = {42: "b_house_oda", 48: "b_smithy", 40: "b_house_gorm"}
    people = {
        "p_oda": _person("p_oda", "Ода Вент", "лавочница", 42, "b_smithy"),
        "p_gorm": _person("p_gorm", "Горм Вент", "кузнец", 40, "b_smithy"),
    }
    saved = dict(core._S._d()); d = core._S._d()
    try:
        d.clear()
        d.update(wid=1, gt=600, city=_City(), people=people, keynode=keynode, cr2b=cr2b, loc=50)
        yield
    finally:
        d.clear(); d.update(saved)


def test_share_answer_has_reveal(town, monkeypatch):
    monkeypatch.setattr(core, "_model",
                        lambda: _Stub('{"help":"да","bid":"b_smithy","refer_pid":null,"манера":"x"}'))
    ans = geo.geo_answer("p_oda", "где купить оружие?", 50)
    assert ans["reveal"] and ans["reveal"]["bid"] == "b_smithy"
    assert "кузница" in ans["geo_line"]


def test_refer_answer_no_reveal_names_person(town, monkeypatch):
    monkeypatch.setattr(core, "_model",
                        lambda: _Stub('{"help":"да","bid":null,"refer_pid":"p_gorm","манера":"y"}'))
    ans = geo.geo_answer("p_oda", "где дом Ветла?", 50)
    assert ans["reveal"] is None                              # nothing revealed on a referral
    assert "Горм" in ans["geo_line"] and "у колодца" in ans["geo_line"]


def test_refuse_answer_no_reveal(town, monkeypatch):
    monkeypatch.setattr(core, "_model",
                        lambda: _Stub('{"help":"нет","bid":null,"refer_pid":null,"манера":"z"}'))
    ans = geo.geo_answer("p_oda", "где кузница?", 50)
    assert ans["reveal"] is None


def test_non_place_line_returns_none(town, monkeypatch):
    monkeypatch.setattr(core, "_model", lambda: _Stub("{}"))
    assert geo.geo_answer("p_oda", "как твои дела?", 50) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_geo_referral.py -q`
Expected: FAIL — `test_refer_answer_no_reveal_names_person` fails: Inc 1's exact-name `geo_answer` never refers (returns a deflect geo_line with no «Горм»/«у колодца»).

- [ ] **Step 3: Rewrite the `geo_answer` body to use the router**

Replace the entire `geo_answer` function in `src/aidnd/server/play/engine/geo.py` with:

```python
def geo_answer(pid: str, text: str, from_node) -> dict | None:
    """Stable say() seam. None → not a geo question (say() runs unchanged). Otherwise a dict with
    a geo_line for _voice and an optional reveal {bid,text} to _mark_seen. Inc 2 body: the ONE
    mind-router decides share/refer/refuse/deflect; code builds the always-true geo_line and reveals
    ONLY on a validated share."""
    if not geo_question(text):
        return None
    dec = route_geo_ask(pid, text, from_node)
    manera = f" (манера: {dec['манера']})" if dec.get("манера") else ""
    teller = (_S.get("people") or {}).get(pid)
    tname = teller.name if teller is not None else "NPC"

    if dec["kind"] == "share":
        place = dec["place"]
        dline = direction_line(from_node, place["bid"])
        if dline == "это на другом конце города":
            return {"geo_line": f"ты знаешь про {place['kind']} «{place['name']}», но это далеко: "
                                f"{dline} — так и скажи{manera}", "reveal": None}
        return {
            "geo_line": f"ты знаешь место {place['kind']} «{place['name']}»: {dline} — посоветуй "
                        f"дорогу игроку по-своему{manera}",
            "reveal": {"bid": place["bid"], "text": f"{tname} рассказал(а) дорогу к {place['name']}"},
        }
    if dec["kind"] == "refer":
        r = dec["refer"]
        return {"geo_line": f"места ты не знаешь, но посоветуй спросить {r['name']} ({r['role']}), "
                            f"он {r['where_line']}{manera}", "reveal": None}
    if dec["kind"] == "refuse":
        return {"geo_line": f"ты решил НЕ помогать — по своему нраву, отбрось вопрос{manera}",
                "reveal": None}
    return {"geo_line": f"ты уклончив и не выдаёшь точных мест — отговорись общими словами{manera}",
            "reveal": None}
```

The Inc 1 `match_known_place` helper is now unused by `geo_answer`. Remove it (and its `_stem_tokens` helper if nothing else references it — `grep -n "match_known_place\|_stem_tokens" src/aidnd`) so `ruff` does not flag dead code. Update `tests/play/test_geo_say_share.py`: its `_Voice` stub keys off «ГЕО-ФАКТ» in the prompt, so the share/ordinary assertions still hold under the router — but its `_Voice.call` now also drives `route_geo_ask`, so add a canned share JSON to that stub (return `'{"say":"Ступай к кузнице.","player_tone":"neutral"}'` for the voice call and have the router-model return `'{"help":"да","bid":"b_smithy","refer_pid":null,"манера":"x"}'`; since both go through `core._model()`, give the stub a two-shot `call` that returns the router JSON first, then the voice line — mirror `_Stub` in `test_quest_framer.py:47`). Re-run `test_geo_say_share.py` after editing.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/play/test_geo_referral.py tests/play/test_geo_say_share.py -q`
Expected: PASS (both files).

- [ ] **Step 5: Commit**

```bash
git add src/aidnd/server/play/engine/geo.py \
        tests/play/test_geo_referral.py tests/play/test_geo_say_share.py
git commit -m "feat(play/geo): geo_answer через router — share/refer/refuse; отсылка без метки на карте"
```

---

## Task 8: Quest-framer integration — known places in `_allowed` + `direction_line` on pitches

**Files:**
- Modify: `src/aidnd/server/play/engine/quests/pipeline.py:101-130` (`_allowed`)
- Modify: `src/aidnd/server/play/engine/quests/framing.py:265` (`framer`)
- Test: `tests/play/test_geo_framer.py`

**Interfaces:**
- Consumes: `geo.known_places(giver_pid)`, `geo.direction_line`, `_S["loc"]`.
- Produces: `_allowed` includes the giver's known-place names; `framer` appends the real `direction_line` when a pitch names a known place. A place outside the giver's known-set cannot enter `allowed` (and so cannot pass the apophenia validator).

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_geo_framer.py
"""Framer grounding: the giver's known-place NAMES widen _allowed; a pitch naming a known place
gets the real direction_line appended. A place ∉ giver's set cannot enter allowed."""
from types import SimpleNamespace

import pytest

from aidnd.citygraph.model import Nearby, Route
from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core
from aidnd.server.play.engine.quests import framing as F
from aidnd.server.play.engine.quests import pipeline as P
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


class _City:
    def __init__(self):
        self._adj = {}

    def route(self, a, b):
        return Route(found=True, nodes=[50, 1, 2, 3, 48], bearing="С",
                     near_target=Nearby("b_market", "рыночная площадь", 42.7), landmarks=[])


def _person(pid, name, role, home, work):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    return SimpleNamespace(id=pid, name=name, role=role, home=home, work=work,
                           persona={}, state=st)


@pytest.fixture
def town(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    st.save_building(1, "b_smithy", {"name": "кузница «Молот и мех»", "type": "кузница оружейная"})
    st.save_building(1, "b_house_gorm", {"name": "дом Горма", "type": "жилой дом"})
    keynode = {"b_smithy": 48, "b_house_gorm": 40}
    cr2b = {48: "b_smithy", 40: "b_house_gorm"}
    people = {"npc:gorm": _person("npc:gorm", "Горм Вент", "кузнец", 40, "b_smithy")}
    saved = dict(core._S._d()); d = core._S._d()
    try:
        d.clear()
        d.update(wid=1, gt=600, city=_City(), people=people, keynode=keynode, cr2b=cr2b, loc=50)
        yield
    finally:
        d.clear(); d.update(saved)


def _seed():
    return {"sid": "s1", "pattern": "plain_need", "giver": "npc:gorm", "giver_name": "Горм Вент",
            "why": "нужда", "goal": {"done": {"type": "have", "item": "молот"}},
            "cast": {"villain": None, "prize": None}}


def test_allowed_includes_known_place_names(town):
    allowed = P._allowed(_seed())
    assert "кузница «Молот и мех»" in allowed


def test_place_outside_giver_set_absent_from_allowed(town):
    allowed = P._allowed(_seed())
    assert "b_castle" not in allowed and "замок" not in allowed


class _Stub:
    def __init__(self, content):
        self.content = content

    def call(self, role, messages, **kw):
        return {"content": self.content}


def test_pitch_naming_known_place_gets_direction_appended(town, monkeypatch):
    good = ('{"pitch":"Приходи в кузницу «Молот и мех».",'
            '"foreshadow":"Тебя гложет нужда.","reveal":""}')
    allowed = P._allowed(_seed())
    art = F.framer(_seed(), allowed, _Stub([good]) if False else _Stub(good))
    assert art is not None
    assert "минут" in art["pitch"] and "к северу" in art["pitch"]     # direction_line appended
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_geo_framer.py -q`
Expected: FAIL — `test_allowed_includes_known_place_names` (known-place names not yet whitelisted) and `test_pitch_naming_known_place_gets_direction_appended` (no direction appended).

- [ ] **Step 3: Whitelist the giver's known-place names in `_allowed`**

In `src/aidnd/server/play/engine/quests/pipeline.py`, inside `_allowed`, extend the `giver is not None` block (currently ending at line 126 with `out.add(_binfo(giver.work)["name"])`) — add after it:

```python
        from aidnd.server.play.engine import geo
        for e in geo.known_places(seed["giver"]):     # the giver can honestly name places he knows
            out.add(e["name"])
```

- [ ] **Step 4: Append `direction_line` to a pitch naming a known place**

In `src/aidnd/server/play/engine/quests/framing.py`, inside `framer`, after the artifact `art` is validated and built (just before it is returned as the accepted result — locate the `return art` for the successful branch), append the direction. Add a helper import and a post-process step right before returning the accepted `art`:

```python
        from aidnd.server.play.engine import geo
        from aidnd.server.play.engine.session.state import _S
        places = geo.known_places(seed["giver"]) if seed.get("giver") else []
        named = next((e for e in places if e["name"] in (art.get("pitch") or "")), None)
        if named is not None:
            dline = geo.direction_line(_S.get("loc"), named["bid"])
            if dline and dline != "это на другом конце города" and dline not in art["pitch"]:
                art["pitch"] = (art["pitch"].rstrip() + f" ({dline})")[:220]
        return art
```

(If `framer` returns `art` at more than one point, apply this block only on the accepted branch — the one after `valid_entities`/number validation passes. Read `framing.py:294-320` to place it precisely; the block must run once, on success, before the function returns the good artifact.)

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/play/test_geo_framer.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Run the quest-framer regression suite**

Run: `uv run pytest tests/play/test_quest_framer.py -q`
Expected: PASS — the existing framer tests use seeds with no giver in `_S["people"]`, so `known_places` returns `[]` and the pitch is unchanged (no direction appended). Confirm no regressions.

- [ ] **Step 7: Commit**

```bash
git add src/aidnd/server/play/engine/quests/pipeline.py \
        src/aidnd/server/play/engine/quests/framing.py \
        tests/play/test_geo_framer.py
git commit -m "feat(play/geo): фреймер — известные заказчику места в allowed + реальная дорога в питч"
```

---

## Task 9: Suite gate + live playtest

**Files:** none (verification only).

- [ ] **Step 1: Run the full suite**

Run: `uv run pytest tests -q`
Expected: PASS — baseline 523 + all Inc 1 & Inc 2 geo tests, zero regressions. If red, fix the offending task before proceeding; do not paper over with skips.

- [ ] **Step 2: Live playtest against a running world (deepseek) — checklist, not pytest**

Start the dev server and, as the player, verify the spec §5 scenarios end to end:

- [ ] «а где я могу купить оружие?» to a neutral NPC → he names the smithy with a real minutes/side/landmark direction; the smithy appears on the map; the journal shows a `place/told` row.
- [ ] «где дом Ветла?» (a person NOT in the NPC's known-set) → honest «не знаю» + a **referral** naming a real, findable acquaintance with a true where-line; **no** map mark.
- [ ] Ask a **hostile** NPC (aff < 0) the same way → in-character refusal; the map stays dark, no journal row.
- [ ] Follow a referral to the named person and confirm he is real and reachable at the stated place.
- [ ] Confirm two different NPCs asked the same way give **consistent** (geometry-true) directions — the original contradiction bug (Ода vs Горм) is gone.
- [ ] A quest pitch that names a place now carries the real `direction_line` and never names a place the giver has no route to.

Record the transcript via the `/playtest` skill and note any texture issues (referral mark-or-not, minutes phrasing) for a follow-up.

- [ ] **Step 3: Deploy**

Once green and the playtest reads right, ship via the `/deploy` skill (autonomous prod deploy per project convention). No `Co-Authored-By` trailer on any commit.

---

## Self-review notes (author's pass)

- **Spec coverage:** §4.1 six rules → Task 1; §3.3 `direction_line` + §4 `acquaintances` → Task 2; §3 `j_place(prov)` / `_mark_seen` consequences → Task 3; §3 `_voice geo_line` → Task 4; §3.2 say() wiring + §9 Inc 1 exact-name → Task 5; §4.2 mind-router + validation clamps → Task 6; §5 Example B/C/D/E share/refer/refuse/deflect → Task 7; §3 framer `_allowed` + `direction_line` → Task 8; §7 suite + live scenarios → Task 9. Non-goals (gossip, persistence, escort UI, `askkey_*`, willingness key) are respected — none introduced.
- **Placeholder scan:** no TBD/"similar to"/"add validation" — every code step carries full code; every test step carries real assertions and exact expected strings.
- **Type consistency:** `known_places` entry keys `{bid,node,name,kind,goods,why_known}` used identically in Tasks 1/5/6/7/8; `acquaintances` entry `{pid,name,role,home,where_line}` used in Tasks 2/6/7; `geo_answer` return `{geo_line, reveal:{bid,text}|None}` consumed by say() in Task 5 and re-produced in Task 7; `route_geo_ask` return `{kind,place,refer,манера}` consumed only in Task 7. `_mark_seen(bid, *, prov, text)` and `j_place(text, bid, prov="saw")` signatures match across Tasks 3/5/7.
- **Known soft spot:** `direction_line`'s landmark case forms (`_loc_form`) cover the spec's real strings («рыночной площадью», «колодца»); other citygraph names fall back to the raw noun, which the voice smooths. This is honest (never fabricates geometry) and flagged for the playtest.
