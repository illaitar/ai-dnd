# «МОЗГ» — affective/social loop

Closes the affective-social contour on top of the utility core ([mind.md](mind.md)): every act now
*moves affect through the witness's own worldview*, affect *fades toward a floor* instead of only
growing, and the character that emerges *speaks* and *decides* differently — over/under-confidence,
distraction, a newcomer greeted. All arithmetic, zero new LLM calls. `mind.md` is the decision core
(goals × utility over 7 primitives); this doc is the affective loop layered over it — one entity, two
docs by concern.

Ships in 6 increments, all on prod. Design: `docs/superpowers/specs/2026-07-15-brain-design.md`.

## Two-speed lazy decay (Inc1) — `mind/decay.py`

Affect used to only grow: `rel["affinity"] = min(old, -0.5)`-style writes never relaxed, and the one
existing decay (`tick._decay_emotion`) only ran per-tick for NPCs *currently in the scene* — anyone
absent kept a stale grudge forever, relationships had no decay at all.

`decay_lazy(state, now_gt)` now runs once, keyed on elapsed **game-time** (`gt`), not a 1354-wide
sweep:

- **Emotions — FAST**, toward `emotion_baseline` (half-life `decay_emo_days` = 0.5 days). A passing
  fright is gone in a few days regardless of what caused it.
- **Anchored relationships — SLOW**, toward a faint prior `sign × rel_faint_prior` (0.10), half-life
  `decay_rel_anchored_days` (14 days) **× (1 + vengefulness)** — a vindictive NPC (vengefulness 0.8)
  holds a grudge ~25 days; a forgiving one (0.1) lets go in ~15. `anchored` is a new key on the rel
  dict (`{affinity, trust, fear, anchored}`), `True` only for a **real interaction** (attack, deal,
  gift acceptance, `_hydrate_rels`-authored kin/rival ties) — a mere bystander impression is `False`.
- **Unanchored relationships — LOOSE**, toward 0, half-life `decay_rel_loose_days` (2 days). A
  bystander's fear of someone they merely saw act fades fast.

Applied **entrant-gated**: `decay_scene_entrants` runs `decay_lazy` exactly once per NPC, the tick it
*enters* the scene (a mind present now but absent from the prior tick's settled set) — it catches up
the whole out-of-scene gap in one pass, then keeps relaxing emotions per-tick (existing machinery)
while it stays in scene. An NPC already in scene last tick is skipped (no double-decay).

`last_decay_gt` is a persisted int on `NpcState`/`_npc_save` — the clock survives `git reset --hard`
+ restart. A falsy (`0`) clock means "never stamped" (new world or a pre-brain NPC) — decay is
skipped once and the clock stamped to now, so the whole world's age is never flattened into one
gap. A rewound clock (`now_gt < last_decay_gt`, e.g. a replayed/reset `gt`) computes `dt = 0` — a
no-op, never an amplification.

`feel`/`need` LLM tools used to write **absolute** values (`state.emotion[e] = float(v)`) — a model
reply could erase a justified grudge or hunger in one call. Both are now clamped to a **nudge**:
`new = clamp(cur + clamp(target - cur, -feel_nudge_cap, +feel_nudge_cap))` (`feel_nudge_cap` = 0.25)
— the model can move a channel, not zero it.

## The Event bus (Inc2) — `mind/event.py` + `mind/project.py`

Before: a witnessed act moved affect only through `appraise_present`'s co-presence *impression*
(reading a body's surface each tick — unchanged, still runs, see [mind.md](mind.md) "Perception &
Appraisal") or a hand-written enrage-the-victim/memory-only path (`_witness_crime`). Bystanders got
zero fear/disgust/distress, and the one act that *did* move affect landed identically on everyone —
the witness's `worldview` had no consumer.

`Event` (`mind/event.py`) is an **objective, not-pre-judged** signature built at the act site:
`sig(actor, target, intensity, physical_threat, target_harm, tags[], zone)`. `project_event`
(`mind/project.py`) lands one signature on one witness through **two channels**, purely data-driven
(`TAG_AXIS`/`TAG_CHANNEL` tables, no code branches):

- **VISCERAL** — danger, independent of judgement: `harm = physical_threat × (ev_harm_base +
  ev_harm_familiar × fear_prior_of_actor) × perc × (1 − ev_viol_damp × max(0, morals.violence))` —
  someone who personally approves of violence flinches less at seeing it. `care = affinity_target +
  ev_empathy_care × empathy` feeds distress even for a stranger.
- **MORAL LENS** — the dominant tag (first tag present in `TAG_AXIS`, severity-ordered) is scored
  against the witness's `worldview.morals[axis]`: negative stance → `outrage` (× `ev_taboo_mult` 1.6
  if the tag is also a personal `taboo`) → disgust; positive stance → `approval` (× `ev_approval_k`)
  → grim-satisfaction joy. `goal_impact = -target_harm × care + approval` feeds joy/distress in the
  existing `tick.appraise()`; `desert = stance` gates anger (a deserved death draws no anger).

`perc` (perception weight, 1.0 same-zone / `ev_perc_l2`/`ev_perc_l3` farther / 0 unperceived) reuses
the audibility/sight tiers — a witness who didn't hear or see the act gets **no delta at all**, same
gate memory already respects. Un-enriched witness (`worldview = {}`) → `morals.get(axis, 0) = 0` →
moral lens is a no-op, but the **visceral** channel still fires — never crashes, degrades to neutral.

`project_and_apply` fans one Event out to every witness: for each, `project_event` → `tick.appraise`
(applies each channel's `emotion_gain`) → bystander rel deltas onto the Inc1 floor (`actor_fear`,
loose unless the witness *is* the target, in which case the write is `anchored=True` — a real
victim's grudge persists, a bystander's fright fades fast; `target_warmth` for a non-harmful act like
a gift, gratitude from the beneficiary toward the giver, always anchored).

**Wired at 3 real sites** (verified at HEAD, not aspirational):
- `_crime_affect` (`server/play/engine/core.py`) — every player crime against an NPC (assault,
  robbery, pickpocket, murder solicitation) fans out to the co-present crowd. `_crime_signature`
  keyword-derives `(tags, intensity, physical_threat, target_harm)` from the crime's own verb phrase
  — no LLM, no per-crime-type branching beyond the lookup table.
- `_duel_wrapup` (`server/play/mechanics/combat.py`) — a player kill in combat fans the killing out
  to everyone present (`убийство/насилие/смерть`, `target_harm 1.0`).
- `apply_actions` (`mind/llm_agent.py`) — an NPC's own resolved `attack`/`take`/`give` tool call
  builds and fans out the matching Event (kill/harm, theft, gift) to co-present witnesses.

`appraise_present` (existing, `mind/appraisal.py`) is **not** replaced — it keeps running every tick
as the continuous surface-read channel (impression from traits × visible surface × culture ×
personal history). The Event bus is the complementary **episodic** channel: it fires only when
someone *does* something, and it is the one that reads `worldview`. One killing in a tavern: a
`Багровый` cultist (`morals.death +0.84`) feels barely-stirred grim satisfaction; a lavочник
(`morals.death -0.23`) recoils in fear and disgust; a priest with `убийство` in his `taboos` recoils
hardest and is angry at the killer — one signature row, three lands, purely from the `worldview`
slice (spec §5 Example A has the full traced arithmetic).

## Familiarity accrual + emergent newcomer greet (Inc3) — `server/play/engine/world.py`

`_accrue_familiarity` counts co-presence ticks per stranger (`st.familiarity[other_id]`, unbounded,
no cap — consistent with memory-pruning being out of scope); at `familiarity_k` (4) ticks it seeds a
**faint unanchored** tie (`familiarity_affinity` = 0.05 warmth/trust, `anchored: False`) so a
familiar face reads as a mild acquaintance, not a stranger, without a scripted "you've met N times"
rule.

`_pick_newcomer` finds the first co-present body an NPC has *never* met (no relationship row) and
that nobody has greeted yet. `_greet_impulse(sociability) = greet_sociability_base × max(0,
sociability - 0.5)` — sociability ≤ 0.5 raises **zero** impulse (a wary room greets nobody); above
that it's a real pull added to `_MUST_WHY` under the reason `"новичок"`, competing with other reasons
an NPC gets picked into this tick's LLM actor set (event / owed answer / heard a stranger / emotion
spike). **No LOD guarantee** — the greet impulse only raises the odds a sociable/host NPC is drawn
into the actor set that tick; if rotation doesn't pick one, nobody greets, emergent frontier wariness,
not a scripted "always greeted" hook. The ≤1-greeter lock (`greeted` set) fires only on the *actual*
greeting (`_greeted_toward`, an NPC that really said-to/stepped toward the newcomer) — a drawn NPC
that instead ate/worked/waited leaves the slot open for the next sociable NPC, so one missed pick
doesn't permanently burn the scene's one greeting. Same rule applies NPC↔NPC, not just toward the
player.

## Voice speaks character (Inc4) — `narrator/voice.py::_character_bits`

Before, `_voice` folded in only `persona.{origin,voice,quirk,wants,stance,secret}` — flavor prose,
the same regardless of the NPC's actual trait vector, worldview, or current feeling. `_character_bits`
now appends a **compact, salient selection** (not a data dump) to the one existing voice call:

- **НАТУРА** — the 2-3 traits farthest from the 0.5 midpoint (skipped if none clear ≥0.08), e.g.
  "злонравие 0.47, храбрость 0.78, гордость 0.45 — говори дерзко, без страха."
- **ВЕРА и НРАВ** — faith deity (if any, and not `"нет"`), the moral stances with `|v| ≥ 0.25`
  ("смерть тебе БУДНИЧНА" / "тебе претит"), taboos (up to 3, "для тебя мерзость: …"), and a notable
  `standing` (non-common rank, or `notoriety ≥ 0.5` → "о тебе идёт дурная слава").
- **СЕЙЧАС ТЫ ЧУВСТВУЕШЬ** — the single hottest live emotion channel, named in Russian, if ≥ 0.2 —
  this is where Inc2's Event-driven affect actually surfaces in speech: an NPC who just watched a
  killing sounds like it.
- **Boast beat** — when `self_regard(traits) > 0.8` (same formula as Inc5, computed inline here to
  avoid an import cycle with `value.py`), an extra line: "Ты держишься с бахвальством, говоришь о
  себе БОЛЬШЕ, чем заслужил…" — a braggart talks bigger than warranted (§10, resolved: yes, a
  distinct beat, not folded silently into the nature line).

The top drive (`persona.wants`) is deliberately **not** re-emitted here — it already reaches the
prompt via the persona block, so `_character_bits` would only duplicate it. Un-enriched NPC (neutral
traits, empty worldview/standing) degrades gracefully: every slice is independently skippable, so a
legacy row just contributes fewer bits, never breaks the call. Still one `narrator` voice call —
zero new LLM cost.

## Self-regard biases the perceived fight (Inc5) — `mind/value.py`

`self_regard(state) = clamp01(sr_pride·pride + sr_brave·bravery + sr_amb·ambition)` — derived on
demand from traits, no stored field, no regen. 0.5 = calibrated; above is a braggart, below is timid.

`perceived_pwin(att, deff, state)` is the **decision's estimate** of a fight, distinct from the
combat-real `pwin`: `bias = 1 + sr_span·(self_regard - 0.5)` (sr_span 1.5) inflates the NPC's own
power and discounts the foe's (own × bias, opp × (2 - bias)) before computing the win ratio. At
self_regard 0.5, bias is 1.0 and `perceived_pwin == pwin`.

`clean_acquire`/`_u_acquire`/`_u_harm` (the theft/assault/vengeance decision paths) all read
`perceived_pwin` for their attack/subdue terms — so an overconfident NPC (self_regard say 0.66) can
compute a positive `_u_harm` for a fight where the *true* `pwin` is only 0.40, pick it, and lose it
~60% of the time (spec §5 Example C, traced with real pool data: `Ход Овражный pool:0528`). A meek
NPC (self_regard 0.3) inverts it — perceives a losing fight where it would actually win, over-flees.

**Real combat resolution is untouched** — `combat.py` and `hostility()`/threat-danger reads always
call the plain `pwin` (true power ratio); only the *decision estimate* that leads an NPC to start or
avoid a fight is biased. This is the "no self-esteem" gap from the audit, closed: NPCs now over- or
under-estimate themselves, and pay for it in real combat outcomes exactly as a person would.

## Attention Pillar 2 (Inc6) — `server/play/engine/world.py::_body_attention`

`Body.attention` used to be static, read straight from `perception.vigilance` — never dropping when
an NPC was asleep, absorbed, or otherwise not watching, so the theft primitive's `take_distracted`
branch (`value.py` — `ps = take_distracted (0.78) if tb.attention < 0.4 else take_alert (0.15)`) was
dead code: nothing ever pushed attention below the 0.4 threshold.

`_activity_of(state, gt)` derives a coarse activity label from **real runtime signals** already on
`NpcState` — no new field: `mode == "routine"` at night → `"asleep"`; `mode == "threat"` or
`fear ≥ 0.6` or role `"стражник"` → `"alert"`; `mode == "converse"` or `on_shift > 0` → `"absorbed"`;
otherwise ordinary `"alert"` watchfulness. `_body_attention = vigilance × att_{activity}` (multipliers
`att_asleep` 0.2, `att_drunk` 0.4, `att_absorbed` 0.6, `att_alert` 1.3), clamped `[0.05, 1.0]`, re-read
per scene build so it stays live. A sleeping or absorbed target now dips under 0.4 → `take_distracted`
fires; an alert guard caps at 1.0 and stays a hard mark. `att_drunk` has no runtime signal wired yet
(no drunkenness flag on `NpcState`) — the multiplier exists in `PB`/`BAL` and the `_activity=` unit
seam, but is currently unreachable from live play (see "next").

## Depends on the enriched entity

Every worldview/trait read above (`morals`, `taboos`, `faith`, `vengefulness`, `empathy`, `pride`,
`bravery`, `ambition`, `sociability`) is fuel seeded on all ~1354 pool NPCs by the entity enrichment
pass — see [worldgen.md](worldgen.md) "Lazy enrichment in-game" / `worldgen/enrich_pool.py`. Brain
was inert without it: an un-enriched NPC (`worldview = {}`, neutral traits) degrades every channel
above to a visceral-only, neutral-boast-free, un-greeted default — never crashes, just flat.

## Next

- **Faction hostility activation** — `ENEMY_FACTIONS` widening / guild wars. The Event bus's tags
  could drive it, but activation is out of scope here (separate program).
- **Memory pruning** — `familiarity` and `memory` both grow unbounded; no eviction yet (audit item
  3, deliberately deferred, separate root).
- **Drunk attention signal** — `att_drunk` (0.4) is a live `PB`/`BAL` knob with no NPC-side
  drunkenness flag to read yet; wire a tipsy need/flag and `_activity_of` picks it up for free.
- **NPC↔NPC familiarity** — the accrual/greet code already runs identically for two NPCs meeting
  (not player-gated), so this is mostly superseded by Inc3 already shipping general-purpose; only a
  live-playtest check remains to confirm it fires between NPCs, not just toward the player.
- **Phrase low traits via antonym** — `_character_bits`' НАТУРА line only phrases the *high* end of a
  salient trait explicitly (e.g. "храбрость 0.78"); a low value (e.g. `bravery 0.1`) still shows the
  raw number rather than an antonym cue ("трусоват, не лезь в драку") — a phrasing polish, not a
  behavior gap.

Related: [mind.md](mind.md) (utility core, decision pipeline) · [npc-brain.md](npc-brain.md) (entity
shape: surface/hidden, appraisal tiers, attention economy design) · [worldgen.md](worldgen.md)
(enrichment pass that seeds worldview/traits) · [sound-attention.md](sound-attention.md) (audibility
tiers the Event bus's `perc` reuses).
