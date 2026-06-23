#!/usr/bin/env bash
# Полный экспорт дообученной модели в Ollama через мердж (обход LoRA→GGUF reorder).
# НА СЕРВЕРЕ:  ./export_merged.sh quest
# merge(16bit) → convert_hf_to_gguf → quantize Q4_K_M → Modelfile(рендерер базы) → ollama create.
set -uo pipefail
cd "$(dirname "$0")"
source ./config.env
. .venv/bin/activate

ADAPTER="${1:-${ADAPTER:-quest}}"
LLAMA="${LLAMA_CPP:-$HOME/llama.cpp}"
OUT="out/${ADAPTER}"
MERGED="${OUT}/merged_16bit"
F16="${OUT}/${ADAPTER}-f16.gguf"
Q4="${OUT}/${ADAPTER}-q4_k_m.gguf"

step(){ echo; echo "#### $(date +%H:%M:%S) $* ####"; }

step "1/5 merge LoRA → 16bit"
python merge_lora.py --adapter "$ADAPTER" || { echo "FAIL merge"; exit 1; }

step "2/5 HF → GGUF f16"
python "$LLAMA/convert_hf_to_gguf.py" "$MERGED" --outfile "$F16" --outtype f16 || { echo "FAIL convert"; exit 1; }

step "3/5 quantize Q4_K_M (сборка llama-quantize, CPU — nvcc не нужен)"
command -v cmake >/dev/null 2>&1 || pip -q install cmake ninja || true
QUANT="$LLAMA/build/bin/llama-quantize"
if [ ! -x "$QUANT" ]; then
  cmake -S "$LLAMA" -B "$LLAMA/build" -DLLAMA_CURL=OFF -DGGML_NATIVE=ON >/dev/null 2>&1 \
   && cmake --build "$LLAMA/build" --target llama-quantize -j"$(nproc)" >/dev/null 2>&1 || true
fi
if [ -x "$QUANT" ]; then
  "$QUANT" "$F16" "$Q4" Q4_K_M && GGUF_USE="$(basename "$Q4")"
else
  echo "warn: llama-quantize нет → отдаём f16 (крупнее, но рабочее)"
  GGUF_USE="$(basename "$F16")"
fi

step "4/5 Modelfile (рендерер/парсер из базы $BASE_OLLAMA) + ollama create aidnd-$ADAPTER"
{
  echo "FROM ./${GGUF_USE}"
  # переносим qwen3.5 RENDERER/PARSER/TEMPLATE из рабочей базы (без её FROM)
  ollama show --modelfile "$BASE_OLLAMA" 2>/dev/null \
    | grep -E '^(TEMPLATE|RENDERER|PARSER)' || true
  echo "PARAMETER temperature 0"
  echo "PARAMETER top_p 0.95"
} > "${OUT}/Modelfile"
( cd "$OUT" && ollama create "aidnd-${ADAPTER}" -f Modelfile ) || { echo "FAIL ollama create"; exit 1; }

step "5/5 smoke-тест"
ollama run "aidnd-${ADAPTER}" "Верни {\"ping\":true} и ничего больше." 2>&1 | head -c 200
echo
echo "DONE: aidnd-${ADAPTER} ($GGUF_USE)"
