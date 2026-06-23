#!/usr/bin/env bash
# Мониторинг удалённого обучения: фазы из run.log, кривая лосса из train_log.jsonl, GPU.
#   ./monitor.sh [adapter]
set -euo pipefail
cd "$(dirname "$0")"
source ./config.env
ADAPTER="${1:-${ADAPTER:-quest}}"
ssh "$SERVER" "cd ${REMOTE_DIR}/training 2>/dev/null && {
  echo '=== фазы (хвост run.log) ==='; tail -n 10 run.log 2>/dev/null;
  echo; echo '=== лосс (хвост train_log.jsonl) ==='; tail -n 15 out/${ADAPTER}/train_log.jsonl 2>/dev/null || echo '(обучение ещё не началось)';
  echo; echo '=== GPU ==='; nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader 2>/dev/null;
  echo; echo '=== процесс ==='; (kill -0 \$(cat run.pid 2>/dev/null) 2>/dev/null && echo \"pipeline ЖИВ (pid \$(cat run.pid))\") || echo 'pipeline не запущен/завершён'; }"
