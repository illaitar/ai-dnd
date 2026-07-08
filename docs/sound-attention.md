# Sound & attention (design)

How an entity **hears** its surroundings and how what it hears **competes for its one action per
tick**. Two coupled pillars — *audibility* (what reaches you, at what fidelity) and the *attention
economy* (what you do about it). Extends [mind.md](mind.md) (utility core) and
[npc-brain.md](npc-brain.md) (perception/appraisal, which shipped Subsystem 1); the attention
economy sketched there is fully specified here. **Pillar 1 (sound & audibility) is on prod**
(commits 92f3b53..71f32e6); **Pillar 2 (attention economy) is designed, not yet built.**

## Guiding principle: one entity, hearing is symmetric

The player and every NPC are the **same entity** ([npc-brain.md](npc-brain.md)). Hearing is one
function applied to all of them: an NPC across the room and the player overhear the *same amount* of
a conversation, because both go through the same distance→fidelity rule. There is no "player hears"
path and "NPC hears" path — there is one `audibility()`, read not role-checked. What differs is only
the sink: the player's overheard text renders to the scene window; an NPC's becomes a low-weight
memory and a salience contribution.

Audibility is **pure arithmetic** (distance × loudness) over the present entities each tick — **no
LLM**. Only two things ever reach the model: the player's scene text, and the narrator's ambient
context. This keeps the per-tick, per-NPC hearing path cheap enough to run for everyone present.

---

## Pillar 1 — Sound & audibility

### 1. Sound sources (authored layer)

A new `content/sound_sources.json`, keyed by **object-kind** and **zone-kind**, each entry
`{loudness: 0–1, ambient_ru: "потрескивает очаг"}`. The furnish pipeline
([worldgen.md](worldgen.md)) reads it: any zone holding an emitting object (`очаг`, `горн`, …) or an
inherently-noisy zone-kind gets a **fixed sound source** at that zone's centroid, carrying the
authored `loudness` and Russian ambient phrase.

**Crowd murmur** is the one *dynamic* source, not authored per-instance: computed per zone at
runtime as `occupancy × zone.noise` (`noise` already exists on every furnished zone). It has no
ambient phrase — it is the generic hum a busy room makes.

### 2. Zone centroids — distance is spatial (model C)

Zones today carry `{id, kind, name, noise, …}` but **no geometry** — centroids only exist inside the
offline floor-art renderer. `floorplan.plan_location` is deterministic, so furnish computes each
zone's centroid `(cx, cy)` once from its rect (`cx = x + w/2`, `cy = y + h/2`) and **stores it on the
zone record**, so it rides into the live scene (`lv["zones"]`).

`audible_distance` between two co-located zones = **Euclidean distance between their centroids**. Two
entities in **different buildings** or out on the **street** share no coordinate frame → they fall to
the "far" tier by rule (no cross-building spatial distance).

### 3. One audibility function, all sources

For a listener and a sound (conversation *or* ambient source), both positioned at a zone centroid:

```
heard = loudness − k · audible_distance
tier  = L1 if heard ≥ t1 · L2 if heard ≥ t2 · L3 if heard ≥ t3 · else inaudible
```

`k`, `t1`, `t2`, `t3` live in the `PB` table (engine/core.py), not in code
([principle 4](README.md)). One formula covers everything: a quiet fireplace (low `loudness`) is L1
only in its own zone; a **shout** (high `loudness`) carries to L2 across the room and L3 by the door.
A conversation's loudness is set by its register — whisper < normal < shout — so the same function
gives eavesdropping *and* a room-silencing yell for free.

### 4. Fidelity — split by source type

- **Conversations → deterministic random word-cutout (no LLM).**
  - **L1** — the line **verbatim**.
  - **L2** — a **random word-cutout** of the line, stitched with «…» (keep a fraction of the words;
    seed the RNG on `(line, listener, tick)` so it is stable within a tick and identical for the
    player and any NPC at the same tier).
  - **L3** — **presence-only**: "у дальнего стола о чём-то спорят" (that a conversation exists, not
    its content).
  The **same** cutout function feeds the player's scene text and an NPC's memory line. An overheard
  memory keeps today's low weight (≈ 0.3, the existing `(подслушано — …)` weight), scaled down by
  tier.

- **Ambient sources → narrator context, never masked.** Audible ambient sources are collected per
  location and handed to the narrator as **context** ("слышно: очаг потрескивает, точильный
  камень"); the narrator weaves them into prose. NPCs do not record ambient text — ambient feeds
  mood/comfort and salience, not memory content.

### 5. Rendering & focus (player)

- **Not in a directed exchange this tick** → the scene window shows all audible conversations as a
  **darkness gradient**: L1 at `--text-primary`, L2 at `--text-secondary`, L3 at `--text-muted`. No
  color legend — the darkness *is* the distance cue.
- **In a focused exchange** (the player's action is a directed `say`/`talk` to a target) → that line
  renders **full-strength**; the ambient gradient stays dim behind it.

This **generalizes the existing `_dm_snapshot` overheard logic** (`world.py`, the
`same_zone / eaves / murmur` block), which today is a crude 2-level "verbatim if same-zone, else a
murmur counter," into the symmetric 3-tier spatial model. The player-only `listen` primitive
(perception roll buying a hearing tier for `listen_ticks`) still works — it becomes a *modifier* that
lifts the player's effective tier on a target, on top of the ambient audibility everyone gets.

---

## Pillar 2 — Attention economy

The full economy sketched in [npc-brain.md](npc-brain.md). Its foundational call: **salience is a
utility term**, not a separate interrupt gate. "React to an event" is an ordinary candidate action;
the mind's existing arbiter picks the max-utility action, so *who reacts, how many, and whether the
player is special* all emerge from machinery that already runs.

### 1. Salient events per tick

The present scene emits events; each is scored **per listener**:

```
salience(E, obs) = base(type) × audibility_tier(E, obs) × relevance(E, obs) × novelty(E)
```

- **base(type)** (weights in `PB`): drawn steel > shout > arrival > speech > ambient.
- **audibility_tier** — straight from Pillar 1 (L1 ≈ 1.0 · L2 ≈ 0.5 · L3 ≈ 0.2 · inaudible ⇒ the
  event does not exist for that listener). **This is the concrete seam between the two pillars.**
- **relevance(E, obs)** — self-reference (the observer's **name / faction / race** spoken ⇒ large),
  goal-relevance (a customer's call to the on-shift keeper; a mark to the thief), and **impression
  valence** toward the actor, reusing `impression()` from the shipped perception subsystem — you
  attend the person you love or loathe more than a stranger.
- **novelty(E)** — fresh events spike and **decay per tick**, replacing today's crude "~3 ticks then
  back to business."

### 2. Reactions are candidate actions

For the top events, the mind proposes reaction actions — `notice`/`look`, `address`/`reply`
(the `converse` primitive), `approach` (the `move` primitive), `investigate` — each with **utility =
salience(E, obs)** (× a small per-reaction shaping). They enter the existing `propose_goals` arbiter
([mind.md](mind.md)) beside the NPC's ordinary candidates (a need, an agenda, work). **No new
decision path** — the arbiter already picks max-utility.

### 3. Derived "keep working" duty — the thing salience must beat

The tavern-mob root cause: the keeper's `work` is a *place*, not an action, so his free action has
nothing to lose to and he greets every entrant. Fix: an **on-shift entity at its workplace during
`open_hours`** gets a derived **"keep working"** candidate whose utility comes from the `purpose`
need + being on shift — **no per-role task lists**. Now a stranger's low-salience entry loses to the
keeper's duty but still beats a **bored regular's** weak best action. The mob is fixed by *making
work worth doing*, not by capping greeters.

### 4. Emergent contention, no player privilege

Because reactions are utility-scored candidates, "how many turn" falls out of salience vs. each NPC's
own best action — **no attention budget, no cap** ([remove all caps / no mechanical
gates](README.md#cross-cutting-principles-violation--review-failure)). The player is scored by the
same `salience()`: a filthy **unknown** entering is *low* base novelty to a busy NPC — the beggar
parity from [npc-brain.md](npc-brain.md), now on the attention axis too.

### 5. Interruption is competition, both ways

Barging into an NPC↔NPC chat is a reaction action competing with that chat's current utility; a
keeper "deferring you" ("одну минуту") is simply his duty out-scoring your address. The player's
**focus** (Pillar 1 rendering) is the player-side of the same coin — the player commits an action to
one target; NPCs commit via utility.

---

## What we keep vs. change

- **Keep / extend:** the `audibility` generalization of `_dm_snapshot`'s overheard block; the
  player `listen` primitive (becomes a tier modifier); `propose_goals`/utility core; the `converse`
  and `move` primitives; `impression()` (shipped); the `novelty` need; `engagement` /
  `plan.importance` for stickiness; the ≈ 0.3 overheard memory weight.
- **Add:** `content/sound_sources.json`; per-zone centroids in furnish; `audibility()` +
  audibility `PB` thresholds; the deterministic conversation word-cutout; the 3-tier scene-window
  gradient; audible-ambient → narrator context; `salience()` + the per-tick event set + per-event
  novelty decay; salience reactions as candidate actions; the derived "keep working" duty candidate
  + its `PB` weights.
- **Remove:** nothing — this widens existing machinery.

## Increments (each green → commit → deploy)

**Pillar 1 — sound & audibility — ✔ on prod (Increments 1–3).** Note carried into Pillar 2:
**symmetric NPC overheard memory** (a bystander NPC recording a tier-weighted overheard line) is
*not* wired yet — the `audibility()` core is symmetric, but only the player's overheard memory is
written today; it folds naturally into Pillar 2, where overheard content becomes a salience input.
Follow-ups: the narrator's conversation context (`resolve.py` "ПОСЛЕДНИЕ РЕПЛИКИ") still uses the
old same-zone/eaves gate rather than the 3-tier model; the live 3-grey gradient wants an eyeball in
playtest.
1. **Audibility foundation.** Per-zone `(cx,cy)` in furnish; `content/sound_sources.json`; pure
   `audibility(listener_zone, source_zone, loudness) → tier` + `PB` thresholds. Unit-tested; no
   behavior change yet.
2. **Conversation fidelity + 3-tier player rendering.** Generalize `_dm_snapshot`'s overheard path
   into the spatial 3-tier model; deterministic word-cutout; darkness gradient in `play.html`; NPC
   overheard → low-weight memory. *First visible player win.*
3. **Ambient → narrator context.** Collect audible ambient per location; feed the narrator prompt so
   the fireplace/forge surface in prose.

**Pillar 2 — attention economy**
4. **`salience()` + per-tick event set.** Speech / arrival / loud-oneoff / ambient events, scored
   per listener (audibility × base × relevance × novelty) with per-event novelty decay. Pure +
   tested; computed and exposed, no decision change yet.
5. **Reactions as candidate actions.** `notice`/`address`/`approach`/`investigate` enter
   `propose_goals` with utility = salience; NPCs react via the utility arbiter.
6. **Derived "keep working" duty.** On-shift entities get a real duty candidate — fixes the tavern
   mob. *Playtest milestone.*

Related: [mind.md](mind.md) (utility core, primitives) · [npc-brain.md](npc-brain.md)
(perception/appraisal, attention sketch) · [locations.md](locations.md) (zones, `_dm_snapshot`,
scene conductor) · [loop.md](loop.md) (the tick, `listen` primitive, eavesdropping) ·
[worldgen.md](worldgen.md) (furnish, floorplan).
