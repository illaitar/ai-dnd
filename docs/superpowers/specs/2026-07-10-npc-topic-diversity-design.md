# NPC topic diversity & rumor saturation — design spec (Workstream B)

**Status:** approved design, ready for implementation plan. Date: 2026-07-10.
**Source:** live playtest ("клад" monoculture) + root-cause trace, this session.
**Relates to:** [mind.md](../../mind.md) (decision prompt), [locations.md](../../locations.md) (scene/ctx),
[npc-brain.md](../../npc-brain.md) (conversation). Follows Workstream A (work & idle).

## Problem (from the transcripts)

The entire tavern fixates on ONE rumor ("клад"/treasure) tick after tick — every NPC talks about the
same subject endlessly, and it follows the crowd into other buildings. A living room should carry
several parallel conversations that turn over.

## Root cause (grounded in code)

1. **The same rumor is pumped into the same NPC all day.** `world.py:667-669`:
   `rumor_of = {pid: rums[hash((pid, _gt() // 1440)) % len(rums)] for pid in order}` — `_gt()//1440` is
   the *day number*, so within a day each NPC is handed one fixed rumor from the location's ≤3-item
   list (`world.py:520`) every single tick. The prompt line (`llm_agent.py:158-160`) actively invites
   sharing it, with no counter-signal.
2. **No subject ever decays or saturates.** The only topic state is the token-signature anti-echo
   (`world.py`, ~4-tick window) which fails the moment wording changes ("клад разбойников" vs "клад
   сборщика" share no stems). Nothing tracks that the *room has chewed a subject*.
3. **Each NPC's own varied topics are unused live.** `_topics_for(p)` (`voice.py:158-164`) already
   reads `persona.rumors` + `persona.wants`, but is only wired to the dialogue narrator
   (`dialogue.py`), never to the live decision prompt. So live chatter draws only from the shared 3
   location rumors, not each person's own material.

## Design decisions (locked with the user)

- **Scope: B1–B3 this pass; B4 (conversation subject+budget in `convo.py`) deferred** to a follow-up.
- **Moderate saturation:** a rumor stays lively for a few exchanges, then fades from the offered
  topics over the next several ticks. Numbers live in `PB`, tuned in playtest.
- **No mechanical gates:** every change *models a social reality* (a room tires of a subject; people
  have their own things to talk about), never caps who may speak.

## Architecture — three units

### B1 — De-correlate & rotate the location rumor (world)
Change the `rumor_of` construction (`world.py:667-669`) so a rumor is **not** a day-long constant:
rotate on a shorter window `_gt() // PB["rumor_rot_min"]` (plus a salt) so what an NPC raises shifts
over the evening and differs across NPCs. Still sourced from the location `rums`. Extract a pure
helper `_pick_rumor(pool, seed_key, heat, hot) -> str | None` (used by B2) that skips saturated
rumors and returns a rotated pick.

### B2 — Rumor heat / saturation (world) — the "stop eating the room" lever
Add per-scene heat: `lv["rumor_heat"]: dict[str, float]`. Each tick, in the ctx assembly
(`world.py:665-669`): **(a)** decay every heat by `PB["rumor_cool"]`; **(b)** when building `rumor_of`
and filtering `news`, exclude any subject whose heat ≥ `PB["rumor_hot"]` (fall through to a cooler
rumor / persona topic); **(c)** after assigning, add `PB["rumor_warm"]` to each offered subject's heat.
A subject offered repeatedly heats past `rumor_hot`, drops out, and cools back over several ticks.
Moderate defaults (tunable): `rumor_warm ≈ 0.34`, `rumor_hot ≈ 1.0` (≈3 offers → hot), `rumor_cool ≈
0.15` (cools over ~7 ticks), `rumor_rot_min ≈ 90`.

### B3 — Per-persona topics line (world → mind prompt)
Surface each NPC's own material. In `world.py`, build `ctx["topics_of"] = {pid: _topics_for(people[pid])
for pid in order}` (reusing the existing `voice._topics_for` — server-side, so the mind stays pure).
In `llm_agent.py` `build_prompt`, render a new line from `ctx["topics_of"].get(cfg.id)`:
`"  ТВОИ ТЕМЫ (о чём тебе есть что сказать): «X»; «Y» — заведи, к слову."` — giving each NPC a menu of
their own rumors/wants beyond the shared town rumor. Heat-filter these too (B2) so a person's own
subject also fades once chewed.

## Data flow

```
ctx assembly (world.py:665-686):
  decay lv["rumor_heat"]                                      (B2)
  news  = town_talk + guild/board, minus hot subjects        (B2)
  rumor_of[pid] = _pick_rumor(rums, (pid, gt//rot), heat, hot) (B1+B2)
  topics_of[pid] = _topics_for(people[pid]), minus hot        (B3+B2)
  heat up every offered subject                               (B2)
build_prompt (llm_agent.py:155-161):
  render news line · «здешний слух» (rumor_of) · NEW «твои темы» (topics_of)
```

## Testing

- **Pure unit tests:** `_pick_rumor` rotates across windows and skips hot subjects; heat decays and a
  subject offered ≥N times crosses `rumor_hot` then cools below it; `topics_of` built from a persona
  with rumors/wants; `build_prompt` renders the «твои темы» line when `ctx["topics_of"]` is present and
  omits it when empty.
- **Emergence guard:** `tests/mind` + `tests/play` stay green.
- **Live playtest (before/after):** re-run the tavern driver; assert the room carries **≥2 distinct
  subjects** at once and the dominant rumor **fades within a few ticks** instead of saturating; NPCs
  raise their own persona topics (work, wants, a grudge), not only "клад".

## Risks

- **Prompt bloat / cost:** one added line per NPC prompt — negligible.
- **Heat model tuning:** the warm/hot/cool numbers need live tuning (in `PB`).
- **`_topics_for` fallback** returns generic filler ("что нового?") for personas with no rumors/wants —
  acceptable, keeps a topic present; ensure the line is omitted rather than showing filler if that
  reads flat (tune in playtest).
- **Interaction with `_gossip`** (NPC→NPC memory copy) is left for B4 — B2 saturates the *offered*
  topics, which is the dominant driver; if gossip still resurfaces a chewed subject in playtest, fold a
  heat check into `_gossip` in the B4 follow-up.

## Increments (each green → commit → deploy)

1. **B1 + B2 — rumor rotation + saturation** (world.py rumor_of/news + `lv["rumor_heat"]` + PB knobs).
   *First visible win: the shared rumor stops dominating.*
2. **B3 — per-persona topics line** (`ctx["topics_of"]` + `build_prompt` render).
3. **Playtest + tune + deploy.**
