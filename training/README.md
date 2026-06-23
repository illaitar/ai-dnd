# Тренировочный пайплайн (multi-LoRA адаптеры под Ollama)

Дообучение per-role LoRA-адаптеров поверх общей базы — ровно как ждёт движок
(`ModelManager.ROLE_MODELS`: роль → (база, адаптер), напр. `quest_writer → "quest"`).
Один base в VRAM + лёгкие адаптеры по ролям.

## Где что считается
- **Тренировка — на сервере** (`nikalutis@192.168.3.26`, RTX 4070 Ti Super, 16 ГБ).
  Тут Mac без CUDA → `train_lora.py`/`export_ollama.sh` гоняются на сервере.
- **Подготовка данных и before/after eval — локально** (`prepare.py`, `eval_compare.py`):
  чистый Python + запрос модели через SSH-туннель Ollama (механизм из ai-dnd).

## База: обязательно совпадение HF ↔ Ollama
LoRA-адаптер приложится только к тем же весам, на которых обучался. В `config.env`:
- `BASE_HF` — репозиторий для обучения (Unsloth/HF),
- `BASE_OLLAMA` — тег той же модели в Ollama для инференса.
По умолчанию — `qwen2.5:1.5b-instruct` (уже стоит на сервере): быстрый прогон всего
пайплайна и самый наглядный before/after. Для продакшена подменить на 7–8B
(напр. `Qwen2.5-7B-Instruct` / `qwen2.5:7b-instruct`) — QLoRA 4-bit влезает в 16 ГБ.
> В конфиге движка стоит `qwen3.5:9b`, но на сервере её нет и такого тега не существует —
> поэтому база вынесена в переменную и фиксируется здесь.

## Быстрый старт
```bash
source config.env
# 1) сплит train/eval (детерминированный, стратиф. по tier) — локально
python prepare.py --adapter quest --src ../datasets/quests/quests.jsonl --holdout 20
# 2) бейзлайн «до» уже сейчас (туннель поднят), без обучения:
python eval_compare.py --adapter quest --before "$BASE_OLLAMA"
# 3) весь цикл на сервере (заливка → обучение → экспорт в Ollama) + before/after:
./run_remote.sh
```

## Файлы
| файл | где | что |
|---|---|---|
| `config.env` | — | база, сервер, адаптер, гиперпараметры |
| `prepare.py` | локально | `*.jsonl` → `data/<adapter>/{train,eval}.jsonl` |
| `train_lora.py` | сервер | Unsloth QLoRA SFT (учим только ответ ассистента) → `out/<adapter>/` |
| `export_ollama.sh` | сервер | LoRA → GGUF (llama.cpp) + Modelfile + `ollama create aidnd-<adapter>` |
| `eval_compare.py` | локально | before/after, метрика = валидатор квест-билда |
| `run_remote.sh` | локально | оркестрация всего цикла по SSH |

## Метрика before/after
`eval_compare.py` переиспользует `datasets/quests/build.validate`: на каждом eval-примере
строит тот же `user`-промпт, парсит JSON ответа и проверяет echo `kind/theme/tier/giver`,
предикаты только из `allowed_preds`, отсутствие выдуманных id, структуру стадий.
Выводит `% распарсенного JSON` и `% прошедшего валидацию` для базы и адаптера + Δ.

## Острые углы
- **GGUF-адаптер для Ollama.** `export_ollama.sh` зовёт `llama.cpp/convert_lora_to_gguf.py`
  (задать `LLAMA_CPP=/path/to/llama.cpp`). Архитектура адаптера должна совпасть с базой;
  при несовпадении — fallback: смержить LoRA в базу и сделать `FROM ./merged.gguf`.
- **eval идентичности.** `run_remote.sh` делает сплит на сервере; для побайтово того же
  eval локально скопируй `data/<adapter>/eval.jsonl` с сервера (или гоняй eval на сервере).
- **Другие адаптеры.** `freeform` (router/arbiter/consequence) обучается тем же пайплайном:
  `ADAPTER=freeform SRC_JSONL=datasets/freeform/freeform.jsonl`. Свой валидатор в eval — TODO.
