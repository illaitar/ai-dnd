# NPC brain & entity — perception, appraisal, attention (design)

How an NPC (and the player — they are the *same entity*) sees others, forms opinions from what it
sees, and spends its one action per tick. Extends [mind.md](mind.md); nothing here rebuilds the
utility core — it widens the appraisal and attention that already run. Design, not yet built.

## Guiding principle: one entity, read not role-checked

There is no "player object" and "NPC object" — there is one **entity** (mechanical core + a
two-layer visible surface + a mind), and the player is one instance of it. Every system reads the
entity's real attributes, never a `if player` branch. Consequence you get for free: a filthy,
low-status player walks into a tavern and a proud citizen recoils and sits across the room — *the
player has become the beggar*, mechanically, because the appraisal reads a `Body`, and the player
is a `Body`.

## The entity

- **Mechanical core** (forged in the pool, mirrored into the mind `config`): identity (name, sex,
  race, life-stage, build), the **11 traits**, the **6 abilities**, charisma, appearance/status.
- **Mind** (`mind.NpcState`, per-user runtime): 7 needs, emotions, relationships
  `{trust, affinity, fear}`, episodic memory, agendas, plan, mode.
- **Player parity** — TODO. `_pc()` is already an `NpcState` with memory/relationships and a `Body`
  whose `appearance = 0.25 + coins/60` (a broke player already reads poor). Two gaps: (1) the
  player's traits are flat defaults (0.5) — give the player a real mech-core so others can read
  *their* pride/malice; (2) the player's `Body` carries only wealth — project the same visible
  **surface** (below) onto it so the appraisal treats the player identically.

## Two-layer visibility

Same shape as the item factsheet (`surface` may lie · `hidden` behind gates). The boundary is
**concealability**: what you broadcast across a room and can't hide vs. what you (or effort/skill)
can conceal.

- **Surface** — glance, free, read by anyone present: race/species, sex, build & life-stage,
  status/dress-tier (from `appearance`), **hygiene/condition** (the beggar's squalor), worn
  demeanor (current *shown* emotion), openly-worn role-dress & marks (uniform, holy symbol, scar,
  brand), openly-carried arms/armor. Surface **can lie**: a noble in a cloak reads poor; a killer
  in a friar's robe reads safe.
- **Hidden** — needs a gate (perceiver `attention`/perception check · an `observe`/inspect action ·
  interaction · or beaten by the concealer's skill): true name (`_met` already), true wealth (purse
  under rags), concealed weapon, true role when not dressed for it, **true feelings when masked**
  (a deceptive high-charisma NPC's shown demeanor ≠ real emotion), `persona.secret`, hidden
  injury/disease, intent.

Reveal reuses existing machinery: `attention` (vigilance stat), the items inspection gates, `_met`
for identity. The gap between the layers — surface says one thing, hidden says another — is what
makes disguise, mistaken first impressions, and "something's off about him" real.

## Emotions: add `disgust`

Emotions become **5**: `anger, fear, joy, distress, disgust`. `disgust` is the beggar/squalor
outcome — add it to `EMOTIONS`, give it an `emotion_gain`/`emotion_baseline` entry (driven by
`pride`), and let appraisal raise it.

## Appraisal: three tiers, author only what personality can't imply

When A appraises B, A's standing attitude toward B's *kind* comes from three tiers. Author only the
one traits genuinely can't derive.

- **A — derived from traits (emergent, zero authoring)** — the personality dimension: a fixed map
  `d(A.traits, B.surface) → sentiment`, like the trait→`emotion_gain` map the mind already has.
  Examples: disgust at squalor ≈ `pride × (1 − B.status)`; contempt/predatory read ≈
  `malice × (1 − honesty)`; wariness ≈ `(1 − bravery) × B.armed` and `lawful × B.criminal-marks`;
  warmth ≈ `sociability × B.charisma`; deference toward high status, amplified by low `ambition`.
  A proud citizen sits away from a beggar with **nothing authored** — it falls out of his traits
  meeting the beggar's surface.
- **B — group/cultural tables (authored once, world-wide)** — cultural facts traits can't derive
  (a timid, kind dwarf still inherits "distrust orcs"). A small `content/` table
  `race × race → sentiment` (and optionally faction/class); every member reads it, their own traits
  modulate it. Shared by thousands of NPCs, not per-NPC prose.
- **C — personal history (already exists)** — "the orc who killed my brother." `relationships` +
  `memory` + persona `ties`.

**Combination:** `impression(A,B) = A[traits×surface] + B[culture] + C[personal]`, with
**personal > culture > personality** — so "he's an orc *(hate)*, but he saved my life *(trust)*"
resolves to warmth. That single ordering gives you bigotry *and* its redemption.

`impression` is an **Impression** `{valence, emotion-deltas, remember?, relationship-prior}`.

## The pipeline

```
perceive present bodies
  → read each Body's SURFACE (HIDDEN only if a gate is passed)
  → appraise: A(traits×surface) + B(culture) + C(memory) → Impression
  → apply: emotion-deltas (incl. disgust) via appraise() · seed a relationship PRIOR for strangers
           (today they start neutral) · write memory ("a filthy beggar by the fire")
  → decide: goals (as today: acquire/harm/safe/converse) + a PROXEMICS term
```

This is not a new subsystem — the loop **perceive → appraise other → goal → utility → act** already
runs in `goals.py` (it reads `b.appearance`/`b.charisma`/`hostility` today; the code even comments
`← LLM value appraisal connects here`). We widen *what* it reads (full surface) and *what responses*
it produces (disgust + proxemics + relationship priors).

## Proxemics (emergent)

No "avoid" primitive. Add a social term to the existing zone/move utility: prefer positions that
maximize distance from disliked entities and minimize from liked ones —
`+ Σ impression(other) × proximity(zone, other)`. Negative impression → distant seat; positive (or
high charisma) → the next stool. It gives *approaching* someone attractive for free, and stays
personality-driven (a kind NPC barely disperses; a proud one crosses the room).

## Attention & relevance economy

One action per tick (occasionally two). Today the player mobs on entry because (1) entry is the one
salient event, (2) the keeper's "serving" is **not a modeled action** — his `work` is a *place*, so
his free action has nothing to lose to, and (3) nothing budgets how many NPCs attend one event or
gates *relevance*. There is only crude decay ("they've had their look, back to business" after ~3
ticks). Make attention a **contested resource**:

- **Earned salience.** An entity is salient when *new* (novelty, which **decays**), when it *did
  something* (spoke, drew steel, is wanted), or when it's *relevant to that NPC's goals* (a customer
  to the keeper, a mark to the thief). Absent a reason, a busy NPC does not turn.
- **Current activity is an importance-weighted commitment.** The mind already has `engagement` and
  `plan.importance` = "resistance to interruption" — underused. Model an NPC's real task (serve the
  queue, finish a chat) as a plan with importance; greeting a stranger must **beat** it. So the
  bored regular greets you; the harried keeper gives a nod and keeps pouring.
- **No player privilege.** The player competes for attention exactly like a salient NPC would.

## Conversation is freeform — no dialogue interface

There is **no separate dialogue mode, panel, or reply-thread**. Talking is a freeform world action:

- You type what you say — to a person or to the room. The arbiter (`resolve`) picks the target via
  the existing `say`/`talk` primitives (target `npc` or none = the room).
- Present NPCs **hear** it (perception), **appraise** it (tone, content, who you are), and the
  **attention economy** decides who — if anyone — responds. Replies are `address`/feed lines in the
  live scene, not a locked exchange.
- **Interruption is a costed social action**, both ways: you can barge into an NPC↔NPC chat (a
  social move that spends their patience/affinity); a busy NPC can defer you ("одну минуту") or stay
  silent — the scene already supports "не вступает в разговоры".
- `_voice` (NPC speech generation) stays, but is invoked by the **scene brain**, not a dialogue
  endpoint. **Remove:** the `/talk` `/say` dialogue handlers and the freeform `talk`→`open_talk`
  modal; `converse` stops being a UI mode and becomes ordinary attention held within the freeform
  scene.

## What we keep vs. change

- **Keep / extend:** `appraise()` (dims→emotion), the `goals.py` appraisal loop, `Body` surface,
  the `converse` goal formula, `engagement`/`plan.importance`, `salient`, `_met`, the items
  inspection-gate model, the utility core.
- **Add:** `disgust` emotion; a full visible **surface** on every `Body` (incl. the player);
  identity appraisal on perceive → `Impression`; a `race × race` (± faction/class) sentiment table;
  the proxemics utility term; earned-salience + importance-weighted-activity attention; a real
  mech-core (traits + surface) for the player.
- **Remove:** the separate dialogue interface (all talking is freeform).

## Open decisions

- Where the player's real traits come from (character creation vs. a chosen archetype vs. derived).
- Exact `content/race_relations.json` values (and whether faction/class get tables now or later).
- Whether "current activity as a plan" needs new authored tasks (serve/tend) or can derive from
  `work` + place.
- Non-goal for now: persistent health/injury, numeric age, skills beyond the 6 abilities (Seam ③).

Related: [mind.md](mind.md) (utility core) · [entities.md](entities.md) · [items.md](items.md)
(surface/hidden precedent) · [locations.md](locations.md) (zones/proxemics) · [loop.md](loop.md)
(the tick, freeform `/act`).
