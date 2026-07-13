---
name: playtest
description: Use when the user asks to playtest the game, verify a feature live «глазами игрока», or check how a system feels in real play (quests, journal, trade, combat, dialogue). Runs a haiku player-agent against the dev server and delivers a compact conversation log + analysis, saved to a file.
---

# Playtest (haiku player harness)

Run a cheap LLM agent as a *blind player* against the live dev server, then deliver: a **compact
turn-by-turn log of real game conversations**, verdicts per objective, findings triaged by severity —
written to `data/debug/playtests/YYYY-MM-DD-HHMM-<slug>.md` and summarized in chat.

**Announce at start:** "I'm using the playtest skill — dispatching a haiku player."

## Process

1. **Server.** `pkill -f "port 8098"` then
   `env AIDND_OPEN_PLAY=1 AIDND_PROFILE=deepseek .venv/bin/python -m uvicorn aidnd.server.app:app --host 127.0.0.1 --port 8098 &` (log to /tmp). Verify `/api/play/scene` → 200.
2. **Scenario prep (controller only).** Read [references/harness.md](references/harness.md) for
   world-state queries, `debug/skip` day-gate semantics, and honest world-authoring (deeds, purse).
   Never let the *player* run debug endpoints.
3. **Dispatch ONE haiku subagent** (`model: haiku`) with:
   - the FULL affordance cheat-sheet from [references/api-cheatsheet.md](references/api-cheatsheet.md)
     pasted in (players fail on missing affordances, not missing skill);
   - the world-truths block (verbatim, below);
   - the scenario protocol (phases + call budget ~30);
   - the **report contract** (below) — the log format is the deliverable.
4. **Verify before believing.** Every mechanical claim in the report (deaths, completions, rewards,
   "X is broken") gets checked against the DB/API per harness.md before it becomes a finding.
   Player *experience* claims (confusing, vague, alive) are taken as-is.
5. **Write the file** (log + analysis + your mechanical-verification appendix), then summarize in
   chat: verdicts, real findings vs false alarms, the best living moment.

## World-truths block (paste into every player prompt)

> - Твой персонаж живёт в постоянном мире: старые записи в хронике — история, не баги.
> - Горожане сплетничают и ЛГУТ (могут «похоронить» живого). Верь доске, контрактам и своим глазам.
> - Рассказ ≠ механика: смерть/завершение подтверждай через /contracts, /journal — не через красивый текст.
> - Бой идёт ТОЛЬКО через GET /api/play/combat + POST /api/play/combat_act. Свободный текст не убивает.

## Report contract (the player must return exactly this shape)

```
## НИТЬ — что читалось на экране
        〔входишь: Кузница «Железный зуб»〕
        〔подходишь к Горму Долинному〕
  ГОРМ ДОЛИННЫЙ. А, дорогой друж! Снова ты. Присаживайся, налью чего покрепче.
  ТЫ. что тебя гложет?
  ГОРМ ДОЛИННЫЙ. Ох, заботы трактирщика, сами знаете…
        〔даю 50 монет〕
  Ты отсчитываешь 50 монет и вкладываешь в ладонь Горма. Уговор исполнен! Горм отсыпает тебе 30 зм.
## ЛОГ — механика
[gt 1950] → talk pool:0246 · [gt 1955] → say · [gt 1961] → give coins:50 → done, +30
## ВЕРДИКТЫ   (one line per scenario objective: PASS/FAIL/BLOCKED + why)
## НАХОДКИ    (numbered, severe-first; quote the exact game string for each)
## ЖИВОЕ      (1-3 quoted moments that felt alive)
```
**НИТЬ is the primary artifact** — the frontend experience: every rendered narr/line/feed/digest
string VERBATIM (full, uncut), in play order; player actions as `〔…〕` stage directions; NPC lines
as `ИМЯ. текст`, yours as `ТЫ. текст`. No JSON, no coordinates, no failed-payload noise — only what
a human at the screen would read. Collect it AS YOU PLAY (append after every call), not from memory.
ЛОГ is the compact mechanical trace (one line per call, replies ≤80 chars). Analysis goes ONLY in
the sections after.

## False alarms (check before reporting these as bugs)

| Player says | Reality check first |
|---|---|
| «доску нельзя взять / contract_accept: уговора нет» | board ads take via `board_take`; postings list carries ids |
| «бой не начинается / не работает» | duel started? `GET /api/play/combat` — drive it with `combat_act` |
| «NPC мёртв / пропал (со слов другого NPC)» | gossip lies — check `flags dead\|<pid>` + placements |
| «квест не закрылся, хотя я его убил» | narration kills no one — check the combat log actually ran |
| «в хронике чужие записи» | persistent world — the character has a past |

## Scenario presets

`quest` (find→accept→pursue→complete→aftermath) · `journal` (witness fidelity: overheard tiers,
no-omniscience) · `trade` (NPC market, haggle observation) · `combat` (duel through combat_act,
consequences: witnesses/wanted) · `free` (wander, report what feels alive/dead). Args after the
preset = focus notes woven into the protocol.
