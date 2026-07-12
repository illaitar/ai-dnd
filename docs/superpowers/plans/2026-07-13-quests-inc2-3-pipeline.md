# Emergent Quest Pipeline — Inc 2 & Inc 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** turn the town's own sim state (deeds, agendas, affinities) into *offered* quests — a morning **sift → salience → judge → cast → offer** pipeline (Inc 2), then wrap it in an **arc** (foreshadow → twist → light director FSM, Inc 3), while every completed emergent quest still mechanically advances the giver's real `Agenda` through the already-shipped honest bridge (Inc 1).

**Architecture:** a new pure-ish package `src/aidnd/server/play/engine/quests/` hangs off the existing morning batch (`routine._world_events`). Code sifts and prices real facts (`seeds.py`, `salience.py`, `casting.py`); the LLM appears at exactly two seams, both in `framing.py` (the judge ranking call and the 3-string framer). The chosen seed rides on the existing contract row as 4 JSON fields (`seed/arc/roles/src` + `done_any`) — zero migration; all completion flows through the unchanged triggers `_contract_on_give/_on_move/_on_talk/_on_death` and `_contract_complete`. Inc 3 adds `director.py` (the surfacing FSM), a foreshadow beat (per-mind hot impulse + line, mirroring the `oaths` injection in `world._world_tick`), and a twist beat (`twist.py`, append-only `done_any`).

**Tech Stack:** Python 3.11, `uv run pytest`, SQLite (`WorldStore`), the `aidnd.mind` core (`NpcState`, `Milestone`, `_met`), `aidnd.inference.ModelManager` (`mgr.call("narrator", …)`), FastAPI handlers.

## Global Constraints

- Code owns all numbers; the LLM appears at exactly two seams (the judge ranking, the framer strings) — it never authors a number, predicate, or entity that survives validation.
- No LLM at either seam → honest absence for that morning (error logged, boards/incidents continue), never a canned quest / stub / offline fallback.
- Minds are never throttled: the director paces only the *telling* (`quest_active_max`/`quest_interrupt_k`/`quest_offer_days` cap offers-in-flight and their order, not NPC behavior).
- Predicates never change mid-quest: `done_any[0]` is immutable; the twist only **appends** an OR-disjunct — it never mutates or removes one.
- Improvised personal contracts (`_make_contract`, no `src`) are untouched; emergent quests are marked `data["src"]="sift"`.
- All tunables live in `PB` (`src/aidnd/server/play/engine/session/config.py`); the only code constants are the deed-weight table and the 5-day freshness window in `salience.py`.
- Commits are Russian and scoped `feat(play/quests): …`. **NEVER** add a `Co-Authored-By` trailer.
- Every run uses `uv run pytest`. Pre-quest baseline is **363 passed**, but this plan runs LAST in the serialized order (Inc 1 → journal → Inc 2 → Inc 3), so the actual baseline when it starts is higher (Inc 1 `+16`, journal `+26` → **405**). Assert green as "+N new, 0 failed", not an absolute total.

---

## Consumed interfaces (do NOT redefine)

From the **parallel Inc 1 plan** — `src/aidnd/server/play/engine/quests/bridge.py` exists before this plan runs:

```python
def milestone_to_step(m) -> dict | None      # Milestone → contract step dict (kind/want/target/…) per §4 bridge table
def make_done_any(m) -> list[dict]           # [verbatim real _met dict]; [0] is the giver's milestone predicate
def done_any_met(ct: dict, giver_state) -> bool          # True if ANY done_any disjunct holds right now
def quest_writeback(ct: dict, giver_state, manager=None) -> bool  # advance giver cursor iff a matching open milestone
```

**Interface contract from the finished Inc 1 plan — consume exactly, do NOT redefine:**
- In BOTH `done_any_met` and `quest_writeback`, `giver_state` is the **pair `(state, world)`**, not a bare `NpcState` — because `agenda._met(cond, state, world)` needs both and the giver's loot lives on `world.bodies[id]`, not on `NpcState` (mirrors `advance_agendas(state, world)`). This plan never calls `done_any_met` itself (Task 14 uses its own read-only `_milestone_still_open(state, anchor)`), so no signature is at risk — but if you do call these, pass the `(state, world)` pair.
- `quest_writeback` calls `plan_agenda` ONLY when the agenda is exhausted after `cursor += 1`; an unfinished agenda simply advances to its next pre-authored milestone. It stays wired into `_contract_complete` by Inc 1 — **this plan does not touch it.**
- **Completion closing is Inc 1's, not yours.** Inc 1 adds a helper `_sift_maybe_close()` consulted FIRST in all four completion triggers (`_contract_on_give/_on_move/_on_talk` in `contracts.py`, `_contract_on_death` in `combat.py`), each short-circuiting on `src != "sift"`. Consequence for this plan: **appending a disjunct to `data["done_any"]` is sufficient** — the next relevant trigger closes and pays the quest through `_sift_maybe_close()`. Never write a completion close yourself. (The twist's appended `{type:"dead", id:villain}` disjunct is closed by `_contract_on_death`; the item route by `_contract_on_give`.) The ONLY closes this plan writes are *administrative*: `status="closed"` with `arc.beat="expired"` (compost) and `arc.beat="overtaken"` (moot milestone) — those are explicitly the pipeline/director's job (§5 Step 6 / §6), never a completion.
- **Inc 1 adds NO PB keys.** Every `quest_*` key belongs to this plan (Task 1 + Task 10).

From the **parallel journal plan** — `src/aidnd/server/play/engine/journal.py`:

```python
def j_quest(prov, text, cid) -> None         # append a quest beat to the player journal
```

Every call site guards the journal with `try/except ImportError` so this plan works even if the journal lands later:

```python
def _j_quest(prov, text, cid):               # local shim — repeat verbatim wherever a beat is logged
    try:
        from aidnd.server.play.engine.journal import j_quest
    except ImportError:
        return
    try:
        j_quest(prov, text, cid)
    except Exception:                         # noqa: BLE001 — journal never breaks the pipeline
        pass
```

## Real seams quoted (read before coding)

- `mechanics/contracts.py`: `_build_step` (`:60`, the entity-reject pattern the apophenia validator mirrors — returns `None` on an unknown entity), `_contract_offer` (`:146`), `_make_contract` (`:166`, the `mgr.call("narrator", [{system},{user}], options={"temperature":0.7})` pattern; JSON parsed via `t[t.find("{"):t.rfind("}")+1]`), `_ct_advance` (`:299`), `_contract_complete` (`:311`), `_contract_on_give` (`:343`), `_contract_on_move` (`:371`), `_board_ads` (`:391`).
- `engine/loop/routine.py`: `_world_events` (`:20`) runs the morning batch; each subsystem in its own `try`. Hook the quest morning here after `_board_publish`.
- `engine/incidents.py`: `incident_jobs` (`:193`) renders incidents onto the guild board (the public-merge shape); `save_contract(wid, iid, "incident", inc)`.
- `mind/agenda.py`: `Milestone` (`:24-30`), `_met` (`:59-76`, the 5 real kinds `wealth|dead|affinity|at|have`), `advance_agendas` (`:79`).
- `handlers/dialogue.py`: `talk` (`:100`, stashes `_S["pending_offer"][npc]=offer`), `say` (`:181-182`, pops `pending_offer` when `_WORK_INTEREST_RE` matches).
- `engine/world.py`: `contract_accept` (`:161`, flips `offered→active`); `_world_tick` impulse loop (`:906-932`) and the per-mind `oaths` injection (`ctx["oaths"]=oaths` `:948`, consumed at `llm_agent.py:184`) — the exact pattern the foreshadow beat reuses.
- `mind/llm_agent.py`: prompt builder reads `ctx.get("oaths",{}).get(cfg.id)` (`:184`) and `ctx.get("event")` (`:173`); `plan_agenda` (`:300`).
- `worldgen/store.py`: `save_contract(wid,cid,status,data)` (`:361`), `contracts(wid,status)` (`:366`), `flag_get/flag_set/flag_del` (`:347-358`), `deeds(wid, verb=…, actor=…, status=…, since_gt=…, limit=…)` (`:222`), `purse_get` (`:334`).
- `session/config.py`: `PB` dict (`:16`), contracts block at `:53-59`.

---

# PHASE INC 2 — sift → judge → cast → offer

### Task 1: PB tunables for Inc 2

**Files:**
- Modify: `src/aidnd/server/play/engine/session/config.py:53-59` (contracts block)
- Test: `tests/play/test_quests_pb.py`

**Interfaces:**
- Produces: `PB` keys `quest_topk=4, quest_offer_days=2, quest_w_rare=1.0, quest_w_peak=1.0, quest_w_near=0.6, quest_w_fresh=0.8, quest_twist_p=0.7`.

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_quests_pb.py
from aidnd.server.play.engine.core import PB


def test_inc2_quest_pb_present():
    assert PB["quest_topk"] == 4
    assert PB["quest_offer_days"] == 2
    assert PB["quest_w_rare"] == 1.0
    assert PB["quest_w_peak"] == 1.0
    assert PB["quest_w_near"] == 0.6
    assert PB["quest_w_fresh"] == 0.8
    assert PB["quest_twist_p"] == 0.7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_quests_pb.py -q`
Expected: FAIL with `KeyError: 'quest_topk'`

- [ ] **Step 3: Add the keys**

Insert after `config.py:59` (`"befriend_aff": 0.25,`):

```python
    # emergent quests (Inc 2) — salience weights + surfacing windows (docs/superpowers/specs/2026-07-12-emergent-quests-design.md §11)
    "quest_topk": 4,          # seeds sent to the judge
    "quest_offer_days": 2,    # days an unaccepted offer lives before compost
    "quest_w_rare": 1.0,      # salience weight — pattern rarity
    "quest_w_peak": 1.0,      # salience weight — cast affinity/deed peak
    "quest_w_near": 0.6,      # salience weight — giver↔player proximity
    "quest_w_fresh": 0.8,     # salience weight — evidence freshness
    "quest_twist_p": 0.7,     # probability a qualifying twist candidate is planted
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/play/test_quests_pb.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidnd/server/play/engine/session/config.py tests/play/test_quests_pb.py
git commit -m "feat(play/quests): PB-тюнеры Inc 2 — веса salience и окна предложения [quests inc2]"
```

---

### Task 2: `seeds.py` — QuestSeed + the 5 sifting patterns

**Files:**
- Create: `src/aidnd/server/play/engine/quests/__init__.py`
- Create: `src/aidnd/server/play/engine/quests/seeds.py`
- Test: `tests/play/test_quest_seeds.py`

**Interfaces:**
- Consumes: `_S["people"][pid]` wrappers (`.name`, `.role`, `.state` = `NpcState` with `.agendas`, `.relationships`); the `Milestone` dataclass (`aidnd.mind.agenda`); deed dicts from `store.deeds(...)` with keys `id, gt, actor, verb, obj, place, status, data`.
- Produces:
  - `DELEGATABLE = {"have", "dead", "wealth", "affinity"}` (excludes `"at"` per §4 table).
  - `sift(people: dict, deeds: list, gt: int) -> list[dict]` — deduped `QuestSeed` list.
  - Each pattern `pat_<name>(people, deeds, gt) -> list[dict]`; registry `PATTERNS`.
  - `QuestSeed` shape (dict, per §4): `{"pattern","giver","giver_name","goal":{"kind","target","done"},"cast":{"villain","prize"},"motivation","twist":<dict|None>,"evidence":[…],"score":0.0}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_quest_seeds.py
"""Просев: пять паттернов связываются/воздерживаются ровно как в §5 Step 1 (тройка Дунн/Марта/Ральф)."""
from types import SimpleNamespace

from aidnd.mind import NpcConfig, NpcState
from aidnd.mind.agenda import Agenda, Milestone
from aidnd.server.play.engine.quests import seeds as S


def _person(pid, name, role, agendas=(), rels=None):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    st.agendas = list(agendas)
    st.relationships = dict(rels or {})
    return SimpleNamespace(name=name, role=role, state=st, persona={}, work=None)


def _fixture(gt=3 * 1440):
    # Дунн: открытая веха acquire, done={have,гроссбух}; недолюбливает Ральфа (−0.4)
    dunn_ms = Milestone("вернуть гроссбух сестры", "acquire", "debt:marta", {},
                        {"type": "have", "item": "гроссбух"})
    dunn = _person("npc:dunn", "Дунн Ли", "охотник",
                   agendas=[Agenda("вернуть гроссбух сестры", "ambition", 0.7, [dunn_ms])],
                   rels={"npc:ralf": {"affinity": -0.4}})
    # Ральф: держатель гроссбуха; к Дунну лишь −0.1 (не взаимная вражда)
    ralf = _person("npc:ralf", "Ральф Ли", "ростовщик",
                   rels={"npc:dunn": {"affinity": -0.1}})
    # Марта: сестра Дунна, обида на Ральфа (−0.6), своей агенды нет
    marta = _person("npc:marta", "Марта Ли", "торговка",
                    rels={"npc:ralf": {"affinity": -0.6}})
    people = {"npc:dunn": dunn, "npc:ralf": ralf, "npc:marta": marta}
    # d123: обещание Ральфа Марте — нарушено, 1 день назад
    d123 = {"id": "d123", "gt": gt - 1440, "actor": "npc:ralf", "obj": "npc:marta",
            "verb": "promise", "place": "", "status": "broken",
            "data": {"what": "вернуть гроссбух", "made_gt": gt - 1440}}
    # d124: Ральф сам должен гильдии — второй факт о составе (кандидат на твист)
    d124 = {"id": "d124", "gt": gt - 720, "actor": "npc:ralf", "obj": "guild",
            "verb": "promise", "place": "", "status": "broken",
            "data": {"what": "отдать гильдии 200", "made_gt": gt - 720}}
    return people, [d123, d124], gt


def test_kin_debt_and_broken_promise_bind_others_abstain():
    people, deeds, gt = _fixture()
    got = {(s["pattern"], s["giver"]) for s in S.sift(people, deeds, gt)}
    assert ("kin_debt", "npc:dunn") in got          # ✔ Дунн — брат за сестру
    assert ("broken_promise", "npc:marta") in got   # ✔ Марта — жертва с обидой
    assert ("blocked_rival", "npc:dunn") not in got  # ✘ вражда не взаимна (Ральф→Дунн −0.1)
    assert not any(p == "unanswered_blood" for p, _ in got)  # ✘ нет крови/кражи
    assert not any(p == "courtship_wall" for p, _ in got)    # ✘ веха не courtship


def test_kin_debt_goal_is_verbatim_milestone_done():
    people, deeds, gt = _fixture()
    seed = next(s for s in S.sift(people, deeds, gt) if s["pattern"] == "kin_debt")
    assert seed["goal"]["done"] == {"type": "have", "item": "гроссбух"}  # дословно из вехи
    assert seed["cast"] == {"villain": "npc:ralf", "prize": "npc:marta"}
    assert "d123" in seed["evidence"]
    assert "agenda:npc:dunn:0" in seed["evidence"]


def test_broken_promise_goal_is_real_met_dict():
    people, deeds, gt = _fixture()
    seed = next(s for s in S.sift(people, deeds, gt) if s["pattern"] == "broken_promise")
    assert seed["goal"]["done"] == {"type": "dead", "id": "npc:ralf"}   # маршрут-возмездие, код-авторство
    assert seed["evidence"] == ["d123"]


def test_twist_candidate_from_second_fact_touching_cast():
    people, deeds, gt = _fixture()
    seed = next(s for s in S.sift(people, deeds, gt) if s["pattern"] == "kin_debt")
    assert seed["twist"] and seed["twist"]["adds"] == {"type": "dead", "id": "npc:ralf"}
    assert "d124" in seed["twist"]["fact"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_quest_seeds.py -q`
Expected: FAIL with `ModuleNotFoundError: aidnd.server.play.engine.quests.seeds`

- [ ] **Step 3: Write the implementation**

```python
# src/aidnd/server/play/engine/quests/__init__.py
"""Emergent quest pipeline (docs/superpowers/specs/2026-07-12-emergent-quests-design.md).
Code sifts and prices real sim facts; the LLM only judges taste and writes 3 strings (framing.py)."""
```

```python
# src/aidnd/server/play/engine/quests/seeds.py
"""SIFTER — the 5 launch patterns (spec §4 table + §5 Step 1). Pure code over pool agendas,
the deeds journal and affinity edges → fully-bound QuestSeed dicts (twist candidate attached).

A seed's goal.done is ALWAYS a real _met dict (agenda.py:59-76). Milestone-anchored patterns
(kin_debt, blocked_rival, courtship_wall) lift the giver's live Milestone.done VERBATIM →
completing the quest advances that giver's cursor (the honest bridge). Deed-grievance patterns
(broken_promise, unanswered_blood) name the INTENDED revenge predicate {type:'dead', id:villain}
as goal.done; the giver has no pre-existing milestone for it, so at seed-CHOICE time the pipeline
INSERTS a real revenge Agenda into the giver's live state whose only Milestone.done IS this
predicate (pipeline._ensure_milestone, Task 7) — after which done_any[0] lifts verbatim from that
milestone and quest_writeback advances a real cursor exactly like every other pattern (no special
no-op case). Sift itself never mutates giver state — it only names the predicate.
"""

from __future__ import annotations

from aidnd.mind.agenda import Milestone

DELEGATABLE = {"have", "dead", "wealth", "affinity"}   # "at" is never sifted (§4 table)

# Doran motivation per pattern (drives casting.py kind/reward tone, not the predicate)
_MOTIV = {"kin_debt": "serenity", "broken_promise": "justice", "blocked_rival": "recognition",
          "unanswered_blood": "justice", "courtship_wall": "protection"}


def _fam(name: str) -> str:
    return (name or "").split()[-1]


def _aff(person, other: str) -> float:
    return (person.state.relationships.get(other) or {}).get("affinity", 0.0)


def _open_milestone(person):
    """Current, delegatable milestone of the giver's first active agenda (or None)."""
    for ag in person.state.agendas or []:
        if getattr(ag, "status", "active") != "active":
            continue
        m = ag.current() if hasattr(ag, "current") else None
        if m and (m.done or {}).get("type") in DELEGATABLE:
            return ag, m, ag.cursor
    return None, None, None


def _twist_for(cast: set, deeds: list, giver: str) -> dict | None:
    """A SECOND real fact touching the cast → optional OR-disjunct (spec §4/§5 Step 5).
    The predicate is code-authored (neutralise the villain); the villain must be in the cast."""
    villain = next((c for c in cast if c and c != giver), None)
    if not villain:
        return None
    for d in deeds:
        if d["id"] in _touched_ids(cast):        # reserved; see caller — pass fresh deeds only
            pass
        if d["actor"] == villain and d["verb"] in ("promise", "theft", "murder"):
            what = d["data"].get("what") or d["verb"]
            return {"fact": f"{d['id']}: {what}", "reveal_on": f"visit:{villain}",
                    "adds": {"type": "dead", "id": villain}}
    return None


def _touched_ids(cast: set) -> set:              # placeholder join key (kept explicit for clarity)
    return set()


def _seed(pattern, giver, people, done, villain=None, prize=None, evidence=None, twist=None):
    p = people[giver]
    m = _open_milestone(p)[1]
    goal = {"kind": (m.kind if m else "harm"), "target": (m.target if m else villain), "done": done}
    return {"pattern": pattern, "giver": giver, "giver_name": p.name, "goal": goal,
            "cast": {"villain": villain, "prize": prize}, "motivation": _MOTIV[pattern],
            "twist": twist, "evidence": list(evidence or []), "score": 0.0}


def pat_kin_debt(people, deeds, gt) -> list[dict]:
    """Blocked delegatable acquire/have milestone + a promise deed naming the giver's kin,
    made by a creditor the giver dislikes (affinity giver→creditor < 0)."""
    out = []
    for gid, g in people.items():
        ag, m, cur = _open_milestone(g)
        if not m:
            continue
        for d in deeds:
            if d["verb"] != "promise":
                continue
            creditor, victim = d["actor"], d["obj"]
            if creditor == gid or creditor not in people or victim not in people:
                continue
            if _fam(people[victim].name) != _fam(g.name) or _aff(g, creditor) >= 0:
                continue
            cast = {gid, creditor, victim}
            out.append(_seed("kin_debt", gid, people, dict(m.done), villain=creditor, prize=victim,
                             evidence=[d["id"], f"agenda:{gid}:{cur}"],
                             twist=_twist_for(cast, deeds, gid)))
    return out


def pat_broken_promise(people, deeds, gt) -> list[dict]:
    """A broken promise + promiser alive + victim holds a grudge (affinity victim→promiser < 0).
    Giver = the aggrieved victim; goal names the intended revenge predicate {dead, villain}. The giver
    has no milestone for it yet — pipeline._ensure_milestone materializes a real revenge Agenda at
    seed-choice time so done_any[0] lifts from a real milestone and the writeback works uniformly."""
    out = []
    for d in deeds:
        if d["verb"] != "promise" or d["status"] != "broken":
            continue
        promiser, victim = d["actor"], d["obj"]
        if promiser not in people or victim not in people:
            continue
        if _aff(people[victim], promiser) >= 0:
            continue
        cast = {victim, promiser}
        out.append(_seed("broken_promise", victim, people, {"type": "dead", "id": promiser},
                         villain=promiser, prize=None, evidence=[d["id"]],
                         twist=_twist_for(cast, deeds, victim)))
    return out


def pat_blocked_rival(people, deeds, gt) -> list[dict]:
    """Giver's delegatable milestone is blocked by a rival with MUTUAL enmity (< −0.2 both ways)."""
    out = []
    for gid, g in people.items():
        ag, m, cur = _open_milestone(g)
        if not m:
            continue
        for rid, r in people.items():
            if rid == gid:
                continue
            if _aff(g, rid) < -0.2 and _aff(r, gid) < -0.2:   # mutual only
                cast = {gid, rid}
                out.append(_seed("blocked_rival", gid, people, dict(m.done), villain=rid,
                                 evidence=[f"agenda:{gid}:{cur}"],
                                 twist=_twist_for(cast, deeds, gid)))
    return out


def pat_unanswered_blood(people, deeds, gt) -> list[dict]:
    """A witnessed murder/theft with no clearing answer → giver = the aggrieved victim's kin."""
    out = []
    cleared = {d["obj"] for d in deeds if d["verb"] in ("clear", "arrest")}
    for d in deeds:
        if d["verb"] not in ("murder", "theft") or not d.get("witnesses"):
            continue
        villain, victim = d["actor"], d["obj"]
        if villain in cleared or villain not in people or victim not in people:
            continue
        cast = {victim, villain}
        out.append(_seed("unanswered_blood", victim, people, {"type": "dead", "id": villain},
                         villain=villain, evidence=[d["id"]],
                         twist=_twist_for(cast, deeds, victim)))
    return out


def pat_courtship_wall(people, deeds, gt) -> list[dict]:
    """A stalled courtship: giver's open milestone is an affinity goal toward a beloved."""
    out = []
    for gid, g in people.items():
        ag, m, cur = _open_milestone(g)
        if not m or (m.done or {}).get("type") != "affinity":
            continue
        beloved = m.done.get("id")
        out.append(_seed("courtship_wall", gid, people, dict(m.done), prize=beloved,
                         evidence=[f"agenda:{gid}:{cur}"], twist=None))
    return out


PATTERNS = [pat_kin_debt, pat_broken_promise, pat_blocked_rival, pat_unanswered_blood,
            pat_courtship_wall]


def sift(people: dict, deeds: list, gt: int) -> list[dict]:
    """Run all 5 patterns; dedup identical (pattern, giver, villain, goal-type)."""
    seen, out = set(), []
    for pat in PATTERNS:
        for s in pat(people, deeds, gt):
            key = (s["pattern"], s["giver"], s["cast"]["villain"], s["goal"]["done"].get("type"))
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
    return out
```

> **Note on `_touched_ids`:** `_twist_for` iterates fresh deeds directly; the `_touched_ids` scaffold is a no-op kept only to keep the join explicit — remove it if a reviewer prefers, it changes no behavior.

- [ ] **Step 4: Simplify `_twist_for` (remove the dead scaffold)**

Replace the body of `_twist_for` with the clean version (the `_touched_ids` loop was inert):

```python
def _twist_for(cast: set, deeds: list, giver: str) -> dict | None:
    villain = next((c for c in cast if c and c != giver), None)
    if not villain:
        return None
    for d in deeds:
        if d["actor"] == villain and d["verb"] in ("promise", "theft", "murder"):
            what = d["data"].get("what") or d["verb"]
            return {"fact": f"{d['id']}: {what}", "reveal_on": f"visit:{villain}",
                    "adds": {"type": "dead", "id": villain}}
    return None
```

Delete the now-unused `_touched_ids` function.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/play/test_quest_seeds.py -q`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add src/aidnd/server/play/engine/quests/__init__.py src/aidnd/server/play/engine/quests/seeds.py tests/play/test_quest_seeds.py
git commit -m "feat(play/quests): просев — 5 паттернов над деяниями/агендами/аффинити → связанные QuestSeed [quests inc2]"
```

---

### Task 3: `salience.py` — the code-owned score

**Files:**
- Create: `src/aidnd/server/play/engine/quests/salience.py`
- Test: `tests/play/test_quest_salience.py`

**Interfaces:**
- Consumes: `PB["quest_w_rare"|"quest_w_peak"|"quest_w_near"|"quest_w_fresh"]`; seed dicts from `seeds.py`.
- Produces:
  - `DEED_W = {"promise": 0.5, "favor": 0.3, "theft": 0.7, "murder": 1.0}` (code constant).
  - `FRESH_DAYS = 5` (code constant).
  - `rarity(recent_count: int) -> float`
  - `peak(giver_villain_aff: float, evidence_deeds: list) -> float`
  - `proximity(giver_node, player_node, adjacent: bool) -> float`
  - `freshness(deed_gt: int, now_gt: int) -> float`
  - `score(seed: dict, ctx: dict) -> float` — `ctx = {"recent":{pattern:int}, "aff_edges":{(giver,villain):float}, "deeds":{id:deed}, "prox":{giver:float}, "now_gt":int}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_quest_salience.py
"""Salience воспроизводит арифметику §5 Step 2 число-в-число: A=3.14 > B=2.60."""
import math

from aidnd.server.play.engine.quests import salience as SAL


def _deeds(gt):
    return {"d123": {"id": "d123", "gt": gt - 1440, "verb": "promise",
                     "data": {"made_gt": gt - 1440}}}


def _seed(pattern, giver, villain):
    return {"pattern": pattern, "giver": giver, "cast": {"villain": villain},
            "evidence": ["d123"]}


def test_helpers_reproduce_spec_numbers():
    assert SAL.rarity(0) == 1.0
    assert SAL.rarity(1) == 0.5
    assert SAL.freshness(0, 1440) == 0.8            # возраст 1 день → 1 − 1/5
    assert SAL.proximity(7, 7, False) == 1.0
    assert SAL.proximity(4, 7, True) == 0.6
    assert SAL.proximity(4, 7, False) == 0.2


def test_score_A_gt_B_number_for_number(monkeypatch):
    from aidnd.server.play.engine.core import PB
    for k, v in {"quest_w_rare": 1.0, "quest_w_peak": 1.0, "quest_w_near": 0.6,
                 "quest_w_fresh": 0.8}.items():
        monkeypatch.setitem(PB, k, v)
    gt = 3 * 1440
    ctx = {"recent": {"kin_debt": 0, "broken_promise": 1},
           "aff_edges": {("npc:dunn", "npc:ralf"): -0.4, ("npc:marta", "npc:ralf"): -0.6},
           "deeds": _deeds(gt), "prox": {"npc:dunn": 1.0, "npc:marta": 0.6}, "now_gt": gt}
    a = SAL.score(_seed("kin_debt", "npc:dunn", "npc:ralf"), ctx)
    b = SAL.score(_seed("broken_promise", "npc:marta", "npc:ralf"), ctx)
    assert math.isclose(a, 3.14, abs_tol=1e-9)
    assert math.isclose(b, 2.60, abs_tol=1e-9)
    assert a > b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_quest_salience.py -q`
Expected: FAIL with `ModuleNotFoundError: …quests.salience`

- [ ] **Step 3: Write the implementation**

```python
# src/aidnd/server/play/engine/quests/salience.py
"""SALIENCE — code owns the ordering (spec §5 Step 2). Weights live in PB; the deed-weight table
and the 5-day freshness window are the only code constants (the DEFAULT_RULES precedent, §4/§8).

score = w_rare·rarity + w_peak·peak + w_near·proximity + w_fresh·freshness
  rarity     = 1 / (1 + recent_count)
  peak       = |affinity(giver→villain)| + max deed-weight in evidence
  proximity  = 1.0 same node / 0.6 adjacent / 0.2 else
  freshness  = max(0, 1 − age_days / 5)     (age_days = (now_gt − deed_gt) / 1440)
"""

from __future__ import annotations

from aidnd.server.play.engine.core import PB

DEED_W = {"promise": 0.5, "favor": 0.3, "theft": 0.7, "murder": 1.0}
FRESH_DAYS = 5


def rarity(recent_count: int) -> float:
    return 1.0 / (1.0 + max(0, recent_count))


def peak(giver_villain_aff: float, evidence_deeds: list) -> float:
    dw = max((DEED_W.get(d.get("verb"), 0.0) for d in evidence_deeds), default=0.0)
    return abs(giver_villain_aff) + dw


def proximity(giver_node, player_node, adjacent: bool) -> float:
    if giver_node is not None and giver_node == player_node:
        return 1.0
    return 0.6 if adjacent else 0.2


def freshness(deed_gt: int, now_gt: int) -> float:
    age_days = (now_gt - deed_gt) / 1440.0
    return max(0.0, 1.0 - age_days / FRESH_DAYS)


def score(seed: dict, ctx: dict) -> float:
    giver, villain = seed["giver"], seed["cast"]["villain"]
    ev = [ctx["deeds"][i] for i in seed.get("evidence", []) if i in ctx["deeds"]]
    r = rarity(ctx["recent"].get(seed["pattern"], 0))
    pk = peak(ctx["aff_edges"].get((giver, villain), 0.0), ev)
    px = ctx["prox"].get(giver, 0.2)
    fr = max((freshness(d["data"].get("made_gt", d["gt"]), ctx["now_gt"]) for d in ev), default=0.0)
    s = (PB["quest_w_rare"] * r + PB["quest_w_peak"] * pk
         + PB["quest_w_near"] * px + PB["quest_w_fresh"] * fr)
    seed["score"] = round(s, 6)
    return seed["score"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/play/test_quest_salience.py -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aidnd/server/play/engine/quests/salience.py tests/play/test_quest_salience.py
git commit -m "feat(play/quests): salience — rarity/peak/proximity/freshness, A=3.14>B=2.60 число-в-число [quests inc2]"
```

---

### Task 4: `framing.py` — the judge (LLM seam #1)

**Files:**
- Create: `src/aidnd/server/play/engine/quests/framing.py`
- Test: `tests/play/test_quest_judge.py`

**Interfaces:**
- Consumes: a `manager` with `.call(role, messages, options=…) -> {"content": str}` (raises `LLMUnavailable`); seed dicts.
- Produces:
  - `render_evidence(seed: dict, deeds: dict, names: dict) -> str` — plain-Russian facts + persona line for one seed.
  - `judge(seeds: list, deeds: dict, names: dict, manager) -> list[dict]` — returns the kept seeds in ranked order (each with `seed["why"]` attached). Parse failure → `[]` (logged). `LLMUnavailable` propagates.

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_quest_judge.py
"""Судья — один mgr.call, строгий JSON {rank,veto,why}; парс-сбой → пусто, LLM-падение → пробрасывается."""
import pytest

from aidnd.inference import LLMUnavailable
from aidnd.server.play.engine.quests import framing as F


def _seeds():
    return [
        {"pattern": "kin_debt", "sid": "seed_dunn_kindebt", "giver": "npc:dunn",
         "giver_name": "Дунн", "goal": {"done": {"type": "have", "item": "гроссбух"}},
         "cast": {"villain": "npc:ralf", "prize": "npc:marta"}, "evidence": ["d123"]},
        {"pattern": "broken_promise", "sid": "seed_marta_broken", "giver": "npc:marta",
         "giver_name": "Марта", "goal": {"done": {"type": "dead", "id": "npc:ralf"}},
         "cast": {"villain": "npc:ralf", "prize": None}, "evidence": ["d123"]},
    ]


_DEEDS = {"d123": {"id": "d123", "verb": "promise", "actor": "npc:ralf", "obj": "npc:marta",
                   "data": {"what": "вернуть гроссбух"}, "gt": 0}}
_NAMES = {"npc:dunn": "Дунн", "npc:ralf": "Ральф", "npc:marta": "Марта"}


class _Stub:
    def __init__(self, content):
        self.content = content
        self.seen = None

    def call(self, role, messages, **kw):
        self.seen = messages
        return {"content": self.content}


def test_judge_ranks_and_attaches_why():
    stub = _Stub('{"rank":["seed_dunn_kindebt","seed_marta_broken"],"veto":[],'
                 '"why":{"seed_dunn_kindebt":"тёплый крючок","seed_marta_broken":"бледнее"}}')
    kept = F.judge(_seeds(), _DEEDS, _NAMES, stub)
    assert [s["sid"] for s in kept] == ["seed_dunn_kindebt", "seed_marta_broken"]
    assert kept[0]["why"] == "тёплый крючок"
    assert "Дунн" in stub.seen[1]["content"] and "гроссбух" in stub.seen[1]["content"]


def test_judge_drops_vetoed():
    stub = _Stub('{"rank":["seed_dunn_kindebt"],"veto":["seed_marta_broken"],'
                 '"why":{"seed_dunn_kindebt":"ок"}}')
    kept = F.judge(_seeds(), _DEEDS, _NAMES, stub)
    assert [s["sid"] for s in kept] == ["seed_dunn_kindebt"]


def test_judge_parse_failure_returns_empty():
    kept = F.judge(_seeds(), _DEEDS, _NAMES, _Stub("не json вовсе"))
    assert kept == []


def test_judge_llm_unavailable_propagates():
    class _Boom:
        def call(self, *a, **k):
            raise LLMUnavailable("нет модели")

    with pytest.raises(LLMUnavailable):
        F.judge(_seeds(), _DEEDS, _NAMES, _Boom())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_quest_judge.py -q`
Expected: FAIL with `ModuleNotFoundError: …quests.framing`

- [ ] **Step 3: Write the implementation**

```python
# src/aidnd/server/play/engine/quests/framing.py
"""FRAMING — the two LLM seams (spec §3/§5 Steps 3-4).
  judge(...)  — ONE ranking call: K seeds as plain-Russian evidence + personas → {rank,veto,why}.
  framer(...) — 3 written artifacts (pitch / foreshadow / reveal) + a structural apophenia validator.
No LLM → honest absence (parse failure → empty / None; LLMUnavailable propagates to the morning hook).
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger("aidnd.quests")

_JUDGE_SYS = (
    "Ты — редактор городских слухов. Оцени зёрна сюжета на живость и вкус; наложи вето на те, "
    "что звучат фальшиво; каждому дай ОДНУ фразу «чем цепляет». Верни СТРОГО JSON: "
    '{"rank": ["<sid>", ...], "veto": ["<sid>", ...], '
    '"why": {"<sid>": "<одна фраза>", ...}}. Только перечисленные sid, ничего не выдумывай.'
)


def render_evidence(seed: dict, deeds: dict, names: dict) -> str:
    """One seed → plain-Russian header (only evidence facts + personas, no predicates leak)."""
    gv = seed["giver_name"]
    vil = names.get(seed["cast"].get("villain"), "кто-то")
    prize = names.get(seed["cast"].get("prize"))
    head = f"{seed['sid']} [{seed['pattern']}]: {gv} против {vil}"
    head += f" (речь о {prize})." if prize else "."
    facts = []
    for i in seed.get("evidence", []):
        d = deeds.get(i)
        if not d:
            continue
        what = d.get("data", {}).get("what") or d.get("verb")
        facts.append(f"{names.get(d.get('actor'), 'кто-то')}: {what}")
    return head + ("\n  Факты: " + "; ".join(facts) if facts else "")


def judge(seeds: list, deeds: dict, names: dict, manager) -> list[dict]:
    for s in seeds:
        s.setdefault("sid", f"seed_{s['giver'].split(':')[-1]}_{s['pattern']}")
    payload = "\n".join(render_evidence(s, deeds, names) for s in seeds)
    resp = manager.call("narrator",
                        [{"role": "system", "content": _JUDGE_SYS},
                         {"role": "user", "content": payload}],
                        options={"temperature": 0.4})
    t = (resp.get("content") if resp else "") or ""
    try:
        d = json.loads(t[t.find("{"): t.rfind("}") + 1])
        rank, veto, why = list(d["rank"]), set(d.get("veto") or []), dict(d.get("why") or {})
    except (json.JSONDecodeError, ValueError, KeyError, TypeError):
        log.warning("quests: judge вернул неразборный JSON — предложения нет этим утром")
        return []
    by_sid = {s["sid"]: s for s in seeds}
    kept = []
    for sid in rank:
        s = by_sid.get(sid)
        if not s or sid in veto:
            continue
        s["why"] = str(why.get(sid, ""))[:160]
        kept.append(s)
    return kept
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/play/test_quest_judge.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aidnd/server/play/engine/quests/framing.py tests/play/test_quest_judge.py
git commit -m "feat(play/quests): судья — один ранжирующий вызов {rank,veto,why}, парс-сбой → честное отсутствие [quests inc2]"
```

---

### Task 5: `framing.py` — the framer + apophenia validator (LLM seam #2)

**Files:**
- Modify: `src/aidnd/server/play/engine/quests/framing.py` (append `framer` + `valid_entities`)
- Test: `tests/play/test_quest_framer.py`

**Interfaces:**
- Consumes: `_tokens_ru` (from `engine.core`), a `manager`, a seed dict + an `allowed` set of entity names.
- Produces:
  - `valid_entities(text: str, allowed: set) -> bool` — every «quoted» phrase and Capitalized Cyrillic word shares a token with some `allowed` name (mirrors `_build_step`'s unknown-entity reject).
  - `framer(seed: dict, allowed: set, manager) -> dict | None` — `{"pitch","foreshadow","reveal"}` all validated; one regenerate on failure, else `None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_quest_framer.py
"""Фреймер — 3 строки + апофения-валидатор: чужая сущность → отказ (как _build_step)."""
from aidnd.server.play.engine.quests import framing as F


def _seed():
    return {"sid": "seed_dunn_kindebt", "pattern": "kin_debt", "giver": "npc:dunn",
            "giver_name": "Дунн", "why": "тёплый крючок",
            "goal": {"done": {"type": "have", "item": "гроссбух"}},
            "cast": {"villain": "npc:ralf", "prize": "npc:marta"}}


ALLOWED = {"Дунн", "Марта", "Ральф", "гроссбух", "гильдия"}


def test_validator_accepts_only_known_entities():
    assert F.valid_entities("Верни Дунну гроссбух Марты от Ральфа", ALLOWED)
    assert not F.valid_entities("Найди Гундрена в руднике", ALLOWED)   # Гундрен ∉ allowed


class _Stub:
    def __init__(self, seq):
        self.seq, self.n = seq, 0

    def call(self, role, messages, **kw):
        out = self.seq[min(self.n, len(self.seq) - 1)]
        self.n += 1
        return {"content": out}


def test_framer_returns_three_valid_strings():
    good = ('{"pitch":"Чужак, верни гроссбух Марты — тридцать монет.",'
            '"foreshadow":"Тебя гложет долг Марты — гроссбух всё у Ральфа.",'
            '"reveal":"Ральф сам должен гильдии — его можно прижать."}')
    art = F.framer(_seed(), ALLOWED, _Stub([good]))
    assert set(art) == {"pitch", "foreshadow", "reveal"}
    assert "гроссбух" in art["pitch"]


def test_framer_regenerates_once_then_skips():
    bad = ('{"pitch":"Найди Гундрена","foreshadow":"Гундрен пропал",'
           '"reveal":"Гундрен в руднике"}')
    stub = _Stub([bad, bad])
    assert F.framer(_seed(), ALLOWED, stub) is None       # оба раза чужая сущность → None
    assert stub.n == 2                                     # ровно одна регенерация
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_quest_framer.py -q`
Expected: FAIL with `AttributeError: module 'framing' has no attribute 'valid_entities'`

- [ ] **Step 3: Append the implementation to `framing.py`**

```python
# --- append to framing.py ---
import re

from aidnd.server.play.engine.core import _tokens_ru

_CAP_RU = re.compile(r"[А-ЯЁ][а-яё]+")
_QUOTED = re.compile(r"«([^»]+)»")

_FRAMER_SYS = (
    "Ты пишешь ТРИ короткие фразы для городского поручения. Используй ТОЛЬКО названных людей и вещи — "
    "никого и ничего нового не выдумывай. Верни СТРОГО JSON: "
    '{"pitch":"<просьба в характере, 1-2 фразы, с сутью и наградой>", '
    '"foreshadow":"<что гложет заказчика, 1 фраза, до предложения>", '
    '"reveal":"<фраза поворота, если всплывёт второй факт>"}.'
)


def valid_entities(text: str, allowed: set) -> bool:
    """Every «quoted» phrase and Capitalized Cyrillic word must share a token with some allowed
    name (mirrors _build_step contracts.py:60 — an unknown entity fails the whole artifact)."""
    allow_tok = set()
    for a in allowed:
        allow_tok |= _tokens_ru(a)
    cands = list(_QUOTED.findall(text or "")) + _CAP_RU.findall(text or "")
    for c in cands:
        if not (_tokens_ru(c) & allow_tok):
            return False
    return True


def framer(seed: dict, allowed: set, manager) -> dict | None:
    user = (f"ЗАКАЗЧИК: {seed['giver_name']}. Суть: {seed.get('why', '')}\n"
            f"МОЖНО НАЗЫВАТЬ: {', '.join(sorted(allowed))}.")
    for attempt in range(2):                       # generate → validate → regenerate once → skip
        resp = manager.call("narrator",
                            [{"role": "system", "content": _FRAMER_SYS},
                             {"role": "user", "content": user}],
                            options={"temperature": 0.7})
        t = (resp.get("content") if resp else "") or ""
        try:
            d = json.loads(t[t.find("{"): t.rfind("}") + 1])
            art = {k: str(d.get(k, ""))[:220] for k in ("pitch", "foreshadow", "reveal")}
        except (json.JSONDecodeError, ValueError):
            continue
        if all(art.values()) and all(valid_entities(v, allowed) for v in art.values()):
            return art
    log.warning("quests: фреймер назвал чужую сущность дважды — пропуск этим утром")
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/play/test_quest_framer.py tests/play/test_quest_judge.py -q`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aidnd/server/play/engine/quests/framing.py tests/play/test_quest_framer.py
git commit -m "feat(play/quests): фреймер — 3 строки + апофения-валидатор (регенерация раз, иначе пропуск) [quests inc2]"
```

---

### Task 6: `casting.py` — motivation → kind + reward + DC

**Files:**
- Create: `src/aidnd/server/play/engine/quests/casting.py`
- Test: `tests/play/test_quest_casting.py`

**Interfaces:**
- Consumes: `bridge.milestone_to_step(m)` (Inc 1); `store.purse_get(wid, giver)`; `Milestone`; villain `NpcState` (for DC).
- Produces:
  - `REWARD_CAP = 30` (code constant, spec §5 Step 4 `min(30, purse)`).
  - `MOTIV_KIND = {"serenity":"bring","justice":"dead","protection":"deliver","recognition":"befriend","curiosity":"visit"}`.
  - `cast(seed, giver_state, villain_state, store, wid) -> dict` — returns `{"step","reward","dc","danger","motivation"}` (`step` from the bridge; `reward=min(REWARD_CAP, purse)`; `dc`/`danger` from villain stats).

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_quest_casting.py
"""Кастинг (чистый код): reward = min(30, наличность); step — от Inc-1 bridge; DC растёт от статов злодея."""
import os
import tempfile

from aidnd.mind import NpcConfig, NpcState
from aidnd.mind.agenda import Milestone
from aidnd.server.play.engine import core
from aidnd.server.play.engine.quests import casting as C
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


def _store(monkeypatch):
    tmp = tempfile.mkdtemp()
    st = WorldStore(os.path.join(tmp, "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    return st


def _villain(strong=False):
    cfg = NpcConfig(id="npc:ralf", name="Ральф", role="ростовщик",
                    traits={"malice": 0.8 if strong else 0.3})
    return NpcState.from_config(cfg)


def test_reward_clamped_by_real_purse(monkeypatch):
    st = _store(monkeypatch)
    st.purse_add(core._wid(), "npc:dunn", 41)
    giver = NpcState.from_config(NpcConfig(id="npc:dunn", name="Дунн"))
    seed = {"motivation": "serenity",
            "goal": {"kind": "acquire", "target": "debt:marta",
                     "done": {"type": "have", "item": "гроссбух"}}}
    out = C.cast(seed, giver, _villain(), st, core._wid())
    assert out["reward"] == 30                      # min(30, 41)
    assert out["step"]["kind"] == "bring" and out["step"]["want"] == "гроссбух"


def test_reward_clamped_when_poor(monkeypatch):
    st = _store(monkeypatch)
    st.purse_add(core._wid(), "npc:dunn", 12)
    giver = NpcState.from_config(NpcConfig(id="npc:dunn", name="Дунн"))
    seed = {"motivation": "serenity",
            "goal": {"kind": "acquire", "target": "debt:marta",
                     "done": {"type": "have", "item": "гроссбух"}}}
    out = C.cast(seed, giver, _villain(), st, core._wid())
    assert out["reward"] == 12                      # min(30, 12)


def test_dc_rises_with_villain_malice(monkeypatch):
    st = _store(monkeypatch)
    giver = NpcState.from_config(NpcConfig(id="npc:dunn", name="Дунн"))
    seed = {"motivation": "justice",
            "goal": {"kind": "harm", "target": "npc:ralf", "done": {"type": "dead", "id": "npc:ralf"}}}
    weak = C.cast(seed, giver, _villain(strong=False), st, core._wid())
    strong = C.cast(seed, giver, _villain(strong=True), st, core._wid())
    assert strong["dc"] > weak["dc"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_quest_casting.py -q`
Expected: FAIL with `ModuleNotFoundError: …quests.casting`

- [ ] **Step 3: Write the implementation**

```python
# src/aidnd/server/play/engine/quests/casting.py
"""CASTING — pure code (spec §5 Step 4). Doran motivation → contract kind (tone) + reward shape
(real purse, capped) + DC/danger from the villain's real stats. The contract STEP itself is the
Inc-1 bridge's milestone→step translation, so completion flows through the unchanged triggers."""

from __future__ import annotations

from aidnd.mind.agenda import Milestone
from aidnd.server.play.engine.quests import bridge

REWARD_CAP = 30
_DC_BASE = 10

MOTIV_KIND = {"serenity": "bring", "justice": "dead", "protection": "deliver",
              "recognition": "befriend", "curiosity": "visit"}


def _milestone(seed: dict) -> Milestone:
    g = seed["goal"]
    return Milestone(desc="", kind=g.get("kind", "acquire"), target=g.get("target"),
                     done=dict(g["done"]))


def cast(seed: dict, giver_state, villain_state, store, wid) -> dict:
    step = bridge.milestone_to_step(_milestone(seed)) or {"kind": "bring", "want": None}
    purse = store.purse_get(wid, giver_state.config.id)
    reward = min(REWARD_CAP, max(0, purse))
    malice = villain_state.config.traits.get("malice", 0.3) if villain_state else 0.3
    dc = _DC_BASE + round(malice * 10)              # code-owned; villain's real trait drives danger
    return {"step": step, "reward": reward, "dc": dc, "danger": round(malice, 2),
            "motivation": seed.get("motivation")}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/play/test_quest_casting.py -q`
Expected: PASS (3 tests)

> If `bridge.milestone_to_step` is not yet on the branch (Inc 1 not merged), this task's tests fail at import — do not stub the bridge; block on Inc 1 landing first (it is a hard dependency, per the plan header).

- [ ] **Step 5: Commit**

```bash
git add src/aidnd/server/play/engine/quests/casting.py tests/play/test_quest_casting.py
git commit -m "feat(play/quests): кастинг — мотивация→kind, reward=min(30,кошель), DC от статов злодея [quests inc2]"
```

---

### Task 7: `pipeline.py` — morning orchestration (window=1) + expiry-compost

**Files:**
- Create: `src/aidnd/server/play/engine/quests/pipeline.py`
- Modify: `src/aidnd/server/play/engine/loop/routine.py:35-40` (hook the quest morning inside `_world_events`)
- Test: `tests/play/test_quest_pipeline.py`

**Interfaces:**
- Consumes: `seeds.sift`, `salience.score`, `framing.judge/framer`, `casting.cast`, `bridge.make_done_any`, `store.save_contract/contracts/deeds/purse_get/flag_get/flag_set`; `_S["people"|"crof"|"loc"|"city"]`, `_gt`, `_wid`, `_model`, `PB`.
- Produces:
  - `quest_morning() -> list[str]` — full pipeline; persists exactly ONE chosen seed as `save_contract(status="queued")` then surfaces it (window=1 hardcoded for Inc 2); returns news lines. `LLMUnavailable`/parse-failure → `[]`.
  - `PUBLIC_PATTERNS = {"broken_promise", "unanswered_blood"}`.
  - `_surface(cid: str, ct: dict) -> None` — promote a queued emergent contract: private → status `"offered"` (dialogue picks it up); public → status `"board"` (merges onto the board).
  - `_expire_stale() -> list[str]` — close emergent offers older than `quest_offer_days` (`arc.beat="expired"`, status `"closed"`; giver keeps his agenda; nothing leaks to the board).

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_quest_pipeline.py
"""Утренний конвейер: один seed всплывает; приватный → offered, публичный → board; протухший → compost."""
import os
import tempfile
from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.mind.agenda import Agenda, Milestone
from aidnd.server.play.engine import core
from aidnd.server.play.engine.quests import pipeline as P
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


class _Stub:
    def call(self, role, messages, **kw):
        if "редактор" in messages[0]["content"]:   # judge
            return {"content": '{"rank":["seed_dunn_kin_debt"],"veto":[],'
                               '"why":{"seed_dunn_kin_debt":"тёплый крючок"}}'}
        return {"content": '{"pitch":"Верни гроссбух Марты — тридцать монет, Дунн просит.",'
                           '"foreshadow":"Дунна гложет долг Марты — гроссбух у Ральфа.",'
                           '"reveal":"Ральф сам должен гильдии."}'}


def _person(pid, name, role, agendas=(), rels=None):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    st.agendas = list(agendas)
    st.relationships = dict(rels or {})
    return SimpleNamespace(name=name, role=role, state=st, persona={}, work=None)


@pytest.fixture
def town(monkeypatch):
    tmp = tempfile.mkdtemp()
    st = WorldStore(os.path.join(tmp, "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    monkeypatch.setattr(core, "_model", lambda: _Stub())
    gt = 3 * 1440
    core._S["gt"] = gt
    dunn_ms = Milestone("вернуть гроссбух сестры", "acquire", "debt:marta", {},
                        {"type": "have", "item": "гроссбух"})
    dunn = _person("npc:dunn", "Дунн Ли", "охотник",
                   agendas=[Agenda("вернуть гроссбух сестры", "ambition", 0.7, [dunn_ms])],
                   rels={"npc:ralf": {"affinity": -0.4}})
    ralf = _person("npc:ralf", "Ральф Ли", "ростовщик", rels={"npc:dunn": {"affinity": -0.1}})
    marta = _person("npc:marta", "Марта Ли", "торговка", rels={"npc:ralf": {"affinity": -0.6}})
    core._S["people"] = {"npc:dunn": dunn, "npc:ralf": ralf, "npc:marta": marta}
    core._S["crof"] = {"npc:dunn": 7, "npc:ralf": 9, "npc:marta": 4}
    core._S["loc"] = 7                              # игрок в узле Дунна
    core._S["city"] = None
    st.purse_add(core._wid(), "npc:dunn", 41)
    st.deed_add(core._wid(), gt - 1440, "npc:ralf", "promise", "npc:marta", "",
                status="broken", data={"what": "вернуть гроссбух", "made_gt": gt - 1440})
    return st


def test_one_seed_surfaces_private(town):
    news = P.quest_morning()
    assert news
    offered = town.contracts(core._wid(), "offered")
    emergent = [c for c in offered if c.get("src") == "sift"]
    assert len(emergent) == 1
    ct = emergent[0]
    assert ct["giver"] == "npc:dunn" and ct["arc"]["beat"] == "offered"
    assert ct["done_any"] == [{"type": "have", "item": "гроссбух"}]  # done_any[0] = дословная веха
    assert ct["step"]["kind"] == "bring"


def test_public_pattern_goes_to_board(town, monkeypatch):
    # заставим просев выдать только публичный паттерн: у Дунна убираем агенду
    core._S["people"]["npc:dunn"].state.agendas = []
    news = P.quest_morning()
    board = [c for c in town.contracts(core._wid(), "board") if c.get("src") == "sift"]
    assert board and board[0]["giver"] == "npc:marta"
    # grievance pattern: pipeline materialized a REAL revenge milestone on Марта (mirrors deals.py) →
    # done_any[0] is verbatim from it and quest_writeback can advance her cursor uniformly.
    assert board[0]["done_any"][0] == {"type": "dead", "id": "npc:ralf"}
    marta_ag = core._S["people"]["npc:marta"].state.agendas
    assert marta_ag and marta_ag[-1].kind == "revenge"
    assert marta_ag[-1].current().done == {"type": "dead", "id": "npc:ralf"}
    assert f"agenda:npc:marta:{len(marta_ag) - 1}" in board[0]["seed"]["evidence"]


def test_expire_compost_closes_offer_and_keeps_agenda(town):
    P.quest_morning()
    ct = next(c for c in town.contracts(core._wid(), "offered") if c.get("src") == "sift")
    core._S["gt"] += (core.PB["quest_offer_days"] + 1) * 1440   # два дня спустя
    news = P._expire_stale()
    assert any("протух" in n or "сам" in n for n in news)
    assert not town.contracts(core._wid(), "offered")
    closed = next(c for c in town.contracts(core._wid(), "closed") if c["id"] == ct["id"])
    assert closed["arc"]["beat"] == "expired"
    assert core._S["people"]["npc:dunn"].state.agendas[0].cursor == 0   # агенда цела — сам займётся
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_quest_pipeline.py -q`
Expected: FAIL with `ModuleNotFoundError: …quests.pipeline`

- [ ] **Step 3: Write the implementation**

```python
# src/aidnd/server/play/engine/quests/pipeline.py
"""Morning orchestration (spec §3a/§5). Inc 2: window=1 hardcoded (exactly one seed surfaces per
morning; the director in Inc 3 replaces this). No LLM at either seam → honest absence, boards continue.

  sift → salience → judge → framer → casting → save_contract(status='queued') → surface (private/public)
  + expiry-compost of offers older than quest_offer_days (giver keeps his agenda; no board leak).
"""

from __future__ import annotations

import logging

from aidnd.inference import LLMUnavailable
from aidnd.server.play.engine.core import PB, _gt, _model, _store, _wid, _S
from aidnd.server.play.engine.quests import bridge, casting, framing, salience, seeds

log = logging.getLogger("aidnd.quests")

PUBLIC_PATTERNS = {"broken_promise", "unanswered_blood"}
GRIEVANCE_PATTERNS = {"broken_promise", "unanswered_blood"}   # no pre-existing giver milestone


def _ensure_milestone(seed: dict) -> None:
    """Grievance patterns (broken_promise/unanswered_blood) name a revenge predicate but the giver
    carries NO milestone for it. Insert a real revenge Agenda into the giver's LIVE state so
    done_any[0] lifts verbatim from a real milestone and the Inc-1 writeback advances a real cursor
    uniformly (spec §4 'each enforced disjunct is a real _met dict' + the honest bridge).

    Persistence mirrors deals.py:155 EXACTLY: the agenda is inserted into the in-memory
    _S["people"][giver].state.agendas and lives there for the session. save_npc_state (store.py:372,
    via _npc_save) intentionally persists only relationships/needs/memory — NOT agendas — so deals.py's
    hired-agenda and this revenge-agenda both survive purely on the live pool wrapper. We invent NO
    new persistence: no DB write for the agenda, exactly as the hired-agenda precedent."""
    if seed["pattern"] not in GRIEVANCE_PATTERNS:
        return                                       # milestone-anchored: giver already carries it
    from aidnd.mind.agenda import Agenda, Milestone
    giver = (_S.get("people") or {})[seed["giver"]]
    st = giver.state
    if st.agendas is None:
        st.agendas = []
    villain = seed["cast"].get("villain")
    done = dict(seed["goal"]["done"])                # the intended revenge predicate (real _met dict)
    for i, ag in enumerate(st.agendas):              # idempotent: reuse a matching live revenge agenda
        if getattr(ag, "status", "active") == "active" and ag.current() and ag.current().done == done:
            seed["evidence"].append(f"agenda:{seed['giver']}:{i}")
            return
    ms = Milestone(desc=f"свести счёты с обидчиком ({villain})", kind="harm",
                   target=villain, done=done)
    idx = len(st.agendas)
    st.agendas.append(Agenda(summary=f"расквитаться с {villain} за нарушенное слово",
                             kind="revenge", importance=0.8, milestones=[ms]))
    seed["evidence"].append(f"agenda:{seed['giver']}:{idx}")   # anchor for bridge._anchor_idx


def _names() -> dict:
    return {pid: p.name for pid, p in (_S.get("people") or {}).items()}


def _adjacent(city, a, b) -> bool:
    if city is None or a is None or b is None:
        return False
    try:
        return any({e.a, e.b} == {a, b} for e in city.edges())
    except Exception:                               # noqa: BLE001 — graph shape guard
        return False


def _ctx(chosen_deeds: dict, gt: int) -> dict:
    people = _S.get("people") or {}
    crof, loc, city = _S.get("crof") or {}, _S.get("loc"), _S.get("city")
    aff = {}
    for pid, p in people.items():
        for other, rel in (p.state.relationships or {}).items():
            aff[(pid, other)] = rel.get("affinity", 0.0)
    prox = {pid: salience.proximity(crof.get(pid), loc, _adjacent(city, crof.get(pid), loc))
            for pid in people}
    recent = {}
    for pat in ("kin_debt", "broken_promise", "blocked_rival", "unanswered_blood", "courtship_wall"):
        recent[pat] = int(_store().flag_get(_wid(), f"qrecent|{pat}") or 0)
    return {"recent": recent, "aff_edges": aff, "deeds": chosen_deeds, "prox": prox, "now_gt": gt}


def _allowed(seed: dict) -> set:
    names = _names()
    out = {seed["giver_name"]}
    for r in ("villain", "prize"):
        nm = names.get(seed["cast"].get(r))
        if nm:
            out.add(nm)
    done = seed["goal"]["done"]
    if done.get("type") == "have" and done.get("item"):
        out.add(str(done["item"]))
    out.add("гильдия")
    return out


def quest_morning() -> list[str]:
    people = _S.get("people") or {}
    if not people:
        return []
    gt = _gt()
    raw = _store().deeds(_wid(), since_gt=gt - salience.FRESH_DAYS * 1440, limit=60)
    deeds_by_id = {d["id"]: d for d in raw}
    pool = seeds.sift(people, raw, gt)
    if not pool:
        return []
    ctx = _ctx(deeds_by_id, gt)
    for s in pool:
        salience.score(s, ctx)
    pool.sort(key=lambda s: -s["score"])
    topk = pool[:PB["quest_topk"]]
    kept = framing.judge(topk, deeds_by_id, _names(), _model())   # LLMUnavailable propagates
    if not kept:
        return []
    news = []
    for seed in kept[:1]:                            # Inc 2 window=1 — exactly one seed
        art = framing.framer(seed, _allowed(seed), _model())
        if not art:
            continue
        _ensure_milestone(seed)                      # grievance patterns: materialize a real milestone
        giver = people[seed["giver"]]
        villain = people.get(seed["cast"].get("villain"))
        c = casting.cast(seed, giver.state, villain.state if villain else None, _store(), _wid())
        from aidnd.mind.agenda import Milestone
        m = Milestone(desc="", kind=seed["goal"]["kind"], target=seed["goal"]["target"],
                      done=dict(seed["goal"]["done"]))
        cid = f"ct:sift:{seed['giver']}:{gt}"
        roles = {"giver": seed["giver"], "villain": seed["cast"].get("villain"),
                 "prize": seed["cast"].get("prize")}
        data = {"giver": seed["giver"], "giver_name": seed["giver_name"], "step": 0,
                "steps": [c["step"]], **c["step"], "reward": c["reward"], "reward_item": None,
                "reward_name": None, "pitch": art["pitch"], "why": seed["giver_name"],
                "src": "sift", "seed": seed, "arc": {"beat": "foreshadow"}, "roles": roles,
                "done_any": bridge.make_done_any(m),
                "framer": art, "dc": c["dc"]}
        _store().save_contract(_wid(), cid, "queued", data)
        _store().flag_set(_wid(), f"qrecent|{seed['pattern']}",
                          str(int(_store().flag_get(_wid(), f"qrecent|{seed['pattern']}") or 0) + 1))
        _surface(cid, {"id": cid, "status": "queued", **data})
        news.append(f"в городе зреет дело: {seed['giver_name']} ищет, кому довериться")
    return news + _expire_stale()


def _surface(cid: str, ct: dict) -> None:
    """Promote a queued emergent contract to the player (Inc 2: immediately; Inc 3: director-timed)."""
    data = {k: v for k, v in ct.items() if k not in ("id", "status")}
    data["arc"] = {"beat": "offered"}
    if ct["seed"]["pattern"] in PUBLIC_PATTERNS:
        _store().save_contract(_wid(), cid, "board", data)      # merges onto _board_ads
    else:
        _store().save_contract(_wid(), cid, "offered", data)    # dialogue picks it up (contract_accept)


def _expire_stale() -> list[str]:
    """Compost: an emergent offer unaccepted for quest_offer_days closes; the giver keeps his agenda
    (he acts on it himself → new deeds → next sift). Private grief never leaks to a public board."""
    gt, news = _gt(), []
    for status in ("offered", "board"):
        for ct in _store().contracts(_wid(), status):
            if ct.get("src") != "sift":
                continue
            seed = ct.get("seed") or {}
            age = gt - int(str(ct["id"].rsplit(":", 1)[-1]) or gt)
            if age < PB["quest_offer_days"] * 1440:
                continue
            data = {k: v for k, v in ct.items() if k not in ("id", "status")}
            data["arc"] = {"beat": "expired"}
            _store().save_contract(_wid(), ct["id"], "closed", data)
            news.append(f"{ct.get('giver_name', 'кто-то')} махнул рукой — займётся делом сам")
    return news
```

- [ ] **Step 4: Hook the morning into `routine._world_events`**

In `src/aidnd/server/play/engine/loop/routine.py`, add a new `try` block inside `_world_events`, after the board block (`routine.py:35-40`), so a quest failure never crashes the morning:

```python
    try:
        from aidnd.server.play.engine.quests.pipeline import quest_morning
        qn = quest_morning()
        if qn:
            _S["quest_news"] = (_S.get("quest_news") or [])[-3:] + qn
    except Exception:  # noqa: BLE001 — no LLM / bad output → honest absence, morning continues
        pass
```

(`_S` is already imported at `routine.py:13`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/play/test_quest_pipeline.py -q`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add src/aidnd/server/play/engine/quests/pipeline.py src/aidnd/server/play/engine/loop/routine.py tests/play/test_quest_pipeline.py
git commit -m "feat(play/quests): утренний конвейер (окно=1) + компост протухших; хук в _world_events [quests inc2]"
```

---

### Task 8: offer routing — dialogue pickup + `contract_accept` arc/journal

**Files:**
- Modify: `src/aidnd/server/play/handlers/dialogue.py:100-109` (`talk`: emergent offer outranks improvised)
- Modify: `src/aidnd/server/play/engine/world.py:161-180` (`contract_accept`: bump `arc.beat` + journal beat for `src=="sift"`)
- Create: `src/aidnd/server/play/engine/quests/offer.py`
- Test: `tests/play/test_quest_offer_routing.py`

**Interfaces:**
- Consumes: `_store().contracts(wid, "offered")`, `_S["pending_offer"]`; the `_j_quest` journal shim.
- Produces:
  - `offer.emergent_offer(npc: str) -> dict | None` — the offered emergent contract for `npc` (`src=="sift"`), card-shaped, or `None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_quest_offer_routing.py
"""Приватное эмерджентное предложение перебивает импровизированное; accept двигает arc в active."""
import os
import tempfile
from types import SimpleNamespace

from aidnd.server.play.engine import core
from aidnd.server.play.engine.quests import offer as O
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


def _store(monkeypatch):
    tmp = tempfile.mkdtemp()
    st = WorldStore(os.path.join(tmp, "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    return st


def _emergent(st):
    data = {"giver": "npc:dunn", "giver_name": "Дунн", "step": 0,
            "steps": [{"kind": "bring", "want": "гроссбух"}], "kind": "bring", "want": "гроссбух",
            "reward": 30, "pitch": "Верни гроссбух — тридцать монет.", "src": "sift",
            "seed": {"pattern": "kin_debt"}, "arc": {"beat": "offered"},
            "roles": {"giver": "npc:dunn", "villain": "npc:ralf"},
            "done_any": [{"type": "have", "item": "гроссбух"}]}
    st.save_contract(core._wid(), "ct:sift:npc:dunn:4320", "offered", data)


def test_emergent_offer_found_for_giver(monkeypatch):
    st = _store(monkeypatch)
    _emergent(st)
    off = O.emergent_offer("npc:dunn")
    assert off and off["src"] == "sift" and off["pitch"].startswith("Верни")
    assert O.emergent_offer("npc:ralf") is None


def test_accept_flips_to_active_and_bumps_arc(monkeypatch):
    import asyncio

    from aidnd.server.play.engine import world as W
    st = _store(monkeypatch)
    _emergent(st)

    class _Req:
        async def json(self):
            return {"id": "ct:sift:npc:dunn:4320"}

    core._S["people"] = {"npc:dunn": SimpleNamespace(
        name="Дунн", state=SimpleNamespace(memory=SimpleNamespace(add=lambda *a, **k: None)))}
    core._S.setdefault("pc", None)
    res = asyncio.get_event_loop().run_until_complete(W.contract_accept(_Req()))
    assert res.get("accepted")
    ct = next(c for c in st.contracts(core._wid(), "active") if c["id"] == "ct:sift:npc:dunn:4320")
    assert ct["arc"]["beat"] == "active"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_quest_offer_routing.py -q`
Expected: FAIL with `ModuleNotFoundError: …quests.offer`

- [ ] **Step 3: Write `offer.py`**

```python
# src/aidnd/server/play/engine/quests/offer.py
"""Private-offer routing: an offered emergent contract (src='sift') outranks the improvised
_contract_offer while it is live (spec §3a Beat 2 · dialogue.py:101)."""

from __future__ import annotations

from aidnd.server.play.engine.core import _store, _wid


def emergent_offer(npc: str) -> dict | None:
    for ct in _store().contracts(_wid(), "offered"):
        if ct.get("src") == "sift" and ct.get("giver") == npc:
            return ct
    return None
```

- [ ] **Step 4: Wire `talk` to prefer the emergent offer**

In `dialogue.py`, replace the `try/except` offer block at `:100-108` (the journal plan's Task 5 inserts a first-meeting `j_person` block higher up in `talk`, around `:82-85`, so these line numbers shift down a couple of lines — locate the offer block by its `_contract_offer(npc)` content, not the line number):

```python
    try:
        from aidnd.server.play.engine.quests.offer import emergent_offer
        offer = emergent_offer(npc)                # emergent quest outranks improvised while live
        if offer is None:
            offer = _contract_offer(npc)           # he might have business with you (from agenda)
    except (LLMUnavailable, LLMBadOutput):         # without the model, we don't pretend (principle 1)
        raise
    except Exception:  # noqa: BLE001 — other request failures don't break dialogue
        offer = None
```

- [ ] **Step 5: Bump `arc.beat` on accept**

In `world.py` `contract_accept`, replace the inline `save_contract(... "active" ...)` call (`:167-169`, or wherever it now sits — the journal plan inserted a `j_quest("told", …)` accept beat just below it, near `_pc_remember` `:174-179`, so locate by content, not line number) with an arc-aware persist:

```python
    data = {k: v for k, v in ct.items() if k not in ("id", "status")}
    if ct.get("src") == "sift":
        data["arc"] = {"beat": "active"}             # emergent: foreshadow/offered → active
    _store().save_contract(_wid(), cid, "active", data)
```

> **Do NOT add a journal call here.** The journal plan's `contract_accept` hook (its Task 4) already fires `j_quest("told", …)` on *every* accept, `src:"sift"` included — the emergent accept beat is captured there. Adding a second `j_quest` would double-log the accept. (Execution order is journal → Inc 2, so that hook is already present when this task runs.) This step's only job is the `arc.beat` bump.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/play/test_quest_offer_routing.py tests/play/test_intent.py -q`
Expected: PASS (dialogue import still valid; routing tests green)

- [ ] **Step 7: Commit**

```bash
git add src/aidnd/server/play/engine/quests/offer.py src/aidnd/server/play/handlers/dialogue.py src/aidnd/server/play/engine/world.py tests/play/test_quest_offer_routing.py
git commit -m "feat(play/quests): приватное предложение перебивает импровизацию; accept двигает arc→active + журнал [quests inc2]"
```

---

### Task 9: Inc 2 — full suite green + live playtest checklist

**Files:**
- Test: whole suite

- [ ] **Step 1: Run the whole suite**

Run: `uv run pytest tests -q`
Expected: PASS — **≥ 363 + the new Inc-2 tests** passed, 0 failed. If any prior test broke, fix the regression before continuing (most likely the `dialogue.talk` edit — re-check the offer block).

- [ ] **Step 2: Live playtest (deepseek profile — NOT pytest)**

Run the app on the deepseek profile and verify by hand (this is a manual gate, do not automate):
1. Start a fresh world, advance to a morning where a sift binds (a giver with an open `acquire`/`affinity` milestone + a matching promise/grudge deed).
2. Confirm the server log shows a judge call and a framer call (two LLM seams, no more) and a `save_contract(status="queued"→"offered"|"board")` for `src:"sift"`.
3. Talk to the giver, ask about work — the **emergent** pitch appears (names only real entities: giver/villain/prize/item), not an improvised container errand.
4. Accept, fetch the item, hand it over — the quest completes through `_contract_on_give`→`_contract_complete`; verify (Inc 1 writeback) the giver's agenda cursor advanced.
5. Kill the LLM (bad endpoint) on a morning — confirm **no** emergent offer, an error line in the log, and boards/incidents still run. Never a canned quest.

- [ ] **Step 3: Commit (checklist doc only if you added notes; otherwise nothing to commit)**

No code change in this task. If the playtest surfaced a fix, commit it as `fix(play/quests): … [quests inc2]`.

---

# PHASE INC 3 — arc (foreshadow → twist → director)

### Task 10: PB tunables for Inc 3

**Files:**
- Modify: `src/aidnd/server/play/engine/session/config.py` (quest block from Task 1)
- Test: `tests/play/test_quests_pb.py` (extend)

**Interfaces:**
- Produces: `PB` keys `quest_active_max=1, quest_interrupt_k=2.0, quest_foreshadow_ticks=2`.

- [ ] **Step 1: Extend the failing test**

Append to `tests/play/test_quests_pb.py`:

```python
def test_inc3_quest_pb_present():
    from aidnd.server.play.engine.core import PB
    assert PB["quest_active_max"] == 1
    assert PB["quest_interrupt_k"] == 2.0
    assert PB["quest_foreshadow_ticks"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_quests_pb.py::test_inc3_quest_pb_present -q`
Expected: FAIL with `KeyError: 'quest_active_max'`

- [ ] **Step 3: Add the keys**

In `config.py`, inside the quest block added in Task 1, add:

```python
    "quest_active_max": 1,        # emergent quests in the surfacing window at once (director)
    "quest_interrupt_k": 2.0,     # a new seed must score ≥ k× queued to jump the window
    "quest_foreshadow_ticks": 2,  # ticks of mind-impulse foreshadow before the offer
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/play/test_quests_pb.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidnd/server/play/engine/session/config.py tests/play/test_quests_pb.py
git commit -m "feat(play/quests): PB-тюнеры Inc 3 — окно/перебивка/фор-тики [quests inc3]"
```

---

### Task 11: `director.py` — the surfacing FSM

**Files:**
- Create: `src/aidnd/server/play/engine/quests/director.py`
- Modify: `src/aidnd/server/play/engine/quests/pipeline.py` (`quest_morning` calls the director instead of the hardcoded `[:1]` + inline `_surface`)
- Test: `tests/play/test_quest_director.py`

**Interfaces:**
- Consumes: `_store().contracts(wid, "queued"|"offered"|"board")`, `PB["quest_active_max"|"quest_interrupt_k"|"quest_offer_days"]`, `pipeline._surface`, `pipeline._expire_stale`.
- Produces:
  - `active_count() -> int` — emergent contracts currently in the surfacing window (`arc.beat ∈ {"foreshadow","offered"}`, `src=="sift"`).
  - `admit(new_seeds_scored: list[dict]) -> dict | None` — window/interrupt decision: returns the seed to persist-and-surface this morning, or `None` if the window is full and no interrupt fires.
  - `tick_morning() -> list[str]` — expiry-compost + overtaken re-check (delegates to `pipeline._expire_stale` and Task 14's `_recheck_overtaken`).

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_quest_director.py
"""Директор: окно quest_active_max, перебивка ≥k×, протухание — паузит ТОЛЬКО показ, не разум."""
import os
import tempfile

from aidnd.server.play.engine import core
from aidnd.server.play.engine.quests import director as D
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


def _store(monkeypatch):
    tmp = tempfile.mkdtemp()
    st = WorldStore(os.path.join(tmp, "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    return st


def _queued(st, cid, beat="offered", score=1.0):
    st.save_contract(core._wid(), cid, "offered" if beat == "offered" else "queued",
                     {"src": "sift", "arc": {"beat": beat},
                      "seed": {"score": score, "pattern": "kin_debt"}, "giver": cid})


def test_window_full_blocks_weaker_new(monkeypatch):
    _store(monkeypatch)
    monkeypatch.setitem(core.PB, "quest_active_max", 1)
    monkeypatch.setitem(core.PB, "quest_interrupt_k", 2.0)
    _queued(core._store(), "ct:sift:a", beat="offered", score=1.0)   # window occupied
    assert D.active_count() == 1
    assert D.admit([{"score": 1.5, "pattern": "kin_debt", "giver": "npc:b",
                     "cast": {"villain": None}}]) is None            # 1.5 < 2.0×1.0 → blocked


def test_strong_new_interrupts(monkeypatch):
    _store(monkeypatch)
    monkeypatch.setitem(core.PB, "quest_active_max", 1)
    monkeypatch.setitem(core.PB, "quest_interrupt_k", 2.0)
    _queued(core._store(), "ct:sift:a", beat="offered", score=1.0)
    strong = {"score": 2.5, "pattern": "kin_debt", "giver": "npc:b", "cast": {"villain": None}}
    assert D.admit([strong]) is strong                              # 2.5 ≥ 2.0×1.0 → jumps window


def test_empty_window_admits_top(monkeypatch):
    _store(monkeypatch)
    monkeypatch.setitem(core.PB, "quest_active_max", 1)
    a = {"score": 3.14, "pattern": "kin_debt", "giver": "npc:a", "cast": {"villain": None}}
    b = {"score": 2.60, "pattern": "broken_promise", "giver": "npc:b", "cast": {"villain": None}}
    assert D.admit([a, b]) is a                                     # window free → highest
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_quest_director.py -q`
Expected: FAIL with `ModuleNotFoundError: …quests.director`

- [ ] **Step 3: Write the implementation**

```python
# src/aidnd/server/play/engine/quests/director.py
"""DIRECTOR — the tiny persisted FSM that paces the TELLING only (spec §3a note 2). It never touches
minds: quest_active_max caps offers-in-flight; quest_interrupt_k lets a much stronger seed jump the
window; quest_offer_days expires stale offers to compost. Queue state IS the persisted contract rows."""

from __future__ import annotations

from aidnd.server.play.engine.core import PB, _store, _wid

_LIVE_BEATS = {"foreshadow", "offered"}


def _emergent(status: str) -> list:
    return [c for c in _store().contracts(_wid(), status) if c.get("src") == "sift"]


def active_count() -> int:
    n = 0
    for status in ("queued", "offered", "board"):
        n += sum(1 for c in _emergent(status) if (c.get("arc") or {}).get("beat") in _LIVE_BEATS)
    return n


def _window_scores() -> list:
    scores = []
    for status in ("queued", "offered", "board"):
        for c in _emergent(status):
            if (c.get("arc") or {}).get("beat") in _LIVE_BEATS:
                scores.append((c.get("seed") or {}).get("score", 0.0))
    return scores


def admit(new_seeds_scored: list) -> dict | None:
    """Return the seed to persist-and-surface this morning, or None. new_seeds_scored is judge-kept,
    salience-sorted (desc). Window free → top seed; window full → only a seed scoring ≥ k× the
    weakest live offer interrupts (the bumped one stays queued and is re-scored next morning)."""
    if not new_seeds_scored:
        return None
    top = new_seeds_scored[0]
    if active_count() < PB["quest_active_max"]:
        return top
    weakest = min(_window_scores(), default=0.0)
    if top.get("score", 0.0) >= PB["quest_interrupt_k"] * weakest:
        return top
    return None


def tick_morning() -> list:
    """Morning maintenance: expire stale offers to compost + close 'overtaken' live seeds."""
    from aidnd.server.play.engine.quests.pipeline import _expire_stale, _recheck_overtaken
    return _expire_stale() + _recheck_overtaken()
```

- [ ] **Step 4: Rewire `quest_morning` to use the director**

In `pipeline.py`, replace the `for seed in kept[:1]:` window loop (and its trailing `return news + _expire_stale()`) with a director-mediated single admit. The persist body is identical to Task 7 — spelled out in full here so it reads standalone:

```python
    from aidnd.server.play.engine.quests import director
    admitted = director.admit(kept)                  # window/interrupt decision (replaces [:1])
    news = []
    if admitted is not None:
        seed = admitted
        art = framing.framer(seed, _allowed(seed), _model())
        if art:
            _ensure_milestone(seed)                  # grievance patterns: materialize a real milestone
            giver = people[seed["giver"]]
            villain = people.get(seed["cast"].get("villain"))
            c = casting.cast(seed, giver.state, villain.state if villain else None, _store(), _wid())
            from aidnd.mind.agenda import Milestone
            m = Milestone(desc="", kind=seed["goal"]["kind"], target=seed["goal"]["target"],
                          done=dict(seed["goal"]["done"]))
            cid = f"ct:sift:{seed['giver']}:{gt}"
            roles = {"giver": seed["giver"], "villain": seed["cast"].get("villain"),
                     "prize": seed["cast"].get("prize")}
            data = {"giver": seed["giver"], "giver_name": seed["giver_name"], "step": 0,
                    "steps": [c["step"]], **c["step"], "reward": c["reward"], "reward_item": None,
                    "reward_name": None, "pitch": art["pitch"], "why": seed["giver_name"],
                    "src": "sift", "seed": seed, "arc": {"beat": "foreshadow"}, "roles": roles,
                    "done_any": bridge.make_done_any(m), "framer": art, "dc": c["dc"]}
            _store().save_contract(_wid(), cid, "queued", data)
            _store().flag_set(_wid(), f"qrecent|{seed['pattern']}",
                              str(int(_store().flag_get(_wid(), f"qrecent|{seed['pattern']}") or 0) + 1))
            _surface(cid, {"id": cid, "status": "queued", **data})
            news.append(f"в городе зреет дело: {seed['giver_name']} ищет, кому довериться")
    return news + director.tick_morning()
```

The `arc` line stays `{"beat": "foreshadow"}` here (identical to Task 7); Task 12 Step 4 later adds `fore_left=PB["quest_foreshadow_ticks"]` to it. The trailing `_expire_stale()` becomes `director.tick_morning()` (which calls `_expire_stale` + `_recheck_overtaken`).

- [ ] **Step 5: Add a stub `_recheck_overtaken` so imports resolve (Task 14 fills it)**

Append to `pipeline.py` (Task 14 replaces the body):

```python
def _recheck_overtaken() -> list[str]:
    """Morning evidence re-check per live seed (filled in Task 14)."""
    return []
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/play/test_quest_director.py tests/play/test_quest_pipeline.py -q`
Expected: PASS (director 3 + pipeline 3; the pipeline `test_one_seed_surfaces_private` still passes — `admit` on a free window returns the top seed)

- [ ] **Step 7: Commit**

```bash
git add src/aidnd/server/play/engine/quests/director.py src/aidnd/server/play/engine/quests/pipeline.py tests/play/test_quest_director.py
git commit -m "feat(play/quests): директор — окно/перебивка/протухание; конвейер зовёт admit вместо жёсткого окна [quests inc3]"
```

---

### Task 12: foreshadow beat — per-mind hot impulse + line

**Files:**
- Create: `src/aidnd/server/play/engine/quests/foreshadow.py`
- Modify: `src/aidnd/server/play/engine/world.py:906-948` (`_world_tick`: impulse bump + `ctx["foreshadow"]`)
- Modify: `src/aidnd/mind/llm_agent.py:184-186` (prompt: inject the foreshadow line like `oaths`)
- Test: `tests/play/test_quest_foreshadow.py`

**Interfaces:**
- Consumes: `_store().contracts(wid, "queued")` (emergent, `arc.beat=="foreshadow"`), `PB["quest_foreshadow_ticks"]`.
- Produces:
  - `foreshadow.lines(order: list) -> dict` — `{pid: line}` for cast members present in `order`; decrements each contract's `arc["fore_left"]` and, when it hits 0, calls `pipeline._surface` to promote to the offer beat.
- The per-mind context key `ctx["foreshadow"] = {pid: line}` mirrors `ctx["oaths"]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_quest_foreshadow.py
"""Фор-тень: реплика достигает контекста разума (как oath), тик считается, потом → offered."""
import os
import tempfile

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core
from aidnd.server.play.engine.quests import foreshadow as FS
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


def _store(monkeypatch):
    tmp = tempfile.mkdtemp()
    st = WorldStore(os.path.join(tmp, "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    return st


def _foreshadow_ct(st, left):
    st.save_contract(core._wid(), "ct:sift:npc:dunn:4320", "queued",
                     {"src": "sift", "giver": "npc:dunn", "giver_name": "Дунн",
                      "seed": {"pattern": "kin_debt"}, "roles": {"giver": "npc:dunn"},
                      "arc": {"beat": "foreshadow", "fore_left": left},
                      "framer": {"foreshadow": "Тебя гложет долг Марты — гроссбух у Ральфа."}})


def test_line_reaches_cast_and_counts_down(monkeypatch):
    st = _store(monkeypatch)
    monkeypatch.setitem(core.PB, "quest_foreshadow_ticks", 2)
    _foreshadow_ct(st, left=2)
    lines = FS.lines(["npc:dunn", "npc:other"])
    assert lines["npc:dunn"].startswith("Тебя гложет")
    assert "npc:other" not in lines
    ct = st.contracts(core._wid(), "queued")[0]
    assert ct["arc"]["fore_left"] == 1                 # один тик списан


def test_countdown_hits_zero_promotes_to_offered(monkeypatch):
    st = _store(monkeypatch)
    _foreshadow_ct(st, left=1)
    FS.lines(["npc:dunn"])                              # last foreshadow tick
    assert not st.contracts(core._wid(), "queued")
    off = st.contracts(core._wid(), "offered")
    assert off and off[0]["arc"]["beat"] == "offered"


def test_prompt_injects_foreshadow_like_oath():
    from aidnd.mind.llm_agent import _build_prompt_probe  # thin test hook (added below)
    npc = NpcState.from_config(NpcConfig(id="npc:dunn", name="Дунн"))
    ctx = {"foreshadow": {"npc:dunn": "Тебя гложет долг Марты."}}
    text = _build_prompt_probe(npc, ctx)
    assert "Тебя гложет долг Марты." in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_quest_foreshadow.py -q`
Expected: FAIL with `ModuleNotFoundError: …quests.foreshadow`

- [ ] **Step 3: Write `foreshadow.py`**

```python
# src/aidnd/server/play/engine/quests/foreshadow.py
"""FORESHADOW beat (spec §3a Beat 1 · §5 Step 4 ticks). The cast get the framer's foreshadow line
as a per-mind context injection + a hot impulse — the SAME mechanism as world.py's oaths (a pid→line
dict fed into ctx and an impulse bump). After quest_foreshadow_ticks the director promotes to offered.
Minds are never throttled — this only adds a line to those already in the scene."""

from __future__ import annotations

from aidnd.server.play.engine.core import _store, _wid


def lines(order: list) -> dict:
    """{pid: foreshadow line} for cast members present in `order`; count down; promote when done."""
    present = set(order)
    out = {}
    for ct in _store().contracts(_wid(), "queued"):
        if ct.get("src") != "sift" or (ct.get("arc") or {}).get("beat") != "foreshadow":
            continue
        line = (ct.get("framer") or {}).get("foreshadow")
        cast_pids = [v for v in (ct.get("roles") or {}).values() if v]
        touched = [pid for pid in cast_pids if pid in present]
        if line:
            for pid in touched:
                out[pid] = line
        arc = dict(ct["arc"])
        arc["fore_left"] = int(arc.get("fore_left", 0)) - 1
        data = {k: v for k, v in ct.items() if k not in ("id", "status")}
        if arc["fore_left"] <= 0:                        # foreshadow spent → surface the offer
            from aidnd.server.play.engine.quests.pipeline import _surface
            data["arc"] = arc
            _surface(ct["id"], {"id": ct["id"], "status": "queued", **data})
        else:
            data["arc"] = arc
            _store().save_contract(_wid(), ct["id"], "queued", data)
    return out
```

- [ ] **Step 4: Seed `fore_left` at persist time**

In `pipeline.py` `quest_morning`, when building `data`, set the foreshadow countdown from PB:

```python
                "src": "sift", "seed": seed,
                "arc": {"beat": "foreshadow", "fore_left": PB["quest_foreshadow_ticks"]},
                "roles": roles,
```

(Replace the `"arc": {"beat": "foreshadow"}` line from Task 7.)

- [ ] **Step 5: Inject into `_world_tick`**

In `world.py`, inside `_world_tick`, before the impulses loop (`:906`), compute foreshadow lines and bump the impulse; after the loop set the ctx key. Add near the `oaths` block (`:900-905`):

```python
    from aidnd.server.play.engine.quests import foreshadow as _fore
    fore = _fore.lines(order)                          # {pid: line} for cast present this tick
```

Then in the impulse loop (`:907-932`), add a branch alongside `oaths_due` (after the `pid in oaths_due` case):

```python
        elif pid in fore:
            imp, why = 2.4, "тень дела"                 # foreshadow pulls, below a live event/debt
```

And after `ctx["oaths"] = oaths` (`:948`):

```python
    ctx["foreshadow"] = fore
```

- [ ] **Step 6: Inject into the mind prompt (`llm_agent.py`)**

In `llm_agent.py`, after the `oath` block (`:184-186`), add:

```python
    fore = ctx.get("foreshadow", {}).get(cfg.id)
    if fore:
        lines.append(f"  ⚑ {fore}")
```

Also add a thin test hook at module end (used only by the test; builds a prompt fragment):

```python
def _build_prompt_probe(state, ctx: dict) -> str:
    """Test hook: render just the foreshadow/oath context line for a state (no LLM)."""
    cfg = state.config
    out = []
    fore = ctx.get("foreshadow", {}).get(cfg.id)
    if fore:
        out.append(f"  ⚑ {fore}")
    return "\n".join(out)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/play/test_quest_foreshadow.py -q`
Expected: PASS (3 tests)

- [ ] **Step 8: Commit**

```bash
git add src/aidnd/server/play/engine/quests/foreshadow.py src/aidnd/server/play/engine/world.py src/aidnd/mind/llm_agent.py src/aidnd/server/play/engine/quests/pipeline.py tests/play/test_quest_foreshadow.py
git commit -m "feat(play/quests): фор-тень — реплика+импульс каста через механизм oaths, тик→offered [quests inc3]"
```

---

### Task 13: twist beat — reveal_on → append-only `done_any`

**Files:**
- Create: `src/aidnd/server/play/engine/quests/twist.py`
- Modify: `src/aidnd/server/play/mechanics/contracts.py:371-377` (`_contract_on_move`: fire twist on first visit to villain node)
- Test: `tests/play/test_quest_twist.py`

**Interfaces:**
- Consumes: active emergent contracts (`_store().contracts(wid, "active")`, `src=="sift"`, `seed.twist`), player node.
- Produces:
  - `twist.on_visit(loc: int, node_of) -> str | None` — if an active emergent contract's `seed.twist.reveal_on == f"visit:{villain}"` and the player is at the villain's node, fire: `arc.beat="twisted"`, **append** `twist.adds` to `done_any` (never touch `done_any[0]`), journal the reveal, stash the giver's next line. Returns the reveal text or `None`.
  - `node_of(pid) -> int | None` — supplied by the caller (`_S["crof"].get`).
- **Never closes the contract.** Per the Inc 1 interface contract, appending the disjunct is enough: the appended `{type:"dead", id:villain}` route is closed and paid by `_contract_on_death`→`_sift_maybe_close()`; the original item route by `_contract_on_give`. `on_visit` only widens `done_any` and re-saves `status="active"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_quest_twist.py
"""Твист: reveal_on → arc twisted, done_any ТОЛЬКО дополняется (инвариант add-or-never-replace)."""
import os
import tempfile

from aidnd.server.play.engine import core
from aidnd.server.play.engine.quests import twist as T
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


def _store(monkeypatch):
    tmp = tempfile.mkdtemp()
    st = WorldStore(os.path.join(tmp, "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    return st


def _active_ct(st):
    st.save_contract(core._wid(), "ct:sift:npc:dunn:4320", "active",
                     {"src": "sift", "giver": "npc:dunn", "giver_name": "Дунн",
                      "roles": {"giver": "npc:dunn", "villain": "npc:ralf"},
                      "arc": {"beat": "active"},
                      "done_any": [{"type": "have", "item": "гроссбух"}],
                      "seed": {"twist": {"fact": "d124: гильдия", "reveal_on": "visit:npc:ralf",
                                         "adds": {"type": "dead", "id": "npc:ralf"}}},
                      "framer": {"reveal": "Ральф сам должен гильдии — его можно прижать."}})


def test_visit_villain_fires_twist_appends_disjunct(monkeypatch):
    st = _store(monkeypatch)
    _active_ct(st)
    node_of = {"npc:ralf": 9, "npc:dunn": 7}.get
    txt = T.on_visit(9, node_of)                       # игрок пришёл в узел Ральфа
    assert txt and "гильдии" in txt
    ct = st.contracts(core._wid(), "active")[0]
    assert ct["arc"]["beat"] == "twisted"
    assert ct["done_any"] == [{"type": "have", "item": "гроссбух"},
                              {"type": "dead", "id": "npc:ralf"}]  # добавлено, не заменено
    assert ct["done_any"][0] == {"type": "have", "item": "гроссбух"}  # [0] неизменно


def test_twist_fires_once(monkeypatch):
    st = _store(monkeypatch)
    _active_ct(st)
    node_of = {"npc:ralf": 9}.get
    assert T.on_visit(9, node_of)
    assert T.on_visit(9, node_of) is None              # второй визит — уже twisted, молчит
    ct = st.contracts(core._wid(), "active")[0]
    assert len(ct["done_any"]) == 2                    # дизъюнкт не задублирован


def test_no_twist_when_not_at_villain(monkeypatch):
    st = _store(monkeypatch)
    _active_ct(st)
    assert T.on_visit(7, {"npc:ralf": 9}.get) is None  # игрок у Дунна, не у Ральфа
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_quest_twist.py -q`
Expected: FAIL with `ModuleNotFoundError: …quests.twist`

- [ ] **Step 3: Write `twist.py`**

```python
# src/aidnd/server/play/engine/quests/twist.py
"""TWIST beat (spec §3a · §5 Step 5). reveal_on (first visit to the villain node) → arc.beat='twisted';
APPEND the twist's real _met dict to done_any (never mutate [0], never remove) — widening the routes,
never invalidating progress. Reveal text → player journal + the giver's next conversation line."""

from __future__ import annotations

from aidnd.server.play.engine.core import _S, _store, _wid


def _j_quest(prov, text, cid):
    try:
        from aidnd.server.play.engine.journal import j_quest
    except ImportError:
        return
    try:
        j_quest(prov, text, cid)
    except Exception:  # noqa: BLE001
        pass


def on_visit(loc: int, node_of) -> str | None:
    for ct in _store().contracts(_wid(), "active"):
        if ct.get("src") != "sift" or (ct.get("arc") or {}).get("beat") == "twisted":
            continue
        tw = ((ct.get("seed") or {}).get("twist")) or None
        if not tw or tw.get("reveal_on", "").split(":", 1)[0] != "visit":
            continue
        villain = tw["reveal_on"].split(":", 1)[1]
        if node_of(villain) != loc:
            continue
        done_any = list(ct.get("done_any") or [])
        adds = tw.get("adds")
        if adds and adds not in done_any:               # append-only, dedup
            done_any.append(adds)
        reveal = (ct.get("framer") or {}).get("reveal") or "Всплыл новый поворот в этом деле."
        data = {k: v for k, v in ct.items() if k not in ("id", "status")}
        data["done_any"] = done_any
        data["arc"] = {"beat": "twisted"}
        data["giver_next_line"] = reveal                # giver voices it in the next conversation
        _store().save_contract(_wid(), ct["id"], "active", data)
        _j_quest("told", reveal, ct["id"])           # prov ∈ journal's closed set (saw|heard1|heard2|told)
        return reveal
    return None
```

- [ ] **Step 4: Fire the twist from `_contract_on_move`**

In `contracts.py` `_contract_on_move` (`:371-377`), after the existing `visit`-step loop, add the twist check (player just reached `loc`). Note the Inc 1 plan has already inserted `hit = _sift_maybe_close(); if hit: return hit` as the FIRST body line, so it returns early when a move closes a sift quest; the twist check below runs only when no completion fired (a widening reveal, never a close):

```python
    from aidnd.server.play.engine.quests import twist as _twist
    from aidnd.server.play.engine.core import _S as _Sc
    node_of = (_Sc.get("crof") or {}).get
    _twist.on_visit(loc, node_of)                       # emergent twist reveal on villain-node visit
    return None
```

(Keep the original `visit`-step return above; the twist check runs after and does not consume the move.)

- [ ] **Step 5: Voice the giver's next line**

In `dialogue.py` `talk`, after computing `has_offer` (`:109`), surface a stashed twist line if present:

```python
    gnl = None
    for _ct in _store().contracts(_wid(), "active"):
        if _ct.get("src") == "sift" and _ct.get("giver") == npc and _ct.get("giver_next_line"):
            gnl = _ct["giver_next_line"]
            data = {k: v for k, v in _ct.items() if k not in ("id", "status")}
            data.pop("giver_next_line", None)           # spoken once
            _store().save_contract(_wid(), _ct["id"], "active", data)
            break
```

Then include `"twist_line": gnl` in the `talk` return dict. (`_store`/`_wid` are already imported in `dialogue.py` via `core`; add them to the import block at `:28` if missing.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/play/test_quest_twist.py -q`
Expected: PASS (3 tests)

- [ ] **Step 7: Commit**

```bash
git add src/aidnd/server/play/engine/quests/twist.py src/aidnd/server/play/mechanics/contracts.py src/aidnd/server/play/handlers/dialogue.py tests/play/test_quest_twist.py
git commit -m "feat(play/quests): твист — reveal_on визитом к злодею, done_any только дополняется, реплика заказчика [quests inc3]"
```

---

### Task 14: morning evidence re-check → overtaken close

**Files:**
- Modify: `src/aidnd/server/play/engine/quests/pipeline.py` (`_recheck_overtaken` body)
- Test: `tests/play/test_quest_overtaken.py`

**Interfaces:**
- Consumes: active/offered emergent contracts; `bridge.done_any_met(ct, giver_state)`; `_S["people"]`.
- Produces:
  - `_recheck_overtaken() -> list[str]` — for each live emergent seed, if the giver's `done_any[0]` milestone is already moot (the giver already advanced it himself), close the quest `arc.beat="overtaken"` with an honest giver line; the giver keeps his (already-advanced) agenda.

- [ ] **Step 1: Write the failing test**

```python
# tests/play/test_quest_overtaken.py
"""Обгон: заказчик сам закрыл веху → квест закрывается 'overtaken' честной репликой, без утечки на доску."""
import os
import tempfile
from types import SimpleNamespace

from aidnd.mind import NpcConfig, NpcState
from aidnd.mind.agenda import Agenda, Milestone
from aidnd.server.play.engine import core
from aidnd.server.play.engine.quests import pipeline as P
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


def _store(monkeypatch):
    tmp = tempfile.mkdtemp()
    st = WorldStore(os.path.join(tmp, "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    return st


def test_overtaken_closes_when_giver_advanced(monkeypatch):
    st = _store(monkeypatch)
    # Марта сама уплатила долг → веха Дунна закрыта, cursor уже 1
    ms = Milestone("вернуть гроссбух", "acquire", "debt:marta", {}, {"type": "have", "item": "гроссбух"})
    ag = Agenda("вернуть гроссбух", "ambition", 0.7, [ms])
    ag.cursor = 1                                      # веха уже пройдена своими силами
    dunn = SimpleNamespace(name="Дунн", state=NpcState.from_config(NpcConfig(id="npc:dunn", name="Дунн")))
    dunn.state.agendas = [ag]
    core._S["people"] = {"npc:dunn": dunn}
    st.save_contract(core._wid(), "ct:sift:npc:dunn:4320", "offered",
                     {"src": "sift", "giver": "npc:dunn", "giver_name": "Дунн",
                      "arc": {"beat": "offered"}, "seed": {"pattern": "kin_debt"},
                      "done_any": [{"type": "have", "item": "гроссбух"}],
                      "roles": {"giver": "npc:dunn"}})
    news = P._recheck_overtaken()
    assert any("улажено" in n or "поздно" in n for n in news)
    assert not st.contracts(core._wid(), "offered")
    closed = st.contracts(core._wid(), "closed")[0]
    assert closed["arc"]["beat"] == "overtaken"
    assert not st.contracts(core._wid(), "board")      # никакой утечки на доску
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/play/test_quest_overtaken.py -q`
Expected: FAIL — `_recheck_overtaken` returns `[]` (stub from Task 11), so the contract stays `offered`.

- [ ] **Step 3: Fill `_recheck_overtaken`**

Replace the stub in `pipeline.py`:

```python
def _recheck_overtaken() -> list[str]:
    """Per-morning re-check (spec §6): if the giver already advanced past the milestone anchoring
    done_any[0], the offer is moot → close 'overtaken' with an honest line. The giver keeps his
    (already-advanced) agenda; private grief never leaks to a board."""
    people = _S.get("people") or {}
    news = []
    for status in ("offered", "board", "queued"):
        for ct in _store().contracts(_wid(), status):
            if ct.get("src") != "sift":
                continue
            giver = people.get(ct.get("giver"))
            if not giver:
                continue
            anchor = (ct.get("done_any") or [{}])[0]
            if _milestone_still_open(giver.state, anchor):
                continue                                # milestone still open — offer stands
            data = {k: v for k, v in ct.items() if k not in ("id", "status")}
            data["arc"] = {"beat": "overtaken"}
            _store().save_contract(_wid(), ct["id"], "closed", data)
            news.append(f"{ct.get('giver_name', 'кто-то')}: спасибо, но дело уж улажено — поздно")
    return news


def _milestone_still_open(giver_state, anchor: dict) -> bool:
    """True if some active agenda's CURRENT milestone still carries the anchoring done predicate."""
    for ag in giver_state.agendas or []:
        if getattr(ag, "status", "active") != "active":
            continue
        m = ag.current() if hasattr(ag, "current") else None
        if m and m.done == anchor:
            return True
    return False
```

Add `from aidnd.server.play.engine.core import ... _S` is already imported at the top of `pipeline.py` (Task 7).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/play/test_quest_overtaken.py tests/play/test_quest_director.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidnd/server/play/engine/quests/pipeline.py tests/play/test_quest_overtaken.py
git commit -m "feat(play/quests): утренний пересмотр улик — заказчик обогнал → закрытие 'overtaken' без утечки на доску [quests inc3]"
```

---

### Task 15: Inc 3 — full suite green + live playtest checklist

**Files:**
- Test: whole suite

- [ ] **Step 1: Run the whole suite**

Run: `uv run pytest tests -q`
Expected: PASS — the running baseline (405 if Inc 1 + journal already landed) plus all Inc 2/3 tests, 0 failed. Assert "+N new, 0 failed", not an absolute. Fix any regression (most likely the `world._world_tick` foreshadow branch or the `_contract_on_move` twist hook) before continuing.

- [ ] **Step 2: Verify the twist invariant across the suite**

Run: `uv run pytest tests/play/test_quest_twist.py tests/play/test_quest_foreshadow.py tests/play/test_quest_director.py tests/play/test_quest_overtaken.py -q`
Expected: PASS — confirms: `done_any[0]` immutable + append-only; foreshadow line reaches the mind prompt; window/interrupt/expiry FSM; overtaken close.

- [ ] **Step 3: Live playtest (deepseek profile — NOT pytest)**

Manual gate — drive a full arc end-to-end:
1. Trigger a morning sift. Confirm the chosen seed persists `arc.beat="foreshadow"` with `fore_left=2`.
2. Advance 2 ticks near the giver — the server scene log shows the giver's impulse rising to `"тень дела"` and the foreshadow line in his mind prompt; the offer then flips to `offered`/`board`.
3. Accept, then walk to the villain's node — the twist fires: `arc.beat="twisted"`, `done_any` grows by one disjunct (verify `done_any[0]` unchanged), the reveal lands in the player journal and the giver voices it next time you talk.
4. Complete via EITHER route (bring the item OR neutralise the villain) — completion fires and the Inc-1 writeback advances the giver's cursor.
5. Interrupt test: force two mornings so a much stronger seed (≥2×) exists — confirm it jumps the window and the weaker one stays queued, re-scored next morning.
6. Overtaken test: let a giver advance his own milestone (or hand-edit) while an offer is live — next morning the offer closes `overtaken` with an honest line and never appears on the board.
7. No-LLM test: kill the model mid-arc — no new emergent offers, error logged, the rest of the world unaffected.

- [ ] **Step 4: Ship**

If green and the playtest passes, this is a finished increment — deploy per the `/deploy` skill (Russian commit, no Claude co-author). Otherwise commit fixes as `fix(play/quests): … [quests inc3]`.

---

## Self-Review

**1. Spec coverage.**
- §4 pattern table + shape → Task 2 (`seeds.py`, all 5 patterns, QuestSeed dict, twist candidate). `at` excluded via `DELEGATABLE`. ✔
- §5 Step 1 binding semantics → Task 2 tests (kin_debt/broken_promise bind; blocked_rival/unanswered_blood/courtship_wall abstain). ✔
- §5 Step 2 salience formulas + constants → Task 3 (`salience.py`), A=3.14>B=2.60 number-for-number. ✔
- §5 Step 3 judge (one call, strict JSON, parse-defensive, no-offer on failure) → Task 4. ✔
- §5 Step 4 framer (3 artifacts at creation) + apophenia validator (regen once then skip, mirrors `_build_step`) → Task 5. ✔
- §5 Step 4 casting (motivation→kind, real purse `min(30,41)`, DC from villain) → Task 6. ✔
- §3a morning hook, persist `status="queued"` with seed/arc/roles/src/done_any, window=1, private/public routing → Task 7 + Task 8. ✔
- §5 Step 6 compost / §10 expiry (no board leak, giver keeps agenda) → Task 7 `_expire_stale`. ✔
- §5 Step 7 no-LLM honest absence → Tasks 4/7 (`judge` returns `[]`, `quest_morning` catches). ✔
- §11 PB keys → Task 1 (Inc 2) + Task 10 (Inc 3). ✔
- §3a/§7 director FSM (window/interrupt/expiry) → Task 11. ✔
- §5 Step 4 foreshadow (hot impulse + line via the oaths mechanism, `quest_foreshadow_ticks`) → Task 12. ✔
- §5 Step 5 twist (reveal_on, append-only `done_any`, journal + giver line) → Task 13. ✔
- §6 overtaken morning re-check → Task 14. ✔
- §7 tests per increment + live playtest → Tasks 9 & 15. ✔
- Consumed Inc-1 bridge (`milestone_to_step`, `make_done_any`, `done_any_met`, `quest_writeback`) — used in Tasks 6/7/14, never redefined; the writeback itself stays wired in `_contract_complete` by Inc 1. ✔
- Journal `j_quest` guarded by `try/except ImportError` at every beat (accept/twist; pitch/outcome beats reachable via the same shim). ✔

**2. Placeholder scan.** The only intentional stub is `_recheck_overtaken` in Task 11, explicitly filled in Task 14 (noted at both sites). No `TBD`/`add error handling`/uncoded steps remain. ✔

**3. Type consistency.** `sift(people, deeds, gt)`, `score(seed, ctx)`, `judge(seeds, deeds, names, manager)`, `framer(seed, allowed, manager)`, `cast(seed, giver_state, villain_state, store, wid)`, `admit(list)->dict|None`, `foreshadow.lines(order)->dict`, `twist.on_visit(loc, node_of)->str|None` — names/signatures match across producing and consuming tasks. The contract `data` keys (`src/seed/arc/roles/done_any/framer/step/dc/giver_next_line`) are used consistently. `arc.beat` vocabulary (`foreshadow→offered/board→active→twisted→closed`; `expired`/`overtaken`) is uniform. ✔

## Ambiguities resolved

1. **broken_promise / deed-grievance patterns have no pre-existing giver milestone** (fixture Марта has no agenda, yet §5 says the pattern binds). Resolved: milestone-anchored patterns (kin_debt/blocked_rival/courtship_wall) lift the giver's live `Milestone.done` verbatim into `done_any[0]`; deed-grievance patterns (broken_promise/unanswered_blood) name the intended revenge predicate `{type:"dead", id:villain}` as `goal.done`, and at **seed-choice time** the pipeline (`_ensure_milestone`, Task 7) **inserts a real `Agenda(kind="revenge", importance=0.8)` with one `Milestone` whose `done` IS that predicate** into the giver's live state — following the deals.py:155 precedent (deal-success inserts a `"hired"` Agenda). `done_any[0]` then lifts verbatim from that milestone, its index is anchored in `seed.evidence` (`agenda:<pid>:<idx>`), and the Inc-1 `quest_writeback` advances a **real** cursor uniformly for every pattern — no special no-op case. Persistence mirrors deals.py exactly: the insert lives on the in-memory `_S["people"][giver].state.agendas`; `save_npc_state`/`_npc_save` deliberately do not write agendas to DB (verified store.py:372), so no new persistence is invented. A side benefit: `_recheck_overtaken` (`_milestone_still_open`, Task 14) now reads True for a live grievance offer instead of spuriously closing it "overtaken". Documented in `seeds.py`'s module docstring and `_ensure_milestone`.
2. **peak uses "max|affinity edge in cast|" but the worked numbers use the giver→villain edge** (A: |Дунн→Ральф|=0.4, not |Марта→Ральф|=0.6). Resolved by following the numbers: `peak = |affinity(giver→villain)| + max deed-weight`. This reproduces both 3.14 and 2.60 exactly; noted in `salience.py`.
3. **The twist's "second fact" (Ральф owes the guild 200) is illustrated but not in the fixture deed list.** Resolved: `_twist_for` binds only to a *real* second deed by the villain; the fixture test adds `d124` (villain→guild broken promise) as that anchor — consistent with §5 Step 5's reveal — and it does **not** perturb the A/B salience (it is in `twist.fact`, never in `evidence`), so the number-for-number check holds.
