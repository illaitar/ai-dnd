# Conversation subject exhaustion (talk-budget) — design spec (Workstream B4)

**Status:** approved design, ready for implementation plan. Date: 2026-07-10.
**Follows:** [2026-07-10-npc-topic-diversity-design.md](2026-07-10-npc-topic-diversity-design.md) (B1–B3,
shipped). **Touches:** `src/aidnd/server/play/engine/convo.py` (the conversation object).

## Problem

B1–B3 diversified the *room* (rumor saturation + per-persona topics) — the tavern no longer chants one
rumor. But a **single conversation thread** can still drag on one subject too long: the playtest's
"giant cellar rats" yarn ran ~5 ticks before a new subject competed. A conversation has no notion that
a subject is *spent*; it only ends on `QUIET_DIE` (3 ticks of silence) or when members leave the zone.

## Root cause (code)

`convo.py` models a conversation as `{id, zone, members, log, debt, quiet}` — no `subject`, no budget.
As long as anyone keeps talking, `quiet` resets (`conv_note_say`) and the thread lives indefinitely, and
the answer-debt (`conv_debt_to`, priority 4.0 in the conductor) keeps *pinning* the same pair to reply.

## Design — a talk-budget that exhausts a thread

Model "people run out of things to say on a topic and move on." No caps on who may speak — just a
natural wind-down. Add a per-conversation **spend counter**; three effects as it approaches the budget:

1. **Count spend** — `conv_note_say` increments `c["spent"]` per line.
2. **Nudge (soft, LLM decides)** — when `spent ≥ CONVO_BUDGET − CONVO_NUDGE`, `conv_block` appends:
   *«⚑ разговор об этом иссякает — смени тему, пошути или отойди (не тяни то же самое)»*. The model winds
   the thread down or pivots to a fresh subject.
3. **Release the pin** — when `spent ≥ CONVO_BUDGET`, `conv_debt_to` returns `None` so an exhausted
   thread no longer forces the addressee to answer as the conductor's top impulse. Participants are free
   to drift to a new partner/subject; the thread then dissolves naturally via the existing `QUIET_DIE`.

**Constants (module-level in `convo.py`, matching the existing `QUIET_DIE`/`LOG_KEEP`/`DEBT_STALE`
pattern — this pure module owns its own tuning, it does not read the server `PB` table):**
`CONVO_BUDGET = 6` (moderate — a good yarn gets told, then turns over), `CONVO_NUDGE = 2` (nudge for the
last ~2 lines before the budget).

## What we keep

- `QUIET_DIE` still ends a silent thread; B4 only *accelerates turnover of a lively one*.
- The anti-echo `_say_ok` / `topics` guard and B1–B3 saturation are untouched and complementary.
- `subject` string tracking is intentionally **not** added — a line-count budget is enough for the
  turnover goal and avoids fuzzy subject extraction (YAGNI). ("Subject" in the spec name is the *thread*.)

## Testing (pure, no LLM)

- `conv_note_say` increments `c["spent"]` per line; starts at 0.
- `conv_debt_to` returns the debt while `spent < CONVO_BUDGET`, and `None` once `spent ≥ CONVO_BUDGET`
  (even with a fresh, non-stale debt) — the release.
- `conv_block` appends the «иссякает» nudge when `spent ≥ CONVO_BUDGET − CONVO_NUDGE`, and does **not**
  before that.
- Merged conversations (two circles joined by a line) carry a sensible `spent` (max of the two, so a
  merge doesn't reset exhaustion).
- Regression: `tests/play/test_convo.py` stays green.

## Risks

- **Tuning:** `CONVO_BUDGET`/`CONVO_NUDGE` need a live-LLM eyeball (playtest) — do threads now turn over
  without feeling clipped mid-story? Numbers are module constants, easy to tune.
- **Debt-release interaction:** releasing the pin at budget must not strand a genuine unanswered
  player→NPC question. Mitigation: the player's direct address is a *fresh* debt (spent low on a new
  thread), so it is unaffected; only long-running NPC↔NPC threads hit the budget.

## Increment (green → commit → deploy)

1. **Talk-budget in `convo.py`** (spend counter + nudge + debt-release + merge handling), unit-tested.
2. **Playtest + tune + deploy** — confirm threads turn over (no 5-tick single-subject drag) without
   clipping a good exchange.
