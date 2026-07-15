# Quests: emergent pipeline, predicate contracts, board, guild

`server/play/engine/quests/` + `mechanics/contracts.py` + `handlers/board.py`. A quest is NOT a
script: a **delegated NPC need**, a want-predicate over real world state ([principle 9](README.md)).
Completion is a world fact, no matter HOW it was reached — bought, stolen, extorted, coincidental.

## Predicate contracts

Every contract carries `done_any`: a **disjunction of real `_met` predicates** (the same grammar
`mind.md` agendas use — `have`/`wealth`/`dead`/`affinity`/`at`). Any one holding for the giver
closes the quest. The list is **append-only**: `done_any[0]` is fixed at birth and never mutated;
twists only ever APPEND another disjunct (widening routes, never invalidating progress).

- **Steps** (the improvised layer, `_build_step`): `bring` (acquire thing) · `deliver` (deliver
  OWN thing to person) · `visit` (go-look) · `befriend` (win over person) · `dead` (only a REAL
  enemy of the giver). One step or an AND-chain of 2-3. The LLM picks a kind + names candidates
  **verbatim** from a code-supplied list; `_build_step` rejects any unknown entity.
- **Completion** flows through the existing triggers `_contract_on_give` / `_on_move` / `_on_talk` /
  `_on_death` → `_ct_advance` (step++ or payout) → `_contract_complete` (pays reward, trust/affinity
  bump, favor deed). For emergent contracts `_sift_maybe_close` also fires: an active `src:"sift"`
  contract whose `done_any` is met closes immediately, whatever route made it true.
- **Reward**: coins from the giver's wallet (capped, `REWARD_CAP=30`); a poor private giver pays
  with the best real item in his own inventory. Neither → the seed is honestly skipped.

## Emergent quests — sift → judge → cast → offer → arc

The town already holds everything a quest is made of (agendas, deeds, affinities); the morning batch
turns that pressure into offers, and finishing an offer is **the same event** as the giver's
milestone closing. All of `quests/` is pure code except two LLM seams in `framing.py`; no model →
honest absence (boards/incidents continue), never a canned quest. Ships as-built per
[the emergent-quests spec](superpowers/specs/2026-07-12-emergent-quests-design.md).

**sift** (`seeds.py`) — **6 launch patterns** scan pool agendas + the deeds journal + affinity edges
into fully-bound seeds:

- `kin_debt` — blocked acquire milestone + a promise deed naming the giver's kin + a disliked creditor.
- `broken_promise` — a broken promise + promiser alive + the aggrieved victim holds a grudge (public).
- `blocked_rival` — the giver's milestone blocked by a rival with **mutual** enmity.
- `unanswered_blood` — a witnessed murder/theft with no clearing answer; giver = living kin/friend
  of the (dead) victim (public).
- `courtship_wall` — a stalled affinity (courtship) milestone toward a beloved.
- `plain_need` — last resort: ANY giver with an open delegatable milestone, no villain needed;
  keeps aspiration-only worlds producing seeds. Salience naturally keeps these below flavored ones.

Milestone-anchored patterns lift the giver's live `Milestone.done` **verbatim** into `done_any[0]`.
Grievance patterns (`broken_promise`/`unanswered_blood`) name the intended revenge predicate; at
seed-choice time `_ensure_milestone` INSERTS a real revenge `Agenda` into the giver's live state, so
the writeback advances a real cursor uniformly. Every seed's ids are resolved to real pids (names
tolerated) or the pattern abstains — an uncompletable quest is never offered.

**salience** (`salience.py`) — code owns ordering: `w_rare·rarity + w_peak·peak + w_near·proximity +
w_fresh·freshness`. `rarity = 1/(1+recent)`, `peak = |aff(giver→villain)| + max deed-weight`,
`proximity` = giver↔player node (1.0 same / 0.6 adjacent / 0.2 else), `freshness = 1 − age/5 days`.
Weights in `PB`; the deed-weight table and 5-day window are the only code constants.

**judge** (`framing.py`, LLM seam 1) — ONE call ranks the top-K seeds for narrative taste, vetoes
false ones, returns a "why compelling" line. Unparseable / no model → no offer this morning.

**cast** (`casting.py`, pure) — the seed's motivation → contract step + reward shape + a DC/danger
from the villain's real `malice` trait. The step IS the milestone→step bridge (`bridge.py`), so
completion flows through the unchanged triggers.

**framer** (`framing.py`, LLM seam 2) — writes 3 artifacts (pitch / foreshadow line / twist reveal).
An **apophenia validator** rejects any artifact naming an entity outside the seed's `allowed` set or
inventing a number code doesn't own (mirrors `_build_step`); one regenerate, else honest skip. If the
pitch names a place the giver knows, the real `direction_line` ([geo.md](geo.md)) is appended.

**arc** (`director.py` + `foreshadow.py` + `twist.py`) — a tiny persisted FSM (state = the contract
rows) that paces the TELLING only; minds are never throttled:

- **window/interrupt** — `quest_active_max` offers in flight; a new seed jumps the window only at
  `≥ quest_interrupt_k×` the weakest live one; the bumped seed waits and is re-scored next morning.
- **foreshadow** — for `quest_foreshadow_ticks` the cast get the framer's line + a hot impulse via
  the normal mind pipeline (same mechanism as oaths); then the offer surfaces. While a quest is
  open the giver's card keeps gnawing (`open_lines`), so he reads desperate, not calm.
- **offer** — private → giver `offered` (dialogue's emergent offer outranks the improvised one);
  public grievance/bounty → the shared board.
- **twist** — on first visit to the villain's node, `on_visit` APPENDS the twist's real disjunct to
  `done_any` and voices a reveal (journal + giver's next line). Gated by `quest_twist_p`.
- **overtaken / compost** — every morning `tick_morning` re-checks live seeds: a giver who advanced
  his milestone himself → close `overtaken` with an honest line; an offer unaccepted for
  `quest_offer_days` → close `expired`, the giver pursues his goal himself, and next morning's sift
  reads the fresh deeds (nemeses/sequels emerge with zero extra machinery). Morning also **seeds
  agendas** (`quest_plan_n` agenda-less NPCs get a `plan_agenda` life-goal) so the sifter has material.

**writeback** (`bridge.py`) — on completion of a `src:"sift"` contract, verify `done_any[0]` still
`_met` and the anchored milestone still open, then `Agenda.cursor += 1` and `plan_agenda` the next
ambition. The giver's REAL long-term goal moves — the pitch was mechanical truth, not flavor.

## Board & city incidents

`handlers/board.py`. The board aggregates three sources: **guild jobs** (lair clears by CR), **city
incidents** (`engine/incidents.py` — gangs, haunts, kidnappings born from the sim, see
[dungeons.md](dungeons.md)), and
**public emergent postings** (`broken_promise`/`unanswered_blood` seeds the director surfaced).

- **Incidents** carry a real bid + door node binding, a live **patron** who pays from their OWN
  wallet (guild only as a channel), and the true `direction_line` appended to the pitch.
- **`board_take`** (and delving straight in) writes an active contract, `_mark_seen`s the building,
  and writes an `accept` journal beat under the patron's name.
- NPC passersby still post from agendas and fulfill orders themselves (`_board_npc_fulfill`).

## Adventurers' Guild

Building + till + lair clears by CR ([combat.md](combat.md)). 5 progressive **ranks**; rank = a
credentials-ITEM (badge). A foreign badge works, but the guild checks the lie (Insight vs Deception)
— fail = confiscation + blacklist. NPC parties run sorties through the same combat engine; morning
clears return lairs' "life" to the economy.

## Next

- Step trees (now AND-chains); authored multi-quest chains / MICE nesting.
- Guild sends beyond the city into procedural interiors ([combat.md](combat.md) "next").
- Main-plot tasks over the same predicate mechanism ([plot.md](plot.md)) — emergent quests stay
  self-contained town business, deliberately not a scripted spine.

Related: [mind.md](mind.md) (agendas/deeds) · [journal.md](journal.md) (per-quest chronicle) ·
[geo.md](geo.md) (grounded pitches) · [items.md](items.md) (bring/deliver targets) ·
[entities.md](entities.md) (contracts in DB)
