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
   - the **immersion taxonomy + ЖИВОСТЬ rubric** (verbatim, below) — the player reads as a
     demanding reader first, mechanic second;
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
## ЖИВОСТЬ    (four lines, each PASS/FAIL + one proving quote — see rubric)
## ТРЕЩИНЫ    (EVERY immersion break: exact quote + break class from the taxonomy; «трещин нет» must be earned, not defaulted)
## НАХОДКИ    (numbered, severe-first; quote the exact game string for each)
## ЖИВОЕ      (1-3 quoted moments that felt alive)
## МЁРТВОЕ    (1-3 quoted moments that felt canned, static, or template — or «не было»)
```
**НИТЬ is the primary artifact** — the frontend experience: every rendered narr/line/feed/digest
string VERBATIM (full, uncut), in play order; player actions as `〔…〕` stage directions; NPC lines
as `ИМЯ. текст`, yours as `ТЫ. текст`. No JSON, no coordinates, no failed-payload noise — only what
a human at the screen would read. Collect it AS YOU PLAY (append after every call), not from memory.
ЛОГ is the compact mechanical trace (one line per call, replies ≤80 chars). Analysis goes ONLY in
the sections after. Budget discipline: НИТЬ entries after EVERY call — when the call budget
tightens, cut exploration, never the НИТЬ. Navigation: don't lattice-walk node numbers — if lost
after ~6 moves, ask NPCs directions or return to a known hub (players have the visual map; API
agents don't — wandering findings are harness artifacts, not game bugs).

## Иммерсия — главная линза (paste the taxonomy into every player prompt)

The player is not a QA bot but a DEMANDING READER: play for the fiction, and log the exact string
every time the spell breaks. НИТЬ doubles as the evidence base — a break with no verbatim quote
doesn't count. Hunt actively; a report claiming zero cracks over 15+ ticks is suspect.

**Таксономия трещин** (class → what to catch):

| класс | что ловить |
|---|---|
| язык | грамматика, украинизмы/англицизмы, кривые числительные («минут 21»), канцелярит, обрубленные фразы |
| механика сквозь ткань | id в прозе (pool:0123, [key:9], ct:…), JSON-остатки, системные слова («контракт», «тик», «валидатор») в устах NPC |
| повторы/шаблоны | одна фраза у разных NPC, одинаковые приветствия, зацикленная сцена, рыночный гул как метроном |
| противоречия | NPC против своей персоны/своих же слов, двое врут по-разному об одном ПРОВЕРЯЕМОМ факте, мертвец говорит |
| всезнание | NPC знает то, чего не видел/не слышал (о игроке, о событиях за стеной) |
| статика | эмоция/отношение не сдвинулись после сильного события; сцена не заметила поступок игрока |
| тон | современные словечки, мета-язык, анахронизмы, ломающий стиль юмор |
| время/пространство | день/ночь путается, внутри/снаружи, NPC телепортируется, погода скачет |

**Рубрика ЖИВОСТЬ** (each line needs its proving quote):
- **свои-дела** — NPC живут собственной жизнью, когда игрок молчит (дела, споры, торг не про игрока)
- **память-мира** — мир помнит прошлые тики/дни (callbacks: «та треснутая кружка…»)
- **реакция** — поступок игрока меняет сцену (встали, замолчали, запомнили, донесли)
- **развитие** — слухи/события эволюционируют между тиками, а не крутятся на месте

Controller triage: language/tone cracks → берём как есть (experience claims); contradiction/
omniscience/static cracks → verify against DB first (was the fact real? did the emotion value
actually not move?) — a lying NPC is a feature, a contradicting WORLD is a bug.

## Coverage matrix (full playtests MUST report every row)

The report gets a `## ПОКРЫТИЕ` table — one line per aspect: `tested → verdict` or `skipped — why`.
A skipped row with no reason is a report defect. For focused presets, mark out-of-scope rows `n/a`.

| Aspect | Minimum probe |
|---|---|
| диалог+персоны | ≥2 NPCs, ≥2 exchanges each; coherence under a probing question |
| слухи | watch ≥3 /live ticks; do rumors evolve/connect? |
| freeform | ≥3 classes of /act (mundane/sensory/physical/sneaky/object) |
| квесты | discovery → accept → **pursue → complete or name the exact blocker** |
| гео | ask a PERSON «где …?» (never lattice-walk); then check map mark + journal told-row |
| экономика | THREE separate probes: NPC↔NPC observed · player BUY (market/buy or confirmed sale) · gift (/give) — they are different mechanics |
| контейнеры/крафт/еда | ≥1 attempt each via /act; quote the exact reply |
| сон/цикл дня | sleep once; verify morning batch fired (new offers/board) |
| хроника-аудит | see chronicle rules below |
| бой+последствия | through combat API only; afterwards check witnesses/wanted/flags |

## Infra vs game (rule learned from a false «всё сломано» report)

If ≥2 consecutive LLM-backed calls (/live /say /act /talk) error — STOP testing. Controller greps
the server log for `402|Payment|5xx|Insufficient`. Provider outage ⇒ every dependent verdict is
**BLOCKED (infra)**, never FAIL; movement, geo shares, and ticks all ride on LLM calls, so «goto
не работает» during an outage is an artifact, not a finding.

## Chronicle-audit rules

- `gt` is monotonic world time (compare with current gt via /scene) — recent-looking gt ≠ «ancient».
- The journal is CAPPED (PB journal_cap, oldest pruned regardless of kind): absence of an old event
  is prune-suspect, not «never recorded» — controller confirms against DB before a FAIL.
- Audit per kind (`?kind=person|place|quest|event`), not one flat limit=100 read.

## False alarms (check before reporting these as bugs)

| Player says | Reality check first |
|---|---|
| «доску нельзя взять / contract_accept: уговора нет» | board ads take via `board_take`; postings list carries ids |
| «бой не начинается / не работает» | duel started? `GET /api/play/combat` — drive it with `combat_act` |
| «NPC мёртв / пропал (со слов другого NPC)» | gossip lies — check `flags dead\|<pid>` + placements |
| «квест не закрылся, хотя я его убил» | narration kills no one — check the combat log actually ran |
| «в хронике чужие записи» | persistent world — the character has a past |
| «купил, но товар не пришёл» | `/give` is a GIFT — a purchase is market/buy or an executed sale; report which affordance was actually used |
| «навигация сломана: goto стоит, loc не меняется» | movement executes on /live ticks — did the ticks run (LLM up)? |
| «хроника пишет чужое/древнее время» | gt is current world time; check journal cap pruning first |

## Scenario presets

`quest` (find→accept→pursue→complete→aftermath) · `journal` (witness fidelity: overheard tiers,
no-omniscience) · `trade` (NPC market, haggle observation) · `combat` (duel through combat_act,
consequences: witnesses/wanted) · `free` (wander, report what feels alive/dead) · `grand`
(everything, 50+ ticks). Args after the preset = focus notes woven into the protocol.

## Grand preset (multi-phase, one adventurer)

Fresh world, exact player start (no debug skips, no funding). Chain 3-4 agents SEQUENTIALLY, each
a phase of ONE adventurer's life: A narrative/freeform → B quests → C items/economy → D combat/
consequences/chronicle-audit. Each dispatch inherits the exact end-state of the previous (loc,
coins, hp, active contracts, notable memories — paste the predecessor's «итоговое состояние»).
Each phase reports its tick count («тиков: N») and full НИТЬ. Controller peeks the DB between
phases (purse, contracts, journal counts) so drift is caught at the seam, not in the finale. If a
phase agent dies mid-run, the world state persists — re-dispatch a continuation agent with the
same inherited-life block. Full coverage matrix applies across the UNION of phases.
