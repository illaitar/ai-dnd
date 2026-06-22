#!/usr/bin/env bash
# Локальная установка всего стека на своём железе: Ollama + модели Qwen + зависимости.
# Запуск:  bash scripts/setup_local.sh
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/local.env
source scripts/local.env

echo "→ AI-DnD · локальная установка на своём железе"
echo "  OLLAMA_HOST=$OLLAMA_HOST"
echo "  base=$AIDND_MODEL   intent=$AIDND_INTENT_MODEL"
echo

# 1) Ollama -----------------------------------------------------------------
if ! command -v ollama >/dev/null 2>&1; then
  echo "→ Ollama не найден — ставлю…"
  case "$(uname -s)" in
    Darwin)
      if command -v brew >/dev/null 2>&1; then
        brew install ollama
      else
        echo "  ✗ Нет Homebrew. Установи Ollama с https://ollama.com/download и запусти скрипт снова."
        exit 1
      fi ;;
    Linux) curl -fsSL https://ollama.com/install.sh | sh ;;
    *) echo "  ✗ Неизвестная ОС — поставь Ollama вручную: https://ollama.com/download"; exit 1 ;;
  esac
fi
echo "✓ ollama: $(command -v ollama)"

# 2) сервер Ollama ----------------------------------------------------------
if ! curl -fsS "$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
  echo "→ Поднимаю ollama serve в фоне (лог: /tmp/ollama-serve.log)…"
  (ollama serve >/tmp/ollama-serve.log 2>&1 &) || true
  for _ in $(seq 1 30); do
    curl -fsS "$OLLAMA_HOST/api/tags" >/dev/null 2>&1 && break
    sleep 1
  done
fi
if curl -fsS "$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
  echo "✓ сервер Ollama отвечает на $OLLAMA_HOST"
else
  echo "✗ сервер Ollama не поднялся — проверь /tmp/ollama-serve.log"; exit 1
fi

# 3) модели -----------------------------------------------------------------
for m in "$AIDND_MODEL" "$AIDND_INTENT_MODEL"; do
  echo "→ ollama pull $m"
  ollama pull "$m"
done

# 4) зависимости проекта ----------------------------------------------------
if command -v uv >/dev/null 2>&1; then
  echo "→ uv sync"; uv sync
else
  echo "  (uv не найден — поставь зависимости вручную: python -m venv .venv && .venv/bin/pip install -e .)"
fi

# 5) проверка ---------------------------------------------------------------
echo; echo "→ Проверка (aidnd doctor):"
if command -v uv >/dev/null 2>&1; then uv run aidnd doctor; else python -m aidnd doctor; fi

echo
echo "✓ Готово. Запуск:"
echo "    ./scripts/run_local.sh serve     # веб-интерфейс на http://127.0.0.1:8000"
echo "    ./scripts/run_local.sh           # игра в терминале"
