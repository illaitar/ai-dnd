#!/usr/bin/env bash
# Публичное ДЕМО ПО ССЫЛКЕ: поднимает игровой бэкенд и отдаёт его в интернет через
# cloudflared quick-tunnel (БЕЗ домена и БЕЗ аккаунта Cloudflare). Запускать НА ДОМАШНЕМ
# СЕРВЕРЕ (там, где Ollama с адаптерами) из корня репозитория:
#
#   ./scripts/serve_public.sh
#
# Наружу торчит ТОЛЬКО игра (FastAPI). Ollama остаётся на localhost и в интернет не выходит.
# Ссылка вида https://<случайно>.trycloudflare.com печатается ниже (меняется при перезапуске).
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8000}"
export OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
export AIDND_MAX_SESSIONS="${AIDND_MAX_SESSIONS:-2}"   # одна GPU → держим наплыв в узде
export PYTHONPATH="$PWD/src:${PYTHONPATH:-}"           # импорт aidnd даже без pip install -e .

# --- 1) окружение + зависимости -------------------------------------------- #
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip -q install -e . >/dev/null 2>&1 || pip -q install fastapi "uvicorn[standard]" httpx

# --- 2) Ollama должна быть жива (локально) ---------------------------------- #
if ! curl -fsS "$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
  echo "✗ Ollama недоступна на $OLLAMA_HOST — запусти 'ollama serve' и проверь адаптеры (ollama list)"; exit 1
fi
echo "✓ Ollama онлайн; модели: $(ollama list 2>/dev/null | awk 'NR>1{printf "%s ", $1}')"

# --- 3) cloudflared (поставим бинарь, если нет) ----------------------------- #
CF="$(command -v cloudflared || true)"
if [ -z "$CF" ]; then
  echo "→ ставлю cloudflared…"
  arch="$(uname -m)"; bin="cloudflared-linux-amd64"
  [ "$arch" = "aarch64" ] || [ "$arch" = "arm64" ] && bin="cloudflared-linux-arm64"
  curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/${bin}" \
    -o "$HOME/.local/bin/cloudflared" --create-dirs
  chmod +x "$HOME/.local/bin/cloudflared"; CF="$HOME/.local/bin/cloudflared"
fi

# --- 4) запуск бэкенда (фон) + туннель (передний план) ---------------------- #
echo "→ uvicorn на 127.0.0.1:${PORT} (лог: /tmp/aidnd-web.log)"
.venv/bin/python -m uvicorn aidnd.server.app:app --host 127.0.0.1 --port "$PORT" \
  >/tmp/aidnd-web.log 2>&1 &
WEB_PID=$!
trap 'kill $WEB_PID 2>/dev/null' EXIT
for _ in $(seq 1 20); do curl -fsS "http://127.0.0.1:${PORT}/" >/dev/null 2>&1 && break; sleep 0.5; done

echo "→ публичная ссылка (держи это окно открытым):"
# --protocol http2: многие домашние сети режут QUIC/UDP, из-за чего туннель не встаёт
# (530 на публичном URL). HTTP/2 идёт по TCP/443 и проходит.
exec "$CF" tunnel --protocol http2 --url "http://localhost:${PORT}"
