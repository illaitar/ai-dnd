#!/usr/bin/env bash
# Заливает код+датасеты на сервер и запускает pipeline.sh ДЕТАЧНО (переживает обрыв SSH).
# Мониторить: ./monitor.sh    Отчёт по завершении: training/reports/<adapter>_compare.md
#
#   source config.env && ./run_remote.sh
set -euo pipefail
cd "$(dirname "$0")"
source ./config.env

echo "==> rsync кода и датасетов → ${SERVER}:${REMOTE_DIR}"
ssh "$SERVER" "mkdir -p ${REMOTE_DIR}"
rsync -az --delete ../training ../datasets ../src "${SERVER}:${REMOTE_DIR}/" \
  --exclude '__pycache__' --exclude 'out' --exclude 'data' --exclude '.venv' \
  --exclude 'reports' --exclude '*.pyc' --exclude '.DS_Store' \
  --exclude 'unsloth_compiled_cache' --exclude 'dist' --exclude 'run.log' --exclude 'run.pid'

echo "==> запуск pipeline.sh детачно (ADAPTER=${ADAPTER}, BASE_HF=${BASE_HF})"
ssh "$SERVER" "cd ${REMOTE_DIR}/training && ADAPTER='${ADAPTER}' nohup bash pipeline.sh > run.log 2>&1 & echo \$! > run.pid; sleep 1; echo 'launched pid' \$(cat run.pid)"

echo
echo "монитор:        ./monitor.sh ${ADAPTER}"
echo "отчёт (потом):  scp ${SERVER}:${REMOTE_DIR}/training/reports/${ADAPTER}_compare.md reports/"
