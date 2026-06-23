#!/usr/bin/env bash
# Конвертирует обученный LoRA-адаптер в GGUF и регистрирует его в Ollama поверх базы.
# Запускать НА сервере после train_lora.py. Требует llama.cpp (convert_lora_to_gguf.py).
#
#   source config.env && ./export_ollama.sh quest
#
# Результат: модель Ollama `aidnd-<adapter>` = BASE_OLLAMA + ADAPTER (общая база, лёгкий адаптер).
set -euo pipefail
cd "$(dirname "$0")"
source ./config.env

ADAPTER="${1:-${ADAPTER:-quest}}"
LLAMA_CPP="${LLAMA_CPP:-$HOME/llama.cpp}"
OUT="out/${ADAPTER}"
GGUF="${OUT}/${ADAPTER}-lora.gguf"

if [[ ! -d "$OUT" ]]; then echo "нет адаптера: $OUT (сначала train_lora.py)"; exit 1; fi
if [[ ! -f "$LLAMA_CPP/convert_lora_to_gguf.py" ]]; then
  echo "нет llama.cpp в $LLAMA_CPP — задай LLAMA_CPP=/path/to/llama.cpp"; exit 1; fi

# Конвертеру нужна база как ЛОКАЛЬНЫЙ путь к весам, а не HF repo-id (иначе os.listdir
# по repo-id → FileNotFoundError). Если BASE_HF не папка — резолвим снапшот из HF-кэша
# (unsloth уже скачал его при обучении, local_files_only=True не качает заново).
if [[ -d "$BASE_HF" ]]; then
  BASE_DIR="$BASE_HF"
else
  BASE_DIR="$(python - "$BASE_HF" <<'PY'
import sys
from huggingface_hub import snapshot_download
print(snapshot_download(sys.argv[1], local_files_only=True))
PY
)"
fi
echo "→ база (локальный снапшот): $BASE_DIR"

echo "→ конвертация LoRA → GGUF (f16)"
python "$LLAMA_CPP/convert_lora_to_gguf.py" "$OUT" --base "$BASE_DIR" --outfile "$GGUF" --outtype f16

echo "→ Modelfile (FROM $BASE_OLLAMA + ADAPTER)"
cat > "${OUT}/Modelfile" <<EOF
FROM ${BASE_OLLAMA}
ADAPTER ${ADAPTER}-lora.gguf
PARAMETER temperature 0
EOF

echo "→ ollama create aidnd-${ADAPTER}"
( cd "$OUT" && ollama create "aidnd-${ADAPTER}" -f Modelfile )
echo "готово: aidnd-${ADAPTER}"
