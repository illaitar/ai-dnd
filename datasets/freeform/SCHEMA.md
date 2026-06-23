# Freeform-pipeline fine-tuning dataset

Цель: дообучить локальную модель надёжно держать **точную схему** трёх агентов цикла
обработки свободного ввода и **заземляться** на присутствующие сущности. Три под-задачи,
**один обучающий файл** `freeform.jsonl` (мульти-таск): каждая строка —

```json
{"messages":[
  {"role":"system","content":"<system-промпт нужного агента>"},
  {"role":"user","content":"<контекст ровно как на инференсе>"},
  {"role":"assistant","content":"<строгий JSON под схему агента>"}
]}
```

`system`-промпты берутся из `aidnd.inference.agents.PROMPTS` (router/arbiter/consequence),
`user` строится теми же шаблонами, что в `agents.route_action/decide_resolution/world_effects` —
чтобы обучение совпадало с инференсом. `build.py` валидирует выход и пишет невалидное в лог.

## 1. router → `route_action`
Классификация ввода игрока.
- **user**: сцена (место/выходы/affordances), присутствующие NPC, недавняя история, реплика.
- **out**: `{kind: query|dialogue|command|freeform, query_type?, verb?, target?, tone}`.
- Учим: `query` для вопросов о мире/себе; `dialogue` — речь присутствующему NPC; `command` —
  явная команда (verb из набора); `freeform` — всё остальное. Точные ключи, без `entity`/`action`.

## 2. arbiter → `decide_resolution`
Как разрешать freeform-действие.
- **user**: действие, сцена, оценка правдоподобия 0..1.
- **out**: `{resolution: auto_success|auto_fail|roll, ability?, skill?, dc?, target?, lasting_effect?, reason}`.
- Учим: тривиальное→auto_success; невозможное→auto_fail; рискованное→roll с навыком и DC
  (ниже DC — выше правдоподобие).

## 3. consequence → `world_effects`
Стойкие последствия успешного/крит-провального действия.
- **user**: действие, исход (success/critical_failure), локация, NPC рядом, предметы при себе.
- **out**: `{effects:[{kind: place|npc|item|self, name?, note?, trust?, fear?, affinity?, condition?, minutes?, flag?}]}`.
- Учим: следы на локации/NPC/предмете, ограниченные дельты отношений (−0.25..0.25),
  состояния, флаги; **тривиальное → пустой `effects`**; **только присутствующие сущности**
  (cast-дисциплина); HP/деньги/счётчики НЕ трогаем.

## Конвенции (валидируются build.py)
- Строго ключи схемы (никаких `entity`/`target_kind`/`type`/`value`).
- Заземление: `name`/`target` эффектов и `target` команд — из переданного каста сцены.
- Дельты отношений в [−0.25, 0.25]; `kind`/`verb`/`query_type`/`resolution` — из enum.
- Баланс: включать тривиальные действия (router→freeform/query, arbiter→auto_success,
  consequence→пусто), чтобы не было перекоса в «всегда эффект».
