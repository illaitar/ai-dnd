# End-to-End Benchmark — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the end-to-end benchmark from [bench.md](bench.md): play the real game over HTTP and
check it against the six goals, as green, independently-shippable increments.

**Architecture:** A `bench/` package driven by `fastapi.testclient.TestClient` against a fresh
seeded per-run world. A per-tick trace (input/frontend/backend/llm) is the substrate both a
deterministic invariant layer and an LLM exploratory/judge layer read. `scripts/bench.py` is the
entry with a `--fast` (CI gate) / `--full` (on-demand) split; artifacts land in
`data/debug/bench/<run-id>/`.

**Tech Stack:** Python 3.14, FastAPI + `TestClient`, pytest, `uv`, existing `aidnd` engine
(`server/play/engine`, `worldgen.WorldStore`, `inference.ModelManager`).

## Global Constraints

- Each increment ends green (`uv run pytest -q` passes) → commit → deploy via the `/deploy` skill.
- Commit messages in English; **no `Co-Authored-By: Claude` trailer**.
- **Never touch game behavior.** The benchmark only reads state and drives public endpoints; it adds
  no game code and changes no player-facing/LLM-prompt string.
- `no-LLM-fallback`: `--full` needs a real LLM. Unit tests stub the model; they must not require one.
- New functions ≤50 lines; every new file starts with an English "Key functions" module docstring.
- Tuned numbers live in data/config, not string literals.
- Package home: `bench/` (sibling of `src/`, added to the same project); tests in `tests/bench/`.

---

## File Structure

```
bench/
  __init__.py
  harness.py      bench_world(seed) — TestClient + fresh temp world; open-play auth bypass
  snapshot.py     snapshot() — deep backend state (session, present NPC minds, live.db, economy)
  llmtap.py       llm_tap() — context manager recording every ModelManager.call (role/msgs/raw/parsed/ms)
  trace.py        TurnRecord, TraceWriter — wrap one turn into a 4-face record; stream JSONL
  actions.py      action_matrix() — cells from resolve.PRIMITIVES + the /api/play/* catalog
  drivers/
    coverage.py   walk the matrix in a valid context; assert each legal action succeeds
    adversarial.py cheat suite; assert refusal + zero illegal delta
    autonomous.py  Russian LLM player: scene JSON + persona/goal -> next action
  oracle.py       invariant families over a trace (conservation/provenance/containment/legality/shape)
  judge.py        LLM-judge rubrics (npc_realism, system_completeness), majority vote
  report.py       aggregate coverage + oracle + judge -> report.json + verdict
  dashboard.py    trace + report -> self-contained HTML
scripts/bench.py  entry: --fast (gate) / --full (adds autonomous+judge); replaces the dead old script
tests/bench/      one test module per bench/ module
data/debug/bench/<run-id>/  trace.jsonl · report.json · dashboard.html
```

Files that change together live together; each `bench/` module has one responsibility and is small
enough to hold in context. `pyproject.toml` gets `bench` added to the package/testpaths.

---

## Increment 1 — Harness + trace substrate (spec: *Shape*, *Trace substrate*; goal 2)

Deliverable: `record_turn(client, action)` produces a well-formed 4-face JSONL record against a
fresh seeded world. This is the spine; everything else reads it.

### Task 1.1: `bench_world` harness (fresh seeded world over TestClient)

**Files:**
- Create: `bench/__init__.py`, `bench/harness.py`
- Test: `tests/bench/test_harness.py`
- Modify: `pyproject.toml` (add `bench` to `tool.setuptools.packages`/`testpaths`)

**Interfaces:**
- Produces: `bench_world(seed: int) -> contextmanager` yielding
  `Harness(client: TestClient, store: WorldStore, seed: int)`; `Harness.scene() -> dict` (GET
  `/api/play/scene`); `Harness.act(endpoint: str, **params) -> httpx.Response`.

**Spike first (comment in the test):** confirm how `core._play_session` resolves a world so a
TestClient call to `/api/play/scene` returns 200. The in-process tests bypass HTTP by monkeypatching
`core._STORE` to a temp `live.db` and setting `core._S["city"]=None` then calling `_play()`. For
HTTP, set `AIDND_OPEN_PLAY=1` (see `server/app.py:play_page`) and monkeypatch `core._STORE` to a
temp store **before** the first request; `_play_session` + `_play()` build the world lazily on the
first `/scene`. If `_play_session` needs a user/world id, pin a benchmark one via
`WorldStore.user_world_create("bench")`.

- [ ] **Step 1: Write the failing test**
```python
# tests/bench/test_harness.py
from bench.harness import bench_world

def test_scene_reachable_over_http():
    with bench_world(seed=7) as h:
        r = h.act("scene")            # GET/POST /api/play/scene
        assert r.status_code == 200
        body = r.json()
        assert "location" in body and "here" in body   # scene dict shape
```
- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/bench/test_harness.py -x` → FAIL (no module `bench`).
- [ ] **Step 3: Implement `bench/harness.py`** — a `@contextmanager` that: sets `os.environ["AIDND_OPEN_PLAY"]="1"`; makes a temp dir + `WorldStore(tmp/live.db)`; monkeypatches `core._STORE` (via `unittest.mock.patch.object`); resets `core._S` world keys (`city=None`); builds `TestClient(app)`; yields `Harness`. `Harness.act` maps a short name to the real `/api/play/<name>` path and method (GET for scene/hero/look, POST otherwise). Tear down: close client, restore `core._STORE`, rm temp dir.
- [ ] **Step 4: Run to verify it passes** — `uv run pytest tests/bench/test_harness.py -x` → PASS.
- [ ] **Step 5: Commit** — `git add bench/ tests/bench/ pyproject.toml && git commit -m "bench: seeded world harness over TestClient"`.

### Task 1.2: Backend snapshot

**Files:** Create `bench/snapshot.py`; Test `tests/bench/test_snapshot.py`.

**Interfaces:**
- Produces: `snapshot() -> dict` with keys `session` (loc/inside/gt/wanted/coins/hp/mana/flags from
  `core._S` + `core` accessors), `npcs` ({pid: {needs, emotion, relationships, memory_size, agenda}}
  for present NPCs), `live` (inventory/purse/flags/deeds/contracts rows from `core._STORE`),
  `economy` (`ec.money_supply()`, `ec.chains_view()`), `crof` (ring-B positions).

- [ ] **Step 1: Failing test** — build a world via `bench_world`, call `snapshot()`, assert
  `snapshot()["economy"]["money_supply"] > 0` and `snapshot()["session"]["gt"]` is an int.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** — read-only reflection over `core._S`, `core._store()`, `economy`,
  `mind` state of `core._S["people"]` present at `loc`. Each sub-collector is its own ≤50-line fn
  (`_session()`, `_npcs()`, `_live()`, `_econ()`).
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `git commit -m "bench: deep backend snapshot"`.

### Task 1.3: LLM tap

**Files:** Create `bench/llmtap.py`; Test `tests/bench/test_llmtap.py`.

**Interfaces:**
- Produces: `llm_tap() -> contextmanager` yielding `list[LLMCall]`; `LLMCall = {role, messages,
  raw, parsed, ms}`. Implemented by wrapping `ModelManager.call` (monkeypatch): time it, record
  args + return, append, return through. (`on_call(role, model)` is insufficient — it lacks
  prompt/output.)

- [ ] **Step 1: Failing test** — with a `StubModelManager` (returns a canned dict), assert a call
  inside `llm_tap()` appends one `LLMCall` with the role and raw output.
- [ ] **Step 2: Run → FAIL.** [ ] **Step 3: Implement wrapper.** [ ] **Step 4: PASS.**
- [ ] **Step 5: Commit** — `git commit -m "bench: LLM call tap"`.

### Task 1.4: Turn record + JSONL writer

**Files:** Create `bench/trace.py`; Test `tests/bench/test_trace.py`.

**Interfaces:**
- Produces: `TurnRecord = {turn, input, frontend, backend, llm}`; `record_turn(h, endpoint,
  **params) -> TurnRecord` (drives via `h.act`, captures response JSON = `frontend`, `snapshot()` =
  `backend`, `llm_tap()` = `llm`); `TraceWriter(path)` with `.append(rec)` streaming JSONL and
  `.close()`.

- [ ] **Step 1: Failing test** — `record_turn(h, "look")` returns a dict whose `frontend` is the
  response JSON and `backend["economy"]["money_supply"] > 0`; `TraceWriter` writes one JSONL line.
- [ ] **Step 2: FAIL.** [ ] **Step 3: Implement.** [ ] **Step 4: PASS.**
- [ ] **Step 5: Commit** — `git commit -m "bench: per-turn 4-face trace + JSONL writer"`.

**Increment 1 close:** `uv run pytest -q` green → `/deploy`.

---

## Increment 2 — Action matrix + coverage driver (spec: *Player driver*; goal 1)

Deliverable: every primitive×manner and endpoint is exercised in a valid context, legal ones assert
success; unreachable cells are reported.

### Task 2.1: Action matrix

**Files:** Create `bench/actions.py`; Test `tests/bench/test_actions.py`.

**Interfaces:**
- Produces: `action_matrix() -> list[ActionCell]`; `ActionCell = {id, kind: "primitive"|"endpoint",
  verb, manner, targets, endpoint, needs: list[str]}`. Primitive cells derive from
  `resolve.PRIMITIVES` (verb × declared manner × targets); endpoint cells from a static list of the
  `/api/play/*` routes (extracted once from the routers).

- [ ] **Step 1: Failing test** — `ids = {c["id"] for c in action_matrix()}`; assert
  `"primitive:take+item+stealthily"` in ids and `"endpoint:/api/play/cast"` in ids; assert every
  `resolve.PRIMITIVES` verb appears.
- [ ] **Step 2: FAIL.** [ ] **Step 3: Implement** (iterate `resolve.PRIMITIVES`; hardcode the route
  list with a test that cross-checks it against the live routers so it can't drift). [ ] **PASS.**
- [ ] **Step 5: Commit** — `git commit -m "bench: action-coverage matrix from PRIMITIVES + routes"`.

### Task 2.2: Coverage driver

**Files:** Create `bench/drivers/__init__.py`, `bench/drivers/coverage.py`; Test
`tests/bench/test_coverage.py`.

**Interfaces:**
- Consumes: `bench_world`, `record_turn`, `action_matrix`.
- Produces: `run_coverage(h, writer) -> CoverageResult`; `CoverageResult = {exercised: set[str],
  unreached: list[str], failures: list[dict]}`. For each cell, `_setup_context(h, cell)` arranges a
  valid state (e.g. for `take+item`, move to a zone with a loose item), fires the action via
  `record_turn`, and asserts the response is not an error/refusal for a legal action.

- [ ] **Step 1: Failing test** — run coverage over a seeded world for a small subset
  (`look`, `map`, `scene`); assert those ids are in `exercised` and `failures == []`.
- [ ] **Step 2: FAIL.** [ ] **Step 3: Implement** the driver + per-cell `_setup_context` helpers
  (each ≤50 lines; unreachable cells go to `unreached`, not `failures`). [ ] **PASS.**
- [ ] **Step 5: Commit** — `git commit -m "bench: coverage driver over the action matrix"`.

**Increment 2 close:** pytest green → `/deploy`.

---

## Increment 3 — Invariant oracle + adversarial prober (spec: *Invariant oracle*; goals 4, 6)

### Task 3.1: Oracle — conservation, provenance, containment, content-shape

**Files:** Create `bench/oracle.py`; Test `tests/bench/test_oracle.py`.

**Interfaces:**
- Consumes: a list of `TurnRecord`.
- Produces: `check_all(trace) -> list[Violation]`; `Violation = {invariant, turn, before, after,
  detail}`. Families as separate ≤50-line functions: `check_conservation` (economy `M` invariant
  except a whitelisted player in/out), `check_provenance` (every player-held item id has a prior
  acquisition event in `backend.live.deeds`/inventory deltas), `check_narrator_containment` (turns
  whose only mechanism was narration have `backend` deltas ⊆ the six clamped consequence types),
  `check_content_shape` (each `llm.parsed` validates; the first world snapshot is well-formed —
  graph connected, every NPC placed, economy seeded).

- [ ] **Step 1: Failing tests** — hand-craft two tiny traces: one that conserves `M` (0 violations)
  and one where a purse jumps with no legal cause (1 `conservation` violation); assert `check_all`
  returns the expected counts and the violation carries `turn` + `before/after`.
- [ ] **Step 2: FAIL.** [ ] **Step 3: Implement** each checker. [ ] **PASS.**
- [ ] **Step 5: Commit** — `git commit -m "bench: invariant oracle (conservation/provenance/containment/shape)"`.

### Task 3.2: Adversarial prober

**Files:** Create `bench/drivers/adversarial.py`; Test `tests/bench/test_adversarial.py`.

**Interfaces:**
- Produces: `run_adversarial(h, writer) -> list[ProbeResult]`; `ProbeResult = {probe, refused: bool,
  illegal_delta: bool}`. A `PROBES` list of cheat attempts, each `{setup, act, expect_refused}`:
  take a pinned/fixed item, move to an unreachable node, trade out-of-hours, revive a dead NPC,
  attempt to over-spend the purse, claim a phantom key. Each asserts a refusal **and** that the
  trace shows zero illegal delta (reuses `oracle.check_narrator_containment` on the probe's turn).

- [ ] **Step 1: Failing test** — the "take a fixed item" probe returns `refused=True,
  illegal_delta=False`.
- [ ] **Step 2: FAIL.** [ ] **Step 3: Implement** the probe runner + `PROBES` (data, not code
  branches). [ ] **PASS.**
- [ ] **Step 5: Commit** — `git commit -m "bench: adversarial cheat prober (world-integrity)"`.

**Increment 3 close:** pytest green → `/deploy`.

---

## Increment 4 — Reporter + dashboard + `scripts/bench.py --fast` (spec: *Dashboard*, *Run modes*)

Deliverable: `uv run python scripts/bench.py --fast --seed 7` plays a seeded world through the
deterministic layer, writes `trace.jsonl` + `report.json` + `dashboard.html`, and exits non-zero on
any invariant/legality break or coverage regression.

### Task 4.1: Reporter

**Files:** Create `bench/report.py`; Test `tests/bench/test_report.py`.

**Interfaces:**
- Produces: `build_report(coverage, violations, probes, judge=None) -> dict` with
  `verdict: "pass"|"fail"`, `coverage_pct`, `violations`, `probes`, `judge` (None in `--fast`);
  `write_report(path, report)`.

- [ ] **Step 1: Failing test** — a report with one violation has `verdict == "fail"`; a clean one
  `"pass"`; `coverage_pct` computed from exercised/total.
- [ ] **Step 2: FAIL.** [ ] **Step 3: Implement.** [ ] **PASS.**
- [ ] **Step 5: Commit** — `git commit -m "bench: reporter + verdict"`.

### Task 4.2: Dashboard

**Files:** Create `bench/dashboard.py`; Test `tests/bench/test_dashboard.py`.

**Interfaces:**
- Produces: `render_dashboard(trace_path, report_path) -> str` (self-contained HTML, inline CSS/JS,
  no external assets, theme-aware); `write_dashboard(out_path, html)`. Sections: verdict banner,
  coverage heatmap, violations (expand → before/after trace slice), judge scores + example
  transcripts (if present), runs-over-time trend (reads sibling run dirs).

- [ ] **Step 1: Failing test** — `render_dashboard` output contains the verdict string, a
  `<style>` block, and no `http://`/`https://` asset link (CSP-safe / self-contained).
- [ ] **Step 2: FAIL.** [ ] **Step 3: Implement** (build strings; keep functions ≤50 lines by
  splitting per section). [ ] **PASS.**
- [ ] **Step 5: Commit** — `git commit -m "bench: self-contained results dashboard"`.

### Task 4.3: `scripts/bench.py --fast` entry (replaces the dead script)

**Files:** Rewrite `scripts/bench.py`; Test `tests/bench/test_cli_fast.py`.

**Interfaces:**
- Produces: CLI `--fast|--full`, `--seed`, `--turns`, `--out data/debug/bench/<run-id>/`. `--fast`
  runs coverage + adversarial + oracle (+ content-shape), writes the three artifacts, exits 0/1 on
  verdict.

- [ ] **Step 1: Failing test** — invoke `main(["--fast","--seed","7","--turns","5"])` in-process;
  assert it returns exit 0 on a clean seed and that `trace.jsonl`/`report.json`/`dashboard.html`
  exist in the run dir.
- [ ] **Step 2: FAIL.** [ ] **Step 3: Implement** `main()` orchestration (run-id from
  `--seed`+turn count, no wall-clock in the id so it's reproducible). Delete the old
  `aidnd.bootstrap`/`runtime` imports entirely. [ ] **PASS.**
- [ ] **Step 5: Commit** — `git commit -m "bench: scripts/bench.py --fast gate (replaces dead script)"`.

**Increment 4 close:** pytest green → `/deploy`. The deterministic gate now runs end-to-end.

---

## Increment 5 — Autonomous player + judge (`--full`) (spec: *Player driver*, *Judge*; goals 3, 5)

Deliverable: `--full` adds a Russian LLM player and an LLM-judge; scores land in the report +
dashboard. Unit tests use a stub model; real runs need a live LLM (`AIDND_PROFILE=deepseek`).

### Task 5.1: Autonomous player

**Files:** Create `bench/drivers/autonomous.py`; Test `tests/bench/test_autonomous.py`.

**Interfaces:**
- Produces: `run_autonomous(h, writer, persona, goal, turns, mgr) -> None`. Each turn: build a
  Russian prompt from the scene JSON + persona + goal, call `mgr.call("bench_player", ...)` for the
  next action `{endpoint|"act", params|text}`, drive it via `record_turn`. `PERSONAS` is data
  (cautious trader / greedy rogue / curious wanderer), each with a goal string (Russian).

- [ ] **Step 1: Failing test (stub model)** — a `StubMgr` returns `{"act":"осмотреться"}`;
  `run_autonomous(..., turns=2, mgr=StubMgr())` appends 2 turns to the writer.
- [ ] **Step 2: FAIL.** [ ] **Step 3: Implement** (prompt builder ≤50 lines; the action parser
  clamps to known endpoints/freeform). [ ] **PASS.**
- [ ] **Step 5: Commit** — `git commit -m "bench: autonomous Russian LLM player"`.

### Task 5.2: Judge

**Files:** Create `bench/judge.py`; Test `tests/bench/test_judge.py`.

**Interfaces:**
- Produces: `judge_npc_realism(trace, mgr) -> list[Score]` and `judge_system_completeness(trace,
  mgr) -> list[Score]`; `Score = {rubric, target, value: 1..5, evidence, votes}`. Each judged item
  runs `mgr.call("bench_judge", ...)` a few times → majority/median vote. The
  system-completeness judge is fed named chains to look for (theft→witness→wanted→guard→gossip;
  producer death→price rise; deal→contract+escrow+agenda) and reports which fired.

- [ ] **Step 1: Failing test (stub model)** — `StubMgr` returns `{"value":4,"evidence":"..."}`;
  `judge_npc_realism` over a 1-NPC trace returns one `Score` with `value==4` and a `votes` list.
- [ ] **Step 2: FAIL.** [ ] **Step 3: Implement** (rubric prompts in Russian for the transcript,
  English rubric labels; majority vote helper). [ ] **PASS.**
- [ ] **Step 5: Commit** — `git commit -m "bench: LLM-judge (npc-realism, system-completeness)"`.

### Task 5.3: Wire `--full`

**Files:** Modify `scripts/bench.py`, `bench/report.py`, `bench/dashboard.py`; Test
`tests/bench/test_cli_full.py`.

**Interfaces:** `--full` runs everything `--fast` does plus `run_autonomous` + both judges (using a
stub model in the test), folds `judge` into the report, dashboard renders the scores.

- [ ] **Step 1: Failing test (stub model)** — `main(["--full","--seed","7","--turns","3"])` writes a
  `report.json` whose `judge` block is non-empty.
- [ ] **Step 2: FAIL.** [ ] **Step 3: Implement.** [ ] **PASS.**
- [ ] **Step 5: Commit** — `git commit -m "bench: --full adds autonomous player + judge"`.

**Increment 5 close:** pytest green → `/deploy`. Then a real-LLM smoke run:
`AIDND_PROFILE=deepseek DEEPSEEK_API_KEY=… uv run python scripts/bench.py --full --seed 7 --turns 20`
and eyeball the dashboard.

---

## Increment 6 — CI wiring + docs

### Task 6.1: CI gate + doc update

**Files:** Modify CI config (or add a `make bench-fast` target), `docs/bench.md` (mark shipped),
`docs/README.md` (add the bench row), `README.md` (a run line).

- [ ] **Step 1** Add a CI step running `uv run python scripts/bench.py --fast --seed 7` on a fixed
  seed; it fails the build on a non-zero exit.
- [ ] **Step 2** Update `docs/bench.md`: mark the deterministic layer + dashboard shipped; note
  `--full` is on-demand.
- [ ] **Step 3: Commit + deploy** — `git commit -m "bench: CI --fast gate + docs"` → `/deploy`.

---

## Deferred seam (spec: *Deferred: ground-truth library*)

`oracle.check_all` and both judges already take their checks from lists. The ground-truth library,
when authored, adds entries to those lists (a `bench/ground_truth/*.json` loader → extra oracle
predicates + judge rubrics keyed to a scenario `setup`). No rework — a later plan.

---

## Self-Review

- **Spec coverage:** goal 1 → Inc 2 (coverage) + Inc 3 (adversarial); goal 2 → Inc 1 (trace);
  goals 4/6 → Inc 3 (oracle) + Inc 2 (content-shape in coverage); goals 3/5 → Inc 5 (player+judge);
  dashboard → Inc 4; CI split → Inc 4 (`--fast`) + Inc 5 (`--full`) + Inc 6. Deferred ground-truth →
  seam noted. No spec section is unaddressed.
- **Type consistency:** `TurnRecord`/`Violation`/`ActionCell`/`Score` names are used identically
  across tasks; `record_turn`, `snapshot`, `llm_tap`, `bench_world` signatures match their producers.
- **Placeholders:** none — each task states files, interfaces, a concrete first test, and the TDD
  cycle. Where a task's body is large (oracle, dashboard), the interface + first test pin it; the
  implementer fills the remaining checkers/sections following the shown pattern.

Related: [bench.md](bench.md) (spec) · [loop.md](loop.md) · [structure.md](structure.md).
