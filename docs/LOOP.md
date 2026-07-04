# ИГРОВОЙ ЦИКЛ — архитектура (зафиксировано)

Карта тика мира и распила `server/play/main.py` (2340 строк) по доменам. Пошаговый мир: **действие
игрока = ход мира**. Правило: **никаких fallback** — нет LLM → жёстко ломаемся (см. память no-llm-fallback).

## Дерево

```
session_step(input)                                         play/loop.py
│  durative? (поход на N узлов / отдых до утра) → ЦИКЛ game_tick до прибытия|прерывания
│  мгновенное (реплика / каст / сделка)          → один game_tick
│
game_tick(action) → response                                play/loop.py :: tick()
├── player_logic
│   ├── input
│   │   ├── UI (ЕДИНСТВЕННЫЕ «кнопки»)
│   │   │   ├── inventory_view          смотреть сумку/экипировку        [det]
│   │   │   └── map_journey(node, N)    поход по графу на N тиков        [det]
│   │   │        пресеты = частные случаи: enter/exit/room/go-to → travel; каждый шаг:
│   │   │        world+npc тик → interrupt? → ПАУЗА | дальше
│   │   └── freeform text → recognition {домен,цели,args} [LLM] → роутинг в хендлер
│   └── HANDLERS  (много веток, роутинг по домену; общего низа НЕТ)
│        travel · dialogue · magic · combat · trade · crime · item · observe · social ·
│        rest · learn · plot · freeform
├── npc_logic          кольца A (сцена, LLM) · B (город, needs det) · C (актёры, редкий LLM) · D (толпа, det)
├── world_simulation   эконом · монстры · guild · plot-doom · decay   [det; фаза/сутки]
└── compose_response   сцена · лента+обращения · нарратор · прерывания · хроника
```

## arbiter — СЕРВИС (хендлер зовёт), не шаг конвейера

```
arbiter(intent) → verdict                                   play/resolve.py :: arbitrate()  [LLM]
  ВХОД (context_assembler): intent · world laws&lore (world_lookup) · scene · npcs_here
        (роль/персона/отношение/настроение) · player (hp/мана/усталость/инвентарь/способности/
        розыск/глифы/монеты) · history (последние действия+память)
  ВЫХОД verdict: possible(yes|no|conditional) · difficulty(шкала + числовой порог) ·
        axis(что проверяется) · stakes(успех/провал) · reason
  → хендлер сам разыгрывает difficulty (бросок или без).
```

## Каталог хендлеров (loop игрока)

| хендлер | входы | arbiter | LLM-роли | эффекты | модуль |
|---|---|---|---|---|---|
| travel | map_journey/enter/exit/room | нет | — | loc/время; прерывания | actions/travel.py |
| dialogue | заговорить/сказать/убедить/солгать/запугать | да | voice | доверие/симпатия/страх/память | actions/dialogue.py + mind |
| magic | круг/каст/прочесть (холст ИЛИ freeform) | нет (feasibility) | spell_scribe, narrator | мана/усталость/урон/статус/freeform/гримуар/табу | magic + actions/magic.py |
| combat | атака/защита/бегство/манёвр | манёвры | — | hp/статусы/смерть/лут | combat |
| trade | купить/продать/торг/оценить | торг | voice | монеты/инвентарь | actions/trade.py + items |
| crime | украсть/ограбить/вскрыть/влезть | да | — | инвентарь/розыск/свидетели | actions/crime.py |
| item | осмотреть/использовать/крафт/починить/дать | осмотр/крафт | item_smith | инвентарь/знание/статы | items + actions/item.py |
| observe | осмотреться/искать/явить | восприятие | narrator | туман/hidden/зацепки | actions/observe.py |
| social | подарить/помочь/befriend/контракт | — | voice | отношения/контракты/репутация | actions/social.py + contracts |
| rest | отдых/сон/лагерь (durative) | нет | — | hp/мана×3/усталость/время | actions/rest.py |
| learn | учиться (глифы/ремесло) | доступность | voice | глифы/рецепты/монеты | actions/learn.py |
| plot | по зацепке/уличить/вербовать/улика | композиция | plot_director | акт/зацепки/каст | plot |
| freeform | всё вне каталога → нарратив-исход | да | arbiter→narrator→consequence | по вердикту | actions/freeform.py |

**Сервисы (хендлеры дёргают, не дублируют):** arbiter · narrator · voice · world_lookup ·
context_assembler · consequence. Все [LLM] → без модели raise.

## Провизорные решения (мои дефолты; поправимы)

1. **Единая проверка:** там, где нужен бросок (dialogue/crime/observe/freeform) — одна система
   `d20 + axis-мод vs DC` из вердикта арбитра. Магия — исключение (без броска).
2. **recognition ⊕ arbiter:** один тяжёлый контекстный вызов `resolve(text)→{домен,цели,args,verdict}`
   (арбитр сам парсит намерение; отдельного лёгкого recognition нет).
3. **consequence с клампом:** freeform-последствия — LLM предлагает механические дельты из
   ОГРАНИЧЕННОГО меню (hp±/предмет/отношение/флаг/перемещение/раскрытие), код валидирует (как магия).
4. **interrupts в походе:** встреча(бой)/стража/сюжетный удар → ПАУЗА (выбор); амбиент/вывески → лента.

## Раскладка пакета server/play/ (распил main.py 2340 → сделано)

```
engine/                ядро (импорты внутри play — абсолютные)
  core.py              сессия _S/PB/router/время/мана/гримуар/розыск + базовые хелперы
  world.py             ЯДРО-сцена: _play/_scene_dict/_live_build/_live_tick/_world_tick/
                       _world_events/_apply_routine/_voice/_world_lookup/_watch_check
  worldsim.py          адаптер society (рутина NPC из нужд)
mechanics/             домены-механики (логика над aidnd.items/combat, без эндпоинтов)
  items.py · contracts.py · combat.py
handlers/              доменные хендлеры (эндпоинты /api/play/*)
  travel.py            /map /move /enter /exit /room /sign_ack /live + _path_interrupt
  dialogue.py          /talk /say
  magic.py             /cast /glyphs /learn /teachers /grimoire + spell-хелперы
  trade.py             /offer /sell /wares /buy /askkey
  crime.py             /steal
  inventory.py         /loot /inspect /inventory /commission /repair /use /give
  observe.py           /look
  freeform.py          /act (арбитр→нарратор→consequence)
  board.py             /board /guild_redeem /board_take /delve /surrender /watch_flee
  misc.py              /hero /debuglog
__init__.py            сборка router (импорт хендлеров = регистрация эндпоинтов)
```

Ещё не выделено (по мере правки логики): `engine/loop.py` (game_tick + session_step durative-циклы),
`engine/resolve.py` (arbiter/context_assembler/consequence — сейчас в handlers/freeform).
Правки логики (характеристики, привязка к mind, локации) — по этой карте.
