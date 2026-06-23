#!/usr/bin/env bash
# Наблюдатель за удалённым обучением: каждые N секунд опрашивает сервер и печатает
# текущую фазу, последний лосс и загрузку GPU. Завершается сам на DONE/FAIL.
#
#   ./watch.sh                # адаптер из config.env, интервал 90 с
#   ./watch.sh quest 30       # адаптер quest, опрос каждые 30 с
#   WATCH_MAX=200 ./watch.sh  # максимум опросов (по умолчанию 120)
#
# Ctrl+C — выйти (на сервере обучение продолжит идти, оно детачное).
set -uo pipefail
cd "$(dirname "$0")"
source ./config.env

ADAPTER="${1:-${ADAPTER:-quest}}"
INTERVAL="${2:-90}"
MAX="${WATCH_MAX:-120}"

echo "наблюдаю ${SERVER}:${REMOTE_DIR}/training  адаптер=${ADAPTER}  интервал=${INTERVAL}с"
for ((i = 1; i <= MAX; i++)); do
  s=$(ssh -o ConnectTimeout=8 "$SERVER" "cd ${REMOTE_DIR}/training 2>/dev/null && {
    echo '--PHASE--'; grep '########' run.log 2>/dev/null | tail -n 1;
    echo '--TAIL--';  tail -n 2 run.log 2>/dev/null;
    echo '--LOSS--';  tail -n 1 out/${ADAPTER}/train_log.jsonl 2>/dev/null;
    echo '--GPU--';   nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader 2>/dev/null;
  }" 2>&1)
  printf '\n[%s] #%d\n%s\n' "$(date +%H:%M:%S)" "$i" "$s"
  if echo "$s" | grep -qE 'DONE — отчёт|!!!! FAIL'; then
    echo; echo "==== ПАЙПЛАЙН ЗАВЕРШЁН ===="
    echo "отчёт: scp ${SERVER}:${REMOTE_DIR}/training/reports/${ADAPTER}_compare.md reports/"
    exit 0
  fi
  sleep "$INTERVAL"
done
echo "достигнут лимит опросов (${MAX}); сервер мог ещё работать — запусти снова."
