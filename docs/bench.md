# End-to-End Benchmark

A benchmark that plays the real game over HTTP and judges it against six goals. Two layers:
a **deterministic invariant layer** that gates every run, and an **LLM exploratory + judge layer**
for emergent quality. In-game interactions are Russian (the real game); the trace, assertions and
report are English (dev-facing).

## Goals

1. **Action coverage** — the player can perform every action that looks legal.
2. **Full observability** — we can see everything a turn produced, frontend and backend.
3. **NPC realism** — NPCs act like real players: logical actions, organic reactions to the player.
4. **World integrity** — the world does not let the player bend it.
5. **System completeness** — our systems feed each other (the "stitching" seams).
6. **Content shape** — our systems generate content in the intended form.

Goals 1/2/4/6 are **hard invariants** (assertions, pass/fail). Goals 3/5 are **soft quality**
(LLM-judged, scored). The benchmark covers both.

## Shape

- One run = one **fresh seeded world** (fixed seed → `worlds.db` pool → clean `live.db`), a real
  FastAPI server, N turns driven over `/api/play/*` exactly as the browser does. Torn down after.
- Driving over real HTTP is deliberate: it captures the true response contract (the "frontend"
  of goal 2) and catches serialization/auth/API-shape regressions an in-process harness would miss.

## Components

1. **Runner** — seeds a world, starts the app, creates a benchmark user, drives turns, tears down.
2. **Trace recorder** — the spine both layers read (see *Trace substrate*).
3. **Player driver** — three modes feeding the same trace: coverage, autonomous LLM player,
   adversarial prober (see *Player driver*).
4. **Invariant oracle** — mechanical checkers over the trace (see *Invariant oracle*).
5. **Judge** — LLM-judge with rubrics for goals 3 and 5 (see *Judge*).
6. **Reporter** — aggregates coverage + invariant results + judge scores → `report.json` + verdict.
7. **Dashboard** — self-contained HTML over the run's trace + report (see *Dashboard*).
8. **Ground-truth library** *(deferred)* — designer-authored scenarios; slots into oracle + judge
   as extra entries without rework (see *Deferred*).

## Trace substrate (goal 2)

Per tick the recorder writes one turn record with four faces:

- **`input`** — the action: endpoint + params, or freeform Russian text plus the resolved
  intent/plan from `resolve()`.
- **`frontend`** — the exact response JSON the client would receive (scene dict, `narr`, `feed`,
  `address`, hp/coins/mana/gt deltas). This is the frontend truth.
- **`backend`** — a deep snapshot via a benchmark-only introspection hook: `_S` session
  (loc/inside/time/wanted/flags), present-NPC mind state (needs/emotion/relationships/memory-size/
  agenda), row-level `live.db` deltas since last tick (inventory, purse, flags, deeds, npc_state,
  contracts), economy (`M`, chain stocks/prices), ring-B positions (`crof`).
- **`llm`** — every model call this tick (role, prompt, raw output, parsed+clamped result, latency),
  captured through the existing `ModelManager.on_call` hook.

The record is fully replayable: what the player did → what the UI showed → what the backend became
→ every LLM decision behind it. Written as per-turn JSONL to `data/debug/bench/<run-id>/`.

## Invariant oracle (goals 4, 6)

Pure functions over consecutive trace records. Each failure emits
`{invariant, turn index, before/after trace slice}` so the dashboard shows exactly what bent.

- **Conservation.** Town money `M` is invariant except legal player in/out (loot influx / spend).
  `economy.py` already conserves `M`; the oracle proves it holds under play.
- **Provenance.** Every item / coin / key / glyph the player holds traces to a legal acquisition
  event in the deeds / inventory log (bought, looted, crafted, given, taken-with-a-recorded-crime).
  Nothing appears without a cause.
- **Narrator containment** *(the "doesn't bend" core)*. On any turn whose only mechanism was
  narration, backend deltas must be ⊆ the six clamped consequence types — no hp/coin/item/flag
  change the code did not author. The narrator may describe, never grant.
- **Legality gates.** Every adversarial-prober cheat yields a refusal + zero illegal delta: a pinned
  item won't lift, an unreachable node won't move, out-of-hours trade is refused, the dead stay
  dead, a purse never goes negative, a phantom key won't open a lock.
- **Content shape (goal 6).** Every LLM output validates against its schema (Intent / Verdict /
  SpellLaw / Persona / Contract — ad-hoc now, or via `inference/schemas.py` when it lands). Every
  generated artifact is well-formed: city graph connected, every NPC housed + placed + jobbed,
  economy seeded (`M` > 0, chains wired), floorplans reachable (BFS), dungeon connected with a goal,
  scene dict schema-valid.

## Player driver (goals 1, 3, 5)

- **Coverage driver (goal 1).** An action matrix built from the `PRIMITIVES` registry
  (verb × targets × manner) and the `/api/play/*` catalog. For each cell the harness constructs a
  valid context and fires it, asserting a legal outcome. Coverage = % of cells exercised in a valid
  context. A cell nobody can legally reach is itself a finding.
- **Autonomous LLM player (goals 3, 5).** A Russian-speaking agent: given a persona + goal + the
  scene JSON, it emits the next Russian action (freeform or UI). A few personas (cautious trader,
  greedy rogue, curious wanderer) drive variety across N turns. It roams, pursues goals, talks to
  NPCs — producing the organic transcripts the judge reads.
- **Adversarial prober (goal 4).** A cheat suite (narrator-grant exploits, phantom keys, taking
  pinned items, walking to unreachable nodes, reviving the dead, double-spend, out-of-hours trade),
  each asserting the world refuses.

## Judge (goals 3, 5)

LLM-judge with rubrics over trace windows, scored 1–5 with evidence. Each call runs a few times /
multiple lenses → majority verdict, to dampen judge noise.

- **NPC realism (goal 3).** Given an NPC's persona + memory + situation and its action/reply: in
  character? logical? did it *react* to what the player actually did (not generic)? Flags: memory
  contradictions, ignoring a salient event, out-of-character tone, hallucinated town facts.
- **System completeness (goal 5).** Given a sequence: did systems feed each other? Named chains to
  look for — theft → witnesses → wanted → guard reaction → gossip → memory; kill a chain producer →
  downstream price rises; deal struck → contract + escrow + agenda; NPC critical need → routine
  shifts. The judge reports which chains fired and which did not.

## Dashboard (Addition 1)

Self-contained HTML (no external assets), reading the run JSONL + `report.json`: top-line verdict,
coverage heatmap, invariant pass/fail (each expandable to its before/after trace slice), judge
scores per rubric with example transcripts, and a runs-over-time trend so regressions are visible.

## Run modes / CI split

- **`bench --fast` (CI gate).** Coverage driver + adversarial prober + invariant oracle +
  content-shape. Deterministic; cheapest LLM profile only where a path requires the model. Fails the
  build on any invariant/legality break or coverage regression.
- **`bench --full` (on-demand / nightly).** Adds the autonomous LLM player + judge for goals 3/5.
  Costs model; produces scores, not a hard gate.

Note the `no-LLM-fallback` principle: the live scene (ring A, `resolve`, `voice`) *requires* a
model, so `--full` needs a real LLM — you cannot Stub the very thing goal 3 measures. The
invariant / worldgen / ring-B checks are mostly LLM-free.

## Layout

```
bench/
  runner.py        seed world · start app · drive turns · teardown
  trace.py         per-tick recorder (input/frontend/backend/llm) → JSONL
  drivers/         coverage.py · autonomous.py · adversarial.py
  oracle.py        invariant families (conservation/provenance/containment/legality/shape)
  judge.py         LLM-judge rubrics (npc-realism, system-completeness)
  report.py        aggregate → report.json + verdict
  dashboard.py     JSONL + report → self-contained HTML
scripts/bench.py   entry (--fast / --full); extends the existing script
data/debug/bench/<run-id>/   trace.jsonl · report.json · dashboard.html
```

## Deferred: ground-truth library

Designer-authored scenarios — "here is what I want to happen" — captured as an external source of
truth beyond internal consistency. Each scenario sets up a situation, plays it, and checks the real
run against the author's expected beats (mechanically where concrete, by judge where it is tone).
The oracle and judge read their checks from a list, so the library appends entries without rework.
To be authored later.

Related: [loop.md](loop.md) (the turn) · [mind.md](mind.md) (NPC realism) · [citysim.md](citysim.md)
(the stitching seams) · [worldgen.md](worldgen.md) (content generation) · [structure.md](structure.md)
(`inference/schemas.py`, the content-shape boundary).
