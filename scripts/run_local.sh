#!/usr/bin/env bash
# Запуск AI-DnD на локальных моделях. Прокидывает аргументы в `aidnd`.
#   ./scripts/run_local.sh serve   # веб   ·   ./scripts/run_local.sh   # терминал (по умолч.)
#   ./scripts/run_local.sh debug --quest dungeon   # консольный прогон сценария
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/local.env
source scripts/local.env

# поднять локальный Ollama, если не запущен
if ! curl -fsS "$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
  echo "→ Поднимаю ollama serve…"
  (ollama serve >/tmp/ollama-serve.log 2>&1 &) || true
  for _ in $(seq 1 20); do curl -fsS "$OLLAMA_HOST/api/tags" >/dev/null 2>&1 && break; sleep 1; done
fi

RUN=(python -m aidnd)
command -v uv >/dev/null 2>&1 && RUN=(uv run aidnd)
exec "${RUN[@]}" "${@:-serve}"
