# Scene-digest chat — design spec

**Status:** approved design, phased implementation. Date: 2026-07-10.
**Supersedes/updates on ship:** [sound-attention.md](../../sound-attention.md) (rendering),
[npc-brain.md](../../npc-brain.md) (freeform conversation), [service.md](../../service.md) (UI).

## Problem

The chat is the whole game, but today it reads as a pile of disjoint messages: a DM narration
line, separate NPC speech bubbles (name highlighted in gold), and overheard "…word…cutout…"
fragments in three greys. Three concrete failures the player feels:

1. **Sound reads as broken text.** Mechanical word-cutout (`fidelity.cutout`) produces glitchy
   «…золото… не верю…» lines that clutter the narrative and look bad.
2. **A tick is not a scene.** The turn's observable events (ambient sound, NPC actions, near/far
   speech) arrive as unordered channels, not one legible, proximity-ordered account.
3. **Conversation is a separate mode.** `/api/play/talk`+`/say` + `_S["dlg"]` put the player on a
   different pipeline than the ambient world; speaking feels like leaving the world.

And there is no "the narrator is thinking" affordance — the full turn pops in at once after the
blocking LLM call.

## Goal

Every player action produces **one compressed scene account** written at the end of the tick:
the player's result, then the world around them **ordered most-hearable → least** (near speech with
who/what → near actions → ambient → far gomon). NPC *intent* ("идёт к бочке") is a thought and never
appears; only observable sound/action does. Distance degrades detail **semantically** (authored by
the narrator), not by deleting words. Conversation runs through the *same* pipeline. The narrator's
prose **streams token-by-token** with a ChatGPT-style "собирается…" indicator.

Two render treatments, both validated in the mockup (`aidnd-play-redesign.html`):
- **Вместе (together)** — one woven paragraph; proximity carried by wording + order (+ optional
  distance dimming under the "Дальность" tone).
- **Раздельно (split)** — player-result line + a banded «в сцене» digest (рядом / звук / в глубине).

Design decisions locked with the user:
- **No NPC name highlighting** (drop the gold speaker names).
- **Order most-hearable → least.**
- **Single tone is the default**; a "Дальность" toggle adds proximity dimming (near ink → far dim →
  ambient faint). No color-coding of speakers ever.
- **Sound model = sealed box:** a building you're outside of contributes nothing to the digest.
- **True token streaming** from the LLM (not a client-side fake).
- The **3-card layout stays** (left rail map/ways, center chat, right rail hero/bag/jobs).

## Architecture

### The tick → digest pipeline

```
player action
  → resolve(text)                        LLM arbiter → intent/plan          (unchanged)
  → _run_plan/_attempt                   player-result strings in res["narr"]
  → _world_tick / _live_tick             NPC conductor → feed[] + address[]  (unchanged core)
  → scene_digest(res, t, sc)             NEW: gather observable events, order by proximity,
                                         author ONE compressed World turn (streamed)
  → response {digest, events, …}         NEW contract; legacy narr/feed/address kept for a transition
```

**Seam:** `handlers/freeform.py::act()` immediately after `t = _world_tick()`, where
`res["narr"]` (player result), `t["feed"]` (deed/speech w/ tier), and `t["address"]` (direct-to-
player) are all in scope. The other tick endpoints (`say`/`talk`/`move`/`live`/`zone`) call the same
shared helper so every entry point emits a digest.

### The event model (structured, deterministic)

Before any narration, the tick's observables are normalized into one ordered list:

```python
Event = {
  "band": "result|near|ambient|far",   # proximity bucket, drives order + split-mode grouping
  "kind": "result|speech|action|sound",
  "actor": str | None,                 # display name, NOT id; None for ambient
  "text": str,                         # observable content only
  "audible": float,                    # 0..1 for ordering within a band
}
```

Mapping from current data:
- `res["narr"]` player result → `band=result`.
- `address[]` (direct-to-player, nearest) → `band=near, kind=speech`.
- `feed[] kind=speech tier` → tier 1 → `near`, tier 2 → `near/far` boundary, tier 3 → `far`.
- `feed[] kind=deed` that is a **sound** (idle-ambient, murmur backstop) → `band=ambient, kind=sound`.
- `feed[] kind=deed` that is an **observable NPC action** → `near/far` by the actor's zone tier.
- Ordering: `result` first, then `near`, `ambient`, `far`; within a band by `audible` desc.

Proximity is already computed upstream (address = nearest; speech carries tier). We reuse it — no new
audibility math.

### `does` gating (no intent leak)

`world.py` `does` (model-authored NPC self-narration) is the one ungated path where movement/intent
("идёт к очагу") can surface. Rule: a `does` deed enters the event list only if it is **observable to
the player** — same/adjacent zone (tier ≤ near threshold) — otherwise it is dropped from the digest
(it still lands in NPC memory / debug log). Movement phrasing is never authored by the digest
narrator; only the composed observable result is.

### The scene narrator

A new narrator call (`narrator` role, reuse `mgr.call`) that consumes the **structured event list**
(not free text) and returns the woven Together paragraph, following: result first; near before far;
distance degrades detail; **do not name the speaker as a highlight**, weave naturally; never invent
events not in the list; keep it compressed. The Split view is rendered directly from `events` with no
extra LLM call (band-grouped). Per **no-fallback**: narrator down → 503 + honest error, no stub.

### Streaming

Add a `StreamingResponse` (SSE, `text/event-stream`) variant of the turn endpoint. Run the blocking
tick in a threadpool; bridge the narrator's `on_token` into an `asyncio.Queue` drained by the SSE
generator. Emit `token` events for the narrator prose, then a final `done` event carrying the rest of
the payload (`events`, `gt`, `coins`, `hp`, control flags). Add `stream=True` + SSE line parsing to
`OpenAICompatBackend.chat` so prod (DeepSeek) streams; Ollama already streams. Mid-stream failure
flushes what streamed + an error tail (retry only before first token).

### Frontend

- New `.world` message renders the digest. Default **single tone** (`--ink`), no speaker highlight.
  `data-tone="grad"` adds ambient=faint-italic / far=dim. `Вместе`/`Раздельно` toggle (setting).
- Processing indicator: breathing "сцена собирается…" row (replaces the `…` placeholder) + a header
  pulse; input stays typeable, send flips to stop during stream. `prefers-reduced-motion` → instant.
- Token stream appends into the `.world` node with a caret.
- Keep the panel-morph state machine, `renderAmb`, work-panel toggling untouched.

### Conversation merge (Increment 4)

Remove `mode='dialogue'`, `#talkchip`, `/api/play/talk`+`/say` client paths. Player speech is a
normal `act()` intent; the addressed NPC's reply comes back as a `near` event in the digest. Keep the
`convo.py` answer-debt layer (drives who replies next tick). `_S["dlg"]` coupling retired.

## Increments (each green → commit; deploy per deploy-autonomously once user-confirmed)

1. **Frontend chat rework — ✔ on prod (commit 06072da).** Single-tone taxonomy, drop NPC gold highlight, reorder each
   turn most-hearable→least (narr → address → feed speech tier 1→3 → deeds/ambient last), breathing
   processing indicator, reduced-motion. Driven by the *existing* response (no backend change).
   Verify: serve play.html with a mocked `/api/play/act` response, drive it, screenshot.
2. **Scene narrator + `does` gating.** Structured event model in a shared tick helper; end-of-tick
   scene-narrator weaving (Together); Split rendered from `events`. Unit-test event assembly +
   ordering with a stub LLM. New `digest`/`events` fields; legacy fields kept.
3. **True token streaming.** SSE endpoint + threadpool/queue bridge; client reader with caret + stop;
   `OpenAICompatBackend` stream parsing for prod. Verify local (Ollama) + a prod smoke.
4. **Merge dialogue into the tick.** Retire the dialogue-mode path; speech flows through `act()`.

## Testing

- Deterministic event assembly + ordering: pure unit tests (`tests/`), stubbed inputs.
- Frontend: browser-driven with mocked fetch (preview tools) — order, single tone, no highlight,
  processing indicator, reduced-motion.
- Scene narrator: live-LLM scene bench asserting no invented events, result-first, near-before-far,
  no speaker highlighting, no movement/intent phrasing.
- Streaming: token arrival order; mid-stream failure tail; prod DeepSeek smoke.

## Risks

- **Extra LLM call per tick** (scene narrator) — cost/latency. Mitigate: one call, compressed; Split
  needs none. Measure before/after.
- **Streaming prod blocker** — DeepSeek SSE parsing must be added; retry semantics after first token.
- **Regression surface** — `feed`/`address` feed six endpoints; the shared helper must cover all.
- **`does` over-gating** — dropping legitimate observable actions; tune the tier threshold with the
  scene bench.
