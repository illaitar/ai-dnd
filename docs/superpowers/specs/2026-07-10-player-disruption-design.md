# The room flinches at a disruption — design spec (Workstream C, increment 2)

**Status:** approved design, ready for implementation plan. Date: 2026-07-10.
**Follows:** [2026-07-10-player-speech-heard-design.md](2026-07-10-player-speech-heard-design.md) (inc 1,
shipped). **Touches:** `handlers/freeform.py`, `engine/narrator/voice.py` (`_DM_SYS`).

## Problem

Two gaps from the playtests:
1. **A disruptive player act draws no reaction.** Drawing a weapon, shouting "Тихо все!", throwing a
   mug — the room ignores it (verified earlier: the mug-throw "приклеена жиром" was pure LLM gap-fill,
   and nobody flinched at a shout).
2. **The DM narration contradicts the reactions.** The freeform fallback narrates a pessimistic
   *"твой голос тонет, никто не оборачивается"* — immediately before NPCs actually answer (inc 1).

## Root cause (grounded)

`lv["salient"]` is the "whole room reacts" event: when set, `_live_tick` boosts every present NPC to
impulse 3.5 ("событие") and injects `ctx["event"]` → `build_prompt` renders *"⚡ ТОЛЬКО ЧТО: {ev} —
отреагируй по своему характеру (страх/любопытство/вмешаться/не моё дело)."* But it is only ever set by
**NPC** actions — an NPC attacking (`world.py:981-982`) or recoiling from a murder-deal
(`deals.py:106-110`) — **never by the player**. And the freeform fallback (`freeform.py:370-387`, where
inc 1 sets `pc_said`) narrates the scene via the DM without emitting any player event, and the `_DM_SYS`
prompt lets it invent a non-reaction.

## Design decision

- **A player disruption uses the `salient` channel** (everyone *notices*; each reacts in character) —
  the right model for a loud/visible act, distinct from inc 1's audibility-gated emergent speech.
- **Detection is a keyword classifier** (like inc-1's work-interest regex — deterministic, no extra LLM
  call), scoped tightly to clear disruptions (shout / throw / break / brandish / threaten) so ordinary
  speech that merely mentions a weapon ("спрашиваю про меч") does not trigger.
- **No mechanical gates:** the salient only *raises* the room's pull to react (existing behavior); each
  NPC's reaction is still their own utility choice ("не моё дело" is a valid outcome).

## Architecture — two units

### D1 — disruptive act → `lv["salient"]`
In `freeform.py` `_attempt`, in the same fallback `if text:` block that sets `pc_said` (inc 1): if
`_DISRUPTIVE_RE.search(text)`, also set `lv["salient"]` to an observable event line so the room reacts
this tick. Keep `pc_said` too (a shout is *both* words heard and a disturbance — salient's 3.5 dominates
inc-1's 2.8, so the whole room reacts and also has the words in-prompt). Also: the player **attack**
path (`freeform.py:348-368`) sets `lv["salient"] = "чужак выхватил оружие!"` before opening combat, so
bystanders register it.
- `_DISRUPTIVE_RE` (case-insensitive), tightly scoped to action verbs:
  `кричу|ору\b|заор|во весь голос|громко (говорю|спрашиваю|зову)|рычу|выхватыва|обнажа|`
  `хвата\w+ за (нож|меч|оруж|клинок)|достаю (нож|меч|клинок|оруж)|швыр|броса\w+ (кружк|в стену|об)|`
  `опрокид|бью кулак|стуч\w+ по столу|разбива|угрожа|за грудки`.
- Salient text is observable third-person: `f"чужак: {text[:70]}"` — the LLM reads the gist (a follow-up
  could pass a cleaner derived phrase).

### D2 — DM narrates the act as *happening*, and never blocks it
The old `_DM_SYS` (`voice.py`) told the DM *"мир от него НЕ изменится … НИКОГДА не подтверждай
свершение заявленного (особенно разрушительного): покажи, почему оно не происходит"* — **this was the
real cause of "приклеена жиром" and the ignored shout: the DM was instructed to negate destructive
player acts.** Per the player-agency directive, that negation is **removed entirely** — a destructive
act is not gated by the narrator. `_DM_SYS` is rewritten to:
- **narrate the player's act as SWERSHING** ("Ты выхватываешь нож… это ПРОИСХОДИТ; свободу действий не
  ограничивай, не выдумывай, почему оно «не выходит»");
- **not describe others' reactions** (those ride in the tick's digest — no more "никто не
  оборачивается" contradicting the replies);
- **not resolve others' fate** (whether a blow lands, whether someone dies) — only what the player
  does; contested outcomes stay with the world/combat, not the freeform narrator.

`_DM_SYS` is used only by the freeform fallback (`freeform.py`), not shared with NPC dialogue — verified,
so the rewrite is safe.

## Testing

- **Pure/unit:** `_DISRUPTIVE_RE` matches shout/throw/brandish/threaten lines and does NOT match ordinary
  speech ("спрашиваю про слухи", "спрашиваю, где купить меч", "как дела"). Table-driven, like inc 1's
  work-interest test.
- **Live playtest (before/after):** in a populated room — the player shouts / draws / throws → the room
  *reacts* this tick (glances, flinches, someone squares up or tells them off), varied by character, not
  a uniform script; ordinary speech still uses inc-1's emergent path (no room-wide flinch); the DM line
  no longer predicts a non-reaction.

## Risks

- **Regex precision:** false-triggers (a disruption fires on a benign line) or misses. Mitigate: tight
  action-verb patterns + the playtest; numbers/patterns easy to adjust. A future upgrade could classify
  via the arbiter instead of keywords.
- **`_DM_SYS` sharing:** if the same system prompt drives NPC dialogue narration, adding the directive
  there could suppress legitimate reaction-narration — verify and, if shared, scope the directive to the
  freeform-fallback user message.
- **Double signal:** setting both `salient` and `pc_said` for a shout is intentional (disturbance +
  words); salient's higher impulse dominates, no conflict.

## Increment (green → commit → deploy)

1. **Disruptive act → salient + DM narration fix** (D1 + D2), unit-tested + playtested.
