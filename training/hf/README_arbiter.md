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
language:
  - ru
---

# aidnd-arbiter — арбитр свободных действий (Qwen3.5-9B + LoRA)

Решает, как разрешать **freeform**-действие игрока в движке **AI-DnD**. На вход —
действие, краткая сцена и оценка правдоподобия 0..1. На выход — **один** JSON:

```json
{"resolution": "auto_success|auto_fail|roll", "ability": …, "skill": …, "dc": …,
 "target": …, "lasting_effect": …, "reason": …}
```

- `auto_success` — тривиальное, без риска;
- `auto_fail` — невозможное;
- `roll` — рискованное: навык 5e + DC (ниже DC — выше правдоподобие).

## Как получился
- **База:** [unsloth/Qwen3.5-9B](https://huggingface.co/unsloth/Qwen3.5-9B) (Apache-2.0).
- **Метод:** QLoRA SFT (4-bit), 170 примеров, 3 эпохи; учили только ответ ассистента.
  Затем мердж в базу и квантизация в **Q4_K_M GGUF**.
- **Оценка** (30 отложенных, по 10 на тип resolution; метрика — совпадение с эталоном,
  DC с допуском ±2):

  | | resolution | skill (roll) | dc±2 (roll) | full |
  |---|---|---|---|---|
  | база Qwen3.5-9B | 10% | 0% | 0% | 10% |
  | **aidnd-arbiter** | **83%** | **80%** | **100%** | **77%** |

  База почти не держит схему арбитра; адаптер — обязателен. DC калибруется отлично
  (±2 в 100% бросков). Часть «промахов» — спорные (невозможное действие как очень
  сложный бросок DC≈22 вместо `auto_fail`), а не грубые ошибки.

## Запуск локально через Ollama
```bash
hf download Illaitar/aidnd-arbiter aidnd-arbiter-q4_k_m.gguf Modelfile --local-dir aidnd-arbiter
cd aidnd-arbiter && ollama create aidnd-arbiter -f Modelfile
ollama run aidnd-arbiter
```
> Требуется Ollama **0.17.1+** (Modelfile использует `RENDERER/PARSER qwen3.5`).

В движке AI-DnD роль `arbiter` (decide_resolution) указывает на `aidnd-arbiter`
(`AIDND_ARBITER_MODEL`, с откатом на базовую модель, если адаптера нет на сервере).
