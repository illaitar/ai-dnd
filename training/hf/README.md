---
license: apache-2.0
base_model: unsloth/Qwen3.5-9B
library_name: gguf
tags:
  - gguf
  - ollama
  - lora
  - qlora
  - dnd
  - quest-generation
language:
  - ru
---

# aidnd-quest — генератор квестов D&D 5e (Qwen3.5-9B + LoRA)

Дообученный квест-дизайнер для движка **AI-DnD** (вертикальный срез *Lost Mine of
Phandalin*). На вход — структурированный запрос квеста (cast: фракции/NPC/шаблоны
предметов/локации; и фиксированные поля kind/theme/tier/giver/reward/allowed_preds).
На выход — **один** полный квест в JSON, на русском, заземлённый на переданный cast
(никаких выдуманных id), предикаты завершения стадий только из allowed_preds.

## Как получился
- **База:** [unsloth/Qwen3.5-9B](https://huggingface.co/unsloth/Qwen3.5-9B) (Apache-2.0).
- **Метод:** QLoRA SFT (4-bit), 180 примеров, 3 эпохи, loss 1.13 → 0.28; обучали только
  ответ ассистента. Затем мердж в базу и квантизация в **Q4_K_M GGUF**.
- **Оценка** (20 отложенных квестов, метрика — валидатор схемы квест-билда):

  | | JSON распарсен | прошёл схему |
  |---|---|---|
  | база Qwen3.5-9B | 20/20 (100%) | **0/20 (0%)** — `missing key` |
  | **aidnd-quest** (этот Q4_K_M GGUF, через Ollama) | 20/20 (100%) | **15/20 (75%)** |
  | (референс: слитый fp16, через transformers) | 20/20 (100%) | 17/20 (85%) |

  База не выдаёт полную структуру квеста **никогда**; дообученная держит её в 75%
  под Q4_K_M (fp16 — 85%; ~10 п.п. — цена квантизации). Оставшиеся промахи —
  изредка выдуманный id вне cast или предикат стадии.

## Запуск локально через Ollama
```bash
# 1) скачать GGUF + Modelfile из этого репозитория
hf download Illaitar/aidnd-quest aidnd-quest-q4_k_m.gguf Modelfile --local-dir aidnd-quest
# 2) зарегистрировать в Ollama
cd aidnd-quest && ollama create aidnd-quest -f Modelfile
# 3) пользоваться
ollama run aidnd-quest
```
> Требуется Ollama **0.17.1+** (Modelfile использует `RENDERER/PARSER qwen3.5`).

В движке AI-DnD роль `quest_writer` уже указывает на `aidnd-quest`
(`AIDND_QUEST_MODEL`, с откатом на базовую модель, если адаптера нет на сервере).

## Формат запроса
System-промпт и схема входа/выхода — см. `datasets/quests/SCHEMA.md` в репозитории
движка. Промпт ожидает JSON-объект запроса в `user` и возвращает JSON-квест в `assistant`.
