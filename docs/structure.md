# Структура кода: текущее → целевое

Карта дерева `src/aidnd` (~16.5k строк), честный список болячек и план миграции.
Кто куда смотрит: `server` оркеструет всех; доменные пакеты (`mind`, `society`, `citygraph`,
`items`, `combat`, `magic`, `plot`, `inference`, `worldgen`) друг друга НЕ импортируют
(исключение: mind → items/society) и не знают о сервере.

## Текущее дерево

```
src/aidnd/
  inference/   700   клиент (ретраи→LLMUnavailable) · бэкенды ollama/openai-compat · structured
  mind/       2000   разум: model/goals/value/act/brain/modulators/fsm/tick/memory/agenda/
                     llm_agent (decide_hybrid) / trade / tools / world (микромир тестов)
  society/     235   нужды · места · рутина (декларативные каталоги)
  citygraph/   850   генерация графа · A* · модель · параметры
  worldgen/   1100   store (обе sqlite) · enrich зданий · персоны · imagegen · enrichment
  items/       560   модель фактшита · smith · inspect · craft (граф материалов) · durability · loot_pool
  combat/      620   Combatant · Encounter · auto · encounters · dungeon
  magic/       390   grammar (бюджет/хэш/base_law) · inscribe (scribe_law/wild)
  plot/        260   bible · architect · casting (НЕ в рантайме)
  play/        130   population (Townsperson)                        ← близнец-огрызок
  content/           bestiary.json (322) · glyphs · материалы
  server/     8000   app · auth · db(postgres) · usage · debug-стенды · web/ (play.html,
                     citygen.py-рендер 1055) · play/: engine{core 802, world 1307, worldsim} ·
                     mechanics{items, contracts, combat} · handlers{10 доменных}
```

## Болячки (по данным ревизии 2026-07-04)

1. **`engine/world.py` — 1307 строк**, функции по 200-400 строк (`_live_build`, `_live_tick`,
   `_world_tick`) знают всё сразу: генерацию, рутину, LLM-планирование, бой.
2. **`_S` — нетипизированный dict-блоб** в contextvar, трогается из 50+ функций; выходы LLM —
   сырые dict без схем.
3. **mechanics → core напрямую** (`_S`, `PB`, `_store`) — механики приварены к сессии.
4. **Захардкоженный список глаголов** в промпте `_INTENT_SYS` + раздельные `_intent`/`_attempt`
   вместо решённого единого `resolve()` ([loop.md](loop.md)).
5. **Близнецы**: `aidnd/play` (130 строк) рядом с `server/play`; SVG-рендер города
   (`citygen.py`, 1055 строк) живёт в `server/web/`.
6. Нет deed-журнала: лента/сплетни/розыск/хроника — пять ad-hoc механизмов.

## Целевое дерево

```
src/aidnd/
  inference/       + schemas.py: ЕДИНАЯ граница — pydantic-схемы ВСЕХ LLM-выходов
                     (Intent, Verdict, Consequence, NpcDecision, SpellLaw, Persona, Contract)
  mind/ society/   как есть (эталон чистоты)
  citygraph/       + render.py (переезд server/web/citygen.py — визуал города к графу)
  worldgen/        + population.py (переезд aidnd/play — Townsperson/расселение); пакет play/ умирает
  items/ combat/ magic/ plot/ content/   как есть
  server/
    app.py auth db usage debug-стенды web/
    play/
      engine/
        session.py   ТИПИЗИРОВАННАЯ Session (Player / LiveScene / CombatRef) вместо _S-блоба
        core.py      PB · время · персист (худеет)
        loop.py      session_step + game_tick + durative-циклы + прерывания   [из world.py]
        resolve.py   resolve(text)→{домен,цели,args,verdict} · context_assembler ·
                     consequence(кламп-меню) · voice · world_lookup            [из world/freeform]
        world.py     только сцена: _live_build/_live_tick/_scene_dict (худеет до ~500)
        worldsim.py  адаптер society
        deeds.py     deed-журнал: append + выборки для сплетен/стражи/хроники/plot
      mechanics/     items · contracts · combat — принимают (session, store, pb) ПАРАМЕТРАМИ
      handlers/      тонкие эндпоинты: распаковал запрос → сервис → ответ
```

## План миграции (порядок = приоритет; каждый шаг — зелёный инкремент на прод)

1. **`engine/resolve.py` + `engine/loop.py`** — вынести сервисы и тик из `world.py`/
   `freeform.py`; поведение не меняется, world.py худеет вдвое.
2. **`inference/schemas.py`** — схемы LLM-выходов, валидация+кламп в одном месте
   (structured.py становится тонким парсером под схемами).
3. **Типизированная `Session`** — за фасадом `_S` (инкрементально: поле за полем), механики
   переводятся на параметры.
4. **Единый `resolve()`** — убить верб-лист `_INTENT_SYS`, слить recognition⊕arbiter.
5. **Переезды**: `aidnd/play` → `worldgen/population.py`; `server/web/citygen.py` →
   `citygraph/render.py`.
6. **`deeds.py`** — журнал дел + перевод сплетен/розыска/хроники/обращений на него
   ([entities.md](entities.md) «Дальше»).

Связано: [README.md](README.md) (принципы) · [loop.md](loop.md) · [entities.md](entities.md)
