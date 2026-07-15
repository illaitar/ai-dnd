# Controller harness (world prep, verification, day mechanics)

The CONTROLLER (you) uses these; the player agent never does.

## Server
```bash
pkill -f "port 8098"; sleep 1
env AIDND_OPEN_PLAY=1 AIDND_PROFILE=deepseek .venv/bin/python -m uvicorn aidnd.server.app:app \
  --host 127.0.0.1 --port 8098 >/tmp/playtest_server.log 2>&1 &
sleep 6; curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8098/api/play/scene   # → 200
```
App file log (quests warnings, validator rejections): `data/debug/play.log`.

## Day mechanics — getting a fresh quest morning
- The morning batch (`_world_events` → quest_morning) runs ONCE per game-day, day-gated by the
  `events_key` flag; it fires INSIDE `debug/skip`'s routine rerun when the skip crosses into an
  unconsumed morning.
- `POST /api/play/debug/skip?hours=24` → next day's morning (repeat to burn more days).
- One emergent quest holds the window at a time (`quest_active_max=1`); foreshadow beat lasts
  `quest_foreshadow_ticks` live ticks before the offer opens (run `POST /api/play/live` to advance).

## World-state truth (verify player claims BEFORE recording findings)
```bash
# live emergent contracts + their real predicate
sqlite3 data/live.db "SELECT id, status, data FROM contracts WHERE data LIKE '%sift%' ORDER BY rowid DESC LIMIT 3"
# is X actually dead? (val must be non-empty — an empty row ≠ dead; sqlite exits 0 on no rows!)
sqlite3 data/live.db "SELECT '['||val||']' FROM flags WHERE world_id=1 AND key='dead|<pid>'"
# where does an NPC actually live/stand
sqlite3 data/live.db "SELECT npc_id,node,home FROM placements WHERE world_id=1 AND npc_id='<pid>'"
# purses / journal
sqlite3 data/live.db "SELECT holder,coins FROM purse WHERE world_id=1 AND holder IN ('pc','<pid>')"
sqlite3 data/live.db "SELECT gt,kind,prov,text FROM journal WHERE world_id=1 ORDER BY id DESC LIMIT 10"
```

## Honest world-authoring (when a scenario needs material the world lacks)
Author through the sim's own vocabulary — deeds, flags, npc_state — never invent new mechanisms:
```bash
# a witnessed murder (unanswered_blood fuel): actor=killer, obj=victim (+ dead| flag for the victim)
sqlite3 data/live.db "INSERT INTO deeds (world_id,gt,actor,verb,obj,place,witnesses,status,data)
  VALUES (1,<gt>,'<killer>','murder','<victim>','<place>','[\"<witness>\"]','','{\"what\":\"<RU line>\"}')"
# a broken promise (broken_promise fuel) + the victim's grudge in npc_state.relationships
# a second deed touching the villain = twist fuel
# fund the player when completion needs coins:
sqlite3 data/live.db "UPDATE purse SET coins=100 WHERE world_id=1 AND holder='pc'"
```
Give the player only an IN-FICTION rumor as a starting hint (name + node) — never the contract id,
never the predicate.

## Replay (source of truth for НИТЬ)
Every play session is recorded server-side to `data/playtest_logs/replay-w{wid}-{ts}.txt` —
exactly what the UI rendered, in order. After a playtest: `ls -t data/playtest_logs/ | head -1`,
slice the session's window (headers carry gt), paste the relevant excerpt into the report's НИТЬ.
`newworld` rotates the file. Kill-switch: AIDND_NO_REPLAY=1 (don't set it during playtests).

## Output file
`data/debug/playtests/YYYY-MM-DD-HHMM-<slug>.md` — the player's ЛОГ/ВЕРДИКТЫ/НАХОДКИ/ЖИВОЕ verbatim,
then your appendix:
```
## МЕХАНИЧЕСКАЯ ПРОВЕРКА (controller)
- <claim> → confirmed / refuted (query + result)
## ТРИАЖ
- real findings → fix/backlog; false alarms → which cheat-sheet/world-truth line covers them
```

## Known sharp edges
- ALL servers share `data/live.db` regardless of port — `newworld` on a throwaway 8097 server
  DESTROYS the world your 8098 playtest is running in. Never call newworld from a side server;
  only the controller resets worlds, deliberately.
- Test fixtures that touch `_contract_complete`/journal MUST root-patch `session.persist._STORE`
  or rows leak into the real `data/live.db` — if the journal/contracts show `npc:marta`-style
  fixture ids, that's a test leak, clean it and note the offending test.
- deepseek can be slow (~10-25s per LLM call); size the player's call budget (~30) accordingly.

## Cold-start (a real new player)
- `POST /api/play/newworld {}` — fresh world from the pools (new live state; worlds.db pool intact).
  A new game starts in the EVENING (start_gt 19:40) — the first quest morning comes after night:
  the player should `rest` where lodging exists (or the controller skips) — resting is the authentic path.
- Cold worlds have NO deeds and NO live agendas: the first mornings yield plain_need quests (after
  agenda seeding) + guild lairs/incidents on the board. Conflict patterns need lived history.
- For a cold-start discovery test give the player NO hints at all — the test IS whether the world
  telegraphs its stories (gnaw on cards, foreshadow fretting, board postings, rumors).
