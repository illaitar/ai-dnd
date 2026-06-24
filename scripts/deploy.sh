#!/usr/bin/env bash
# Деплой публичного демо ОДНОЙ командой (запускать из корня репо, напр. на Маке):
#   ./scripts/deploy.sh
#
# Делает: rsync кода на ДОМАШНЮЮ машину → idempotent рестарт там (uvicorn + reverse-туннель,
# оба под keepalive) → ждёт, пока публичный URL отдаст 200.
#
# Схема (почему так): дом за CGNAT (наружу только исходящий ssh) — игра крутится дома на :8000
# с локальной Ollama, а VPS публикует её reverse-SSH-туннелем. Подробности: scripts/home_serve.sh.
# Переопределяемо через env: AIDND_HOME_HOST, AIDND_HOME_DIR, AIDND_PUBLIC_URL.
set -euo pipefail
cd "$(dirname "$0")/.."
HOME_HOST="${AIDND_HOME_HOST:-nikalutis@192.168.3.26}"
HOME_DIR="${AIDND_HOME_DIR:-dnd-ai}"
PUBLIC_URL="${AIDND_PUBLIC_URL:-http://154.222.8.94}"

echo "→ rsync кода → $HOME_HOST:$HOME_DIR"
rsync -az --delete --exclude __pycache__ --exclude '*.pyc' src/aidnd/ "$HOME_HOST:$HOME_DIR/src/aidnd/"
rsync -az --exclude __pycache__ --exclude '*.pyc' scripts/ "$HOME_HOST:$HOME_DIR/scripts/"

echo "→ (пере)запуск демо на доме"
ssh -o BatchMode=yes "$HOME_HOST" "chmod +x '$HOME_DIR'/scripts/*.sh; '$HOME_DIR'/scripts/home_serve.sh restart"

echo "→ проверка публичного URL: $PUBLIC_URL"
code=""
for _ in $(seq 1 12); do
  code="$(curl -sS -m8 -o /dev/null -w '%{http_code}' "$PUBLIC_URL/" || true)"
  [ "$code" = "200" ] && { echo "✓ ЖИВО: $PUBLIC_URL"; exit 0; }
  sleep 2
done
echo "✗ $PUBLIC_URL не ответил 200 (последний код: ${code:-нет ответа})."
echo "  Туннель/VPS: на доме — tail /tmp/aidnd-tunnel.log; при переустановке VPS — scripts/vps_provision.sh."
exit 1
