# Journal: «Хроника → дела»

`server/play/engine/journal.py` + `handlers/misc.py journal_endpoint`. The player chronicle is a
**collection of quests**, not an ambient log: one first-person, past-tense history thread per quest,
worded by the narrator LLM from code-supplied facts on real quest events only. Reads top-to-bottom
as a story — «Ко мне обратилась Роза → Я согласился → Я обыскал помещение и понял, что она хотела
меня обобрать → Так и завершилось это дело.» Ships as-built per
[the quest-journal spec](superpowers/specs/2026-07-13-quest-journal-design.md).

## Single writer — `j_beat(cid, beat, facts)`

The one path to the persistent journal. Code decides *that* and *what* happened; the LLM only
*words* it; the store only appends and groups.

- Builds a RU facts block (pure string assembly, no invention), makes ONE `narrator` call
  (temp 0.4) → a first-person past-tense one-liner, clamped to the first sentence / 200 chars.
- Appends one row `kind='quest'`, `prov=beat`, `refs=[cid]` via `journal_add` — **no new table, no
  new column**; the beat rides in the existing `prov`.
- **Best-effort**: it runs AFTER the quest transaction commits. `LLMUnavailable` / empty / any error
  → returns without writing, never raises. No canned fallback line ([no-LLM-fallback](README.md)).
  The mechanic never waits on journaling; a skipped beat just leaves a gap the thread reads around.

**Beats** (`prov` values), each fired from an existing code seam:

| beat | seam | line |
|---|---|---|
| `offer` | `dialogue.py` — player asks about work, offer pops | «Ко мне обратился X, {облик}. Он попросил…» |
| `accept` | `_accept_contract` (contract_accept + board_take/`_take_incident`) | «Я взялся за это дело.» |
| `step` | `_ct_advance` (multi-step partial) | «Я {step}; оставалось {next} — шаг n из total.» |
| `twist` / `reveal` | `twist.py on_visit` | «Вскрылось: …» |
| `done` | `_contract_complete` | «Так и завершилось это дело — {что} доставлен.» |
| `overtaken` | `pipeline._recheck_overtaken` (accepted quest only) | «Дело уладилось без меня, я опоздал.» |

`failed` is a reserved beat with **no live path**: an accepted quest can only be `overtaken`, never
failed; expired offers were never accepted, so never reach the journal.

## All ambient writes deleted

The old chronicle wrote five capture hooks (overheard speech, met-people, visited-places, coin-gives,
item-reveals). **All removed.** Nothing non-quest reaches the persistent journal:

- `_mark_seen(bid)` still sets the `seen|<bid>` map flag but writes **no journal row** (its
  `prov`/`text` args are kept only for call-site compatibility). Map reveal keeps its own state.
- NPC-card memory still records meetings. Only the journal rows died.
- The in-scene **live feed** is untouched — only the *persistent* journal stopped capturing ambience.

`purge_legacy_once(wid)` runs a one-shot `DELETE FROM journal WHERE kind != 'quest'` per world
(guarded by a `journal_purged` flag) on the first read after deploy — legacy person/place/event rows
are unreadable and would compost fresh quest rows under the shared `journal_cap`. Old `kind='quest'`
rows survive with legacy `prov` and degrade gracefully into un-typed threads.

## Read path — grouping into дела

`GET /api/play/journal` (`journal_endpoint`, no LLM): reads all `kind='quest'` rows, groups by
`refs[0]=cid`, sorts each thread by `gt` ascending (story order), enriches each group with
`{title, giver, status}` from the live contract row (across ALL statuses), and returns дела
newest-beat-first:

```json
{"dela": [{"cid": "ct:sift:p_roza:20880", "title": "добыть для Розы Медовар",
           "giver": "Роза Медовар", "status": "done",
           "thread": [{"gt": 20940, "beat": "offer", "text": "Ко мне обратилась Роза Медовар…"}, …]}]}
```

`title` = `«{kind_ru} для {giver}»` (or the first line's prefix if the contract vanished →
`status:"unknown"`). The UI renders an expandable дела list; opening one shows the first-person thread.

## Next

- Richer beat markers/glyphs in the thread UI.
- A `failed` beat if an accepted-quest failure path is ever added.
- Optional `PB["journal_temp"]` (temperature is a local literal today).

Related: [quests.md](quests.md) (the quest events that fire beats) · [mind.md](mind.md) (deeds) ·
[service.md](service.md) (UI scaffold)
