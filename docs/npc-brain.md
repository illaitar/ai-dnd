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
  **race**, **numeric age** → life-stage, build), the **11 traits**, the **6 abilities**,
  **skills** (learned proficiencies, below), charisma, appearance/status.
- **Body / condition** (persistent, per-user): **hp / max_hp** (real, not just combat-time) and
  **injuries** (persistent wounds/illness that heal over time and modify abilities/actions).
- **Mind** (`mind.NpcState`, per-user runtime): 7 needs, emotions, relationships
  `{trust, affinity, fear}`, episodic memory, agendas, plan, mode.
- **Player parity** — the player is one instance of this entity, judged like any stranger by
  **surface + behaviour**, not an internal personality: traits are hidden, and the *human* drives
  the player's choices, so the player does **not** get a game-side trait allocation. What the player
  needs is a real **surface** (appearance/hygiene/dress/race/age — settable) so a ragged player
  *reads as a beggar*, plus hp/injury/age/skills like anyone. (`_pc()` is already an `NpcState` with
  memory/relationships and a `Body` whose `appearance = 0.25 + coins/60`; we add the rest.) Only the
  **autonomous benchmark player** ([bench.md](bench.md)) gets a trait vector, because it must decide
  on its own.

## Body & lifecycle — health · injury · age · skills

Pulled in from the earlier non-goals: the entity is a full body, not a mind on a stick.

- **Health** — `hp/max_hp` become **persistent** (today hp is default 10 in the mind and only
  computed at combat). `max_hp` derives from the mech-core (con + build + age); current hp persists
  in `npc_state`/`pc_state`, regenerates slowly (a heal tick, like needs advance) or via rest/care/a
  healer (знахарка). `hp ≤ 0` = death (corpse + witnesses, as combat already does).
- **Injury / illness** — a list of persistent **conditions** (bleeding, broken limb, fever, poison)
  that modify abilities/actions (a broken arm drops `str`/`dex`), heal over game-time or with care,
  and are **surface or hidden** (a limp shows; an early fever is hidden until close). They arise from
  combat, hazards, hunger/exposure, disease, and feed appraisal (a visibly sick or maimed person
  draws pity, disgust, or avoidance by trait).
- **Age** — a **number** (life-stage `child/adult/elder` derives from it). Shapes the mech-core
  (elders: lower str/con, higher wis/skill; children: lower across the board), is a surface signal,
  set at pool-forge (`depgen` already assigns stages). Aging over play is slow — a stored number,
  not a live clock, for now.
- **Skills** — learned **proficiencies** beyond the 6 abilities: a per-entity level in a set of
  competencies (smithing/metalwork, herbs/medicine, letters/lore, trade, faith, law, stealth,
  weapon-skill, persuasion…). This **unifies** three things already half-built: the items
  `COMPETENCIES` list (inspection gates), craft `mastery`, and role. Skills gate & modify **rolls**
  (`d20 + ability-mod + skill`), so a skilled smith forges masterwork and a skilled thief lifts a
  purse a novice can't. Gained by **doing** (practice) and by **learning from a teacher** (same shape
  as glyph-learning in magic).

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
- **B — group/cultural tables (authored once, world-wide) — IN NOW.** Cultural facts traits can't
  derive (a timid, kind dwarf still inherits "distrust orcs"). Ship `content/race_relations.json`
  (`race × race → sentiment`) now and **seed non-human NPCs into the pool** so race-hatred is live
  from the start; every member reads the table, their own traits modulate it. Faction/class tables
  follow. Shared by thousands of NPCs, not per-NPC prose.
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
- **Current activity is an importance-weighted commitment — derived, not authored.** Being on-shift
  at your venue (role at workplace during `open_hours`) is an implicit "working" commitment whose
  importance comes from the `purpose` need + being on shift — no per-role task lists. Reuses the
  underused `engagement`/`plan.importance` ("resistance to interruption"). Greeting a stranger must
  **beat** it, so the bored regular greets you while the harried keeper nods and keeps pouring.
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
- **Add:** `disgust` emotion; a full visible **surface** on every `Body` incl. the player; identity
  appraisal on perceive → `Impression`; `content/race_relations.json` + seeded non-human NPCs; the
  proxemics utility term; earned-salience + derived-activity attention; persistent **hp/injury**, a
  numeric **age**, and a **skills** system; the player's surface (no game-side traits).
- **Remove:** the separate dialogue interface (all talking is freeform).

## Open decisions (the four big calls are resolved & folded in above)

- **Skills:** the exact skill list, the practice-vs-teaching curve (how fast doing/learning raises a
  skill), and which existing rolls become skill-modified.
- **Race:** which non-human races to seed, at what pool fraction, and the `race_relations.json`
  sentiment values.
- **Injury:** the condition set (bleeding/broken/fever/poison/…), each one's ability/action modifier
  + heal rate, and which are surface vs. hidden.
- **Player surface:** how the player's dress/hygiene/race/age start (default stranger vs. a light
  pick) and how they change in play (dirt, wounds, disguise).

Related: [mind.md](mind.md) (utility core) · [entities.md](entities.md) · [items.md](items.md)
(surface/hidden precedent) · [locations.md](locations.md) (zones/proxemics) · [loop.md](loop.md)
(the tick, freeform `/act`).
