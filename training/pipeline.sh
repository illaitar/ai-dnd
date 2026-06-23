#!/usr/bin/env bash
# Полный цикл НА СЕРВЕРЕ. Запуск детачно из ~/aidnd-training/training:
#   nohup bash pipeline.sh > run.log 2>&1 &
# install → split → QLoRA (лог лосса) → export(LoRA→GGUF→Ollama) → before/after.
set -uo pipefail
cd "$(dirname "$0")"
source ./config.env
ADAPTER="${ADAPTER:-quest}"

phase(){ echo; echo "######## $(date +%H:%M:%S) $* ########"; }
die(){ echo "!!!! FAIL: $*"; exit 1; }

phase "1/6 venv + зависимости (unsloth/trl/peft/bitsandbytes/…)"
python3 -m venv .venv || die "venv"
. .venv/bin/activate
pip -q install -U pip || die "pip"
pip install -U unsloth unsloth_zoo transformers trl peft accelerate bitsandbytes datasets httpx gguf || die "deps"
python -c "import unsloth,transformers,trl;print('unsloth',unsloth.__version__,'| transformers',transformers.__version__,'| trl',trl.__version__)" || die "import"

phase "2/6 llama.cpp (конвертер LoRA→GGUF)"
[ -f "$HOME/llama.cpp/convert_lora_to_gguf.py" ] || \
  git clone --depth 1 https://github.com/ggerganov/llama.cpp "$HOME/llama.cpp" || \
  echo "warn: не удалось склонировать llama.cpp — экспорт в Ollama может не пройти"

phase "3/6 split train/eval ($ADAPTER)"
ADAPTER="$ADAPTER" python prepare.py --adapter "$ADAPTER" --src "../$SRC_JSONL" --holdout "$EVAL_HOLDOUT" || die "prepare"

phase "4/6 QLoRA SFT base=$BASE_HF (лог лосса → out/$ADAPTER/train_log.jsonl)"
BASE_HF="$BASE_HF" EPOCHS="$EPOCHS" LR="$LR" LORA_R="$LORA_R" LORA_ALPHA="$LORA_ALPHA" \
  MAX_SEQ="$MAX_SEQ" BATCH="$BATCH" GRAD_ACCUM="$GRAD_ACCUM" SEED="$SEED" \
  python -u train_lora.py --adapter "$ADAPTER" || die "train"

phase "5/6 export LoRA→GGUF→Ollama (aidnd-$ADAPTER, FROM $BASE_OLLAMA)"
LLAMA_CPP="$HOME/llama.cpp" BASE_HF="$BASE_HF" BASE_OLLAMA="$BASE_OLLAMA" \
  bash export_ollama.sh "$ADAPTER" \
  || echo "warn: экспорт не прошёл — адаптер обучен (out/$ADAPTER), экспортируем отдельно (см. README, merged-fallback)"

phase "6/6 before/after на локальной Ollama сервера"
python -u eval_compare.py --adapter "$ADAPTER" --before "$BASE_OLLAMA" --after "aidnd-$ADAPTER" \
  || echo "warn: eval не прошёл (возможно нет aidnd-$ADAPTER)"

phase "DONE — отчёт: reports/${ADAPTER}_compare.md"
