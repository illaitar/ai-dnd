#!/usr/bin/env bash
# Публикация дообученной модели на HuggingFace Hub (GGUF + Modelfile + карточка).
# Запускать НА СЕРВЕРЕ (там лежит GGUF), ПОСЛЕ `hf auth login`:
#
#   ./hf/upload.sh                 # репо по умолчанию nikalutis/aidnd-quest
#   HF_REPO=user/repo ./hf/upload.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source ./config.env
. .venv/bin/activate

ADAPTER="${1:-quest}"
HF_REPO="${HF_REPO:-nikalutis/aidnd-quest}"
OUT="out/${ADAPTER}"
GGUF="${OUT}/${ADAPTER}-q4_k_m.gguf"
[ -f "$GGUF" ] || GGUF="${OUT}/${ADAPTER}-f16.gguf"   # фоллбэк, если quantize не собрался

hf auth whoami >/dev/null 2>&1 || { echo "сначала: hf auth login"; exit 1; }

echo "→ создаю/обновляю репо $HF_REPO"
hf repo create "$HF_REPO" --repo-type model -y 2>/dev/null || true

echo "→ заливаю карточку и Modelfile"
hf upload "$HF_REPO" hf/README.md README.md --repo-type model
# Modelfile с ссылкой на gguf-файл репозитория (для `ollama create` после скачивания)
printf 'FROM ./%s\n' "aidnd-${ADAPTER}-q4_k_m.gguf" > "${OUT}/Modelfile.hf"
ollama show --modelfile "$BASE_OLLAMA" 2>/dev/null | grep -E '^(TEMPLATE|RENDERER|PARSER)' >> "${OUT}/Modelfile.hf" || true
printf 'PARAMETER temperature 0\nPARAMETER top_p 0.95\n' >> "${OUT}/Modelfile.hf"
hf upload "$HF_REPO" "${OUT}/Modelfile.hf" Modelfile --repo-type model

echo "→ заливаю GGUF ($(du -h "$GGUF" | cut -f1)) — это долго"
hf upload "$HF_REPO" "$GGUF" "aidnd-${ADAPTER}-q4_k_m.gguf" --repo-type model

echo "готово: https://huggingface.co/${HF_REPO}"
