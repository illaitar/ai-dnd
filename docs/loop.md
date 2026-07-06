# Игровой цикл

Пошаговый мир: **действие игрока = ход мира**. Без модели цикл не работает
([принцип 1](README.md)): `LLMUnavailable` → 503, `LLMBadOutput` → 502, игрок видит честную
строку и повторяет действие.

## Дерево тика

```
session_step(input)                                         (целевое: engine/loop.py)
│  durative (поход на N узлов / отдых до утра) → ЦИКЛ game_tick до прибытия|прерывания
│  мгновенное (реплика / каст / сделка)        → один game_tick
│
game_tick(action) → response
├── player_logic
│   ├── input
│   │   ├── UI-кнопки (ЕДИНСТВЕННЫЕ): инвентарь · map_journey(node, N) · войти/выйти ·
│   │   │   заговорить (клик по портрету) · кнопки боя/каста
│   │   └── freeform-текст → LLM-интент → роутинг в хендлер
│   └── HANDLERS (по доменам, см. каталог ниже)
├── npc_logic          кольца LOD:
│   │                  A — сцена игрока: полный гибрид, LLM-решения (кэп 8 душ = LOD)
│   │                  B — город: рутина из нужд, детерминированно (society)
│   │                  C — актёры (агенды/зачистки): редкий LLM
│   │                  D — толпа: чистая механика
├── world_simulation   эконом (караван/restock) · монстры · гильдия · decay  [det; фаза/сутки]
└── compose_response   сцена · лента (feed) + обращения (address) · нарратор · прерывания
```

## Поток одного действия (как в коде)

`/api/play/act` → `_play()` (мир в сессию) → `_scene_dict()` → `_intent(text)` [LLM] →
`_attempt(intent)` — единый резолвер (примитив × манера × гейты: броски, перенос предметов,
память, последствия) → `_gt_add(PB[...])` → `_world_tick()`:
`_apply_routine()` (кольцо B) + `_live_tick()` (кольцо A: `decide_hybrid` параллельно на
присутствующих, `apply_actions` исполняет — кража РЕАЛЬНО двигает предметы, речь пишется в
память/hist, сплетни разносятся) → ответ `{narr, feed, address, gt, coins, hp, mana}`.

Модули: `server/play/handlers/freeform.py` · `server/play/engine/world.py` (ядро-сцена) ·
`server/play/engine/worldsim.py` (адаптер society) · `server/play/engine/core.py`
(сессия `_S`, таблица `PB`, время, персист).

## Каталог хендлеров

| хендлер | входы | LLM-роли | эффекты | модуль (handlers/) |
|---|---|---|---|---|
| travel | map/move/enter/exit/room/sign_ack/live | — | локация/время; прерывания пути | travel.py |
| dialogue | talk/say (тон двигает отношения) | voice | доверие/симпатия/страх/память | dialogue.py |
| magic | cast/glyphs/learn/teachers/grimoire | spell_scribe, wild_magic | мана/усталость/урон/гримуар/табу | magic.py |
| combat-UI | атака/защита/бегство/манёвр | — | hp/статусы/смерть/лут | mechanics/combat.py |
| trade | offer/sell/wares/buy/askkey | voice | монеты/инвентарь | trade.py |
| crime | steal | — | инвентарь/розыск/свидетели | crime.py |
| inventory | loot/inspect/commission/repair/use/give | item_smith | инвентарь/знание/статы | inventory.py |
| observe | look | narrator | туман/hidden/зацепки | observe.py |
| board | board/guild_redeem/board_take/delve/surrender | — | контракты/касса/ранг | board.py |
| freeform | act (всё вне каталога) | narrator (интент+DM) | по вердикту | freeform.py |

**Сервисы** (хендлеры дёргают, не дублируют): интент · voice · world_lookup · нарратор.
Сейчас размазаны по `world.py`/`freeform.py` — целевое: `engine/resolve.py`
([structure.md](structure.md)).

## Прерывания пути

Поход по графу тикает мир на каждом шаге; прерывают: встреча (бой) / стража / вывеска
(кнопка «занести на карту») / сюжетный удар → ПАУЗА с выбором. Амбиент — в ленту без паузы.

## Принятые решения

- Единая проверка: где нужен бросок — `d20 + мод-оси vs DC`. Магия — исключение (без броска,
  срывы — противоречия рисунка, [magic.md](magic.md)).
- Тик продвигается ТОЛЬКО тратой игрового времени игроком; кратности нет; бой — раунд 5 сек,
  мир в масштабе минут стоит.
- Freeform-последствия: LLM предлагает дельты из ОГРАНИЧЕННОГО меню
  (hp±/предмет/отношение/флаг/перемещение/раскрытие), код валидирует.

## Дальше

- ✔ (2026-07-06) **Единый `resolve(text)`** — `engine/resolve.py`: реестр PRIMITIVES
  (глагол+цели+«когда») — единственная истина, промпт арбитра ГЕНЕРИТСЯ из реестра
  (добавить примитив = одна запись; рукописный `_INTENT_SYS` умер); контекст-сборщик
  отдаёт максимум фактов сцены (люди/ёмкости/сумка/зоны/предметы рядом/места/время);
  вердикт do|narrate (не-действие → DM-нарратор со снимком). Исполнители остались в
  `handlers/freeform._attempt` (примитив×манера×гейты).
- Выделить `engine/loop.py` (game_tick + durative-циклы); consequence-слой в
  `engine/resolve.py` — карта в [structure.md](structure.md).
- Deed-журнал как субстрат ленты/сплетен/стражи ([entities.md](entities.md)).

Связано: [mind.md](mind.md) (кольцо A изнутри) · [entities.md](entities.md) ·
[service.md](service.md) (лимиты на LLM-вызовы тика)
