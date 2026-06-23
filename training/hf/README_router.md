---
license: apache-2.0
base_model: unsloth/Qwen3.5-9B
library_name: gguf
tags:
  - gguf
  - ollama
  - lora
  - qlora
  - intent-classification
  - dnd
language:
  - ru
---

# aidnd-router — классификатор намерений игрока (Qwen3.5-9B + LoRA)

Роутер ввода для движка **AI-DnD**. На вход — сцена (место/выходы/affordances),
присутствующие NPC, недавняя история и реплика игрока. На выход — **один** JSON:

```json
{"kind": "query|dialogue|command|freeform", "query_type": …, "verb": …, "target": …, "tone": …}
```

- `query` — вопрос о мире/себе (look/items/who/exits/inventory/status/map);
- `dialogue` — речь присутствующему NPC (tone: neutral/friendly/hostile/deceptive/fearful);
- `command` — явная команда движку (verb: move/attack/buy/sell/loot/search/inspect/…);
- `freeform` — всё остальное (уходит арбитру на разрешение броском).

## Как получился
- **База:** [unsloth/Qwen3.5-9B](https://huggingface.co/unsloth/Qwen3.5-9B) (Apache-2.0).
- **Метод:** QLoRA SFT (4-bit), 178 примеров, 3 эпохи; учили только ответ ассистента.
  Затем мердж в базу и квантизация в **Q4_K_M GGUF**.
- **Оценка** (24 отложенных примера, стратиф. по 6 на класс; метрика — совпадение с эталоном):

  | | kind | +field | full |
  |---|---|---|---|
  | база Qwen3.5-9B | 75% | 67% | 50% |
  | **aidnd-router** | **92%** | **83%** | **71%** |

  Роутинг база умеет и сама (это классификация), но адаптер убирает ~⅓–½ ошибок,
  особенно на «грязных» вводах (сленг, опечатки, многословие) и в строгом `full` (тон/target).

## Запуск локально через Ollama
```bash
hf download Illaitar/aidnd-router aidnd-router-q4_k_m.gguf Modelfile --local-dir aidnd-router
cd aidnd-router && ollama create aidnd-router -f Modelfile
ollama run aidnd-router
```
> Требуется Ollama **0.17.1+** (Modelfile использует `RENDERER/PARSER qwen3.5`).

В движке AI-DnD роль `router` уже указывает на `aidnd-router` (`AIDND_ROUTER_MODEL`,
с откатом на базовую модель, если адаптера нет на сервере).
