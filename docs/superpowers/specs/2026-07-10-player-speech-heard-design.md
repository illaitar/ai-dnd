# The room hears the player — design spec (Workstream C, increment 1)

**Status:** approved design, ready for implementation plan. Date: 2026-07-10.
**Builds:** `sound-attention.md` Pillar 2 (attention economy — reactions as candidate actions), the
first real slice of it. **Relates to:** [mind.md](../../mind.md) (decision prompt/impulse),
`engine/convo.py`, `engine/sound/audibility.py`.

## Problem

When the player speaks to the room (untargeted freeform — "спрашиваю, что за слухи", "нет ли работы?"),
**no NPC reacts**. Verified in playtest: 8 ticks, the player's two spoken questions drew zero answers.

## Root cause (why "the room reacts" doesn't already work)

An NPC is pulled to react by exactly two mechanisms, and neither covers player speech:
1. **Answer-debt** (`convo.py`) — the strongest impulse (4.0), but only created by the *targeted*
   dialogue path (`/api/play/talk`+`/say`, which call `conv_note_say(PLAYER, npc, …)`). Untargeted
   speech never creates it.
2. **`lv["salient"]`** — a single crude scene-event flag, but it is only ever *set by NPC actions*
   (an NPC attacking, an NPC recoiling from a murder-deal) — never by the player — and it bluntly
   boosts *all* present NPCs (a mob), not per-listener by relevance.

And the player's untargeted utterance is **never emitted as an event at all**: the freeform fallback
([freeform.py:370-387](../../src/aidnd/server/play/handlers/freeform.py)) only asks the DM narrator to
describe the scene — it never sets `pc_spoke`, never records the line, never injects it into any NPC's
prompt. So NPCs literally don't hear you. The attention economy that *would* score the utterance
per-listener and make "react" a candidate action is designed but unbuilt. This spec builds its first
slice for player speech.

## Design decision (locked with the user)

**Fully emergent.** Every NPC who *hears* the player weighs it by their own state — a busy gambler or
someone who dislikes the player may ignore it entirely. No guaranteed acknowledgment, no mob. Who
reacts (one, several, none) emerges from proximity (audibility) + each NPC's own utility. No caps.

## Architecture — three units

### C1 — emit the utterance as a scene event (freeform)
On the untargeted-speech fallback in `_attempt` ([freeform.py:370-387]), before the world tick runs
(the tick runs after `_run_plan` in `act()`), record the player's line on the live scene:
`lv["pc_said"] = text` and `lv["pc_spoke"] = True`. Keep the existing DM-narrated player-result line
(it narrates *your* act); C2/C3 add the NPCs' side. Guard: only set `pc_said` when there's a text
utterance (the fallback path with `text`), so pure mechanical actions don't emit a phantom line.

### C2 — only NPCs who HEAR it react, proximity-weighted (live tick)
In `_live_tick`, when `lv.get("pc_said")` is set, for each present NPC compute audibility from the
player's zone to the NPC's zone — reuse `audibility(player_zone, npc_zone, PB["sound_voice"])`
(the same call `_overheard` uses). If audible (tier not None):
- add a **per-listener impulse** scaled by tier — `PB["pc_said_impulse"]` × tier-weight (L1 strongest,
  L3 faint) — in the impulse table ([world.py:679-702]) as reason "услышал чужака". This lifts a near
  hearer into the "may think" set (LOD), leaves a far one background, and stays **below** answer-debt
  (4.0) / event (3.5) so a busy NPC's own duty still wins → emergent, not forced.
- pass the utterance into that NPC's `ctx` (a `pc_said` entry) for the prompt (C3).
Clear `lv["pc_said"]` at the end of the tick (one-shot — the utterance is "in the air" for one tick).

### C3 — render the utterance in the decision prompt (mind)
In `build_prompt`, when `ctx["pc_said"]` is present for this NPC, render a neutral, non-coercive line:
`"  ⚑ Чужак рядом только что сказал вслух: «{pc_said}» — ответь, если тебе есть что сказать, или "
"занимайся своим."`. The NPC's own utility (via `decide_hybrid`) decides whether to reply — no forced
answer. (Mind stays pure — it only reads `ctx`.)

## Data flow

```
player untargeted speech → _attempt fallback → lv["pc_said"]=text, lv["pc_spoke"]=True   (C1)
_world_tick → _live_tick:
  for each present NPC that can HEAR (audibility): +impulse "услышал чужака" (tier-scaled),
    ctx["pc_said"][pid]=text                                                              (C2)
  clear lv["pc_said"]
build_prompt: render «Чужак сказал: …» for NPCs who heard → they may reply (emergent)     (C3)
```

## Testing

- **Pure/unit:** audibility gating — a near NPC "hears" (tier not None → gets impulse + ctx entry), a
  far/no-shared-frame NPC does not; the impulse is tier-scaled and below the event/debt tiers;
  `build_prompt` renders the line when `ctx["pc_said"]` present, omits it otherwise; `pc_said` is
  cleared after the tick (one-shot).
- **Live playtest (before/after):** re-run the tavern/den driver; the player speaks to the room —
  assert ≥1 nearby NPC now *considers/answers* (some tick engages), and it stays emergent (not every
  hearer replies; busy ones keep to their business).

## Risks

- **Tuning:** `pc_said_impulse` and the tier weights need a live eyeball — too high = everyone drops
  their business to answer (a new mob); too low = still a ghost. Start moderate (L1 ≈ 2.2), tune.
- **Player-line literalness:** the freeform text is an action *description* ("спрашиваю про слухи"), not
  literal dialogue; framed as "сказал вслух: «…»" the LLM reads the gist fine, but watch the phrasing in
  playtest — a follow-up could pass the arbiter's cleaned utterance instead of raw input.
- **Interaction with LOD selection:** a near hearer's impulse (≈2.2) exceeds the `live_must_impulse`
  (1.5) gate, so they *are* selected to think — intended (they can react) without forcing the reply.

## Increment (green → commit → deploy)

1. **Player speech heard + emergent reactions** (C1–C3), unit-tested + playtested.
2. *(Follow-up, same workstream)* disruptive acts (shout/throw/drawn steel by the player) set a
   stronger `lv["salient"]` so the room flinches — reuses this event channel; also fixes the earlier
   "no reaction to my drawn weapon."
