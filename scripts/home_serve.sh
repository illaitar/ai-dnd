#!/usr/bin/env bash
# Идемпотентный запуск публичного демо на ДОМАШНЕЙ машине: uvicorn (:PORT) + reverse-SSH-туннель
# на VPS, каждый под keepalive-циклом (само-перезапуск при падении/обрыве). Дёргается deploy.sh по ssh.
#   ./scripts/home_serve.sh {start|restart|stop|status}
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
PORT="${AIDND_PORT:-8000}"
PUBLIC_PORT="${AIDND_PUBLIC_PORT:-80}"
VPS="${AIDND_VPS:-root@154.222.8.94}"
export OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
export AIDND_MAX_SESSIONS="${AIDND_MAX_SESSIONS:-2}"
export PYTHONPATH="$ROOT/src"
PY="$ROOT/.venv/bin/python"
UMARK="aidnd_ka_uvicorn"     # маркеры в argv → надёжный pkill keepalive-обёрток
TMARK="aidnd_ka_tunnel"

stop() {
  pkill -f "$UMARK" 2>/dev/null || true          # сначала keepalive-обёртки, иначе воркер перезапустится
  pkill -f "$TMARK" 2>/dev/null || true
  sleep 1
  pkill -f "uvicorn aidnd.server.app" 2>/dev/null || true
  pkill -f "ssh -N -R 0.0.0.0:${PUBLIC_PORT}:localhost:${PORT}" 2>/dev/null || true
  sleep 1
}

start() {
  setsid bash -c ": $UMARK; while true; do \
      \"$PY\" -m uvicorn aidnd.server.app:app --host 0.0.0.0 --port $PORT >>/tmp/aidnd-uv.log 2>&1; \
      echo \"[\$(date +%T)] uvicorn exited -> restart in 3s\" >>/tmp/aidnd-uv.log; sleep 3; \
    done" >/dev/null 2>&1 </dev/null &
  setsid bash -c ": $TMARK; while true; do \
      ssh -N -R 0.0.0.0:${PUBLIC_PORT}:localhost:${PORT} -o ServerAliveInterval=30 \
        -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=accept-new \
        -o BatchMode=yes \"$VPS\" >>/tmp/aidnd-tunnel.log 2>&1; \
      echo \"[\$(date +%T)] tunnel dropped -> reconnect in 3s\" >>/tmp/aidnd-tunnel.log; sleep 3; \
    done" >/dev/null 2>&1 </dev/null &
}

status() {
  echo "uvicorn: $(pgrep -f 'uvicorn aidnd.server.app' | tr '\n' ' ')"
  echo "tunnel:  $(pgrep -f "ssh -N -R 0.0.0.0:${PUBLIC_PORT}:localhost:${PORT}" | tr '\n' ' ')"
  curl -sS -m6 -o /dev/null -w "local :$PORT -> %{http_code}\n" "http://localhost:$PORT/" 2>/dev/null \
    || echo "local curl: FAIL"
}

case "${1:-restart}" in
  start)   start; sleep 4; status ;;
  restart) stop; start; sleep 4; status ;;
  stop)    stop; echo stopped ;;
  status)  status ;;
  *) echo "usage: $0 {start|restart|stop|status}"; exit 1 ;;
esac
