#!/bin/bash
# 指定した時間(秒)が来たら、その時点までの進捗を保存して終了する。
# 予算(GPU時間)を超えないことを最優先にする設計。
#
# 重要: このスクリプト自体のself-terminateとは別に、
# Runpodのdocker起動コマンド側で「nohup sleep TIME; runpodctl stop pod $RUNPOD_POD_ID」を
# 並行実行する二重の安全装置を必ず併用すること。
# (このスクリプト内の処理が予期せず固まっても、確実に時間切れで停止するため)
TIME_LIMIT_SEC="${TIME_LIMIT_SEC:-32760}"  # デフォルト約9.1時間
START_IDX="${START_IDX:-0}"
WORKERS="${WORKERS:-1}"
GITHUB_TOKEN="${GITHUB_TOKEN}"
OUT_DIR="/workspace/output_budget"
POD_TAG="${RUNPOD_POD_ID:-unknown_$(date +%s)}"
LOG_FILE="pod_budget_${POD_TAG}.log"

cd /workspace/repo

echo "=== BUDGET-LIMITED RUN: time_limit=${TIME_LIMIT_SEC}s ===" > /tmp/status.log
echo "start=$(date +%s)" >> /tmp/status.log

# バックグラウンドで大きめの件数(時間内で終わらない前提の上限)を投げ、
# タイムアウトコマンドで強制的に時間内に収める
timeout "${TIME_LIMIT_SEC}" python3 dataset_gen/run_batch.py \
  --start "${START_IDX}" --end "$((START_IDX + 200000))" \
  --workers "${WORKERS}" \
  --templates dataset_gen/structure_templates_300_v2.json \
  --ops_dir "${OUT_DIR}/ops" \
  --out "${OUT_DIR}/rendered" >> /tmp/status.log 2>&1

echo "=== TIME LIMIT REACHED OR RUN COMPLETED ===" >> /tmp/status.log
echo "end=$(date +%s)" >> /tmp/status.log

# 完了した件数を数える
COMPLETED=$(find "${OUT_DIR}/rendered" -name "mesh.glb" 2>/dev/null | wc -l)
echo "completed_count=${COMPLETED}" >> /tmp/status.log

if [ -n "${GITHUB_TOKEN}" ]; then
  cp /tmp/status.log "/workspace/repo/${LOG_FILE}"
  git config user.email "pod@local"
  git config user.name "pod-runner"
  git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/yoojpn/vehicle3d-datagen.git"
  git add "${LOG_FILE}"
  timeout 15 git commit -m "budget run ${POD_TAG}"
  timeout 20 git pull --no-edit origin main
  timeout 20 git push origin main
fi

# push完了後、確実にself-terminateする(セッション切れ対策として必須)
sleep 5
echo "attempting self-terminate: POD_ID=${RUNPOD_POD_ID}" >> /tmp/status.log
if [ -n "${RUNPOD_API_KEY}" ] && [ -n "${RUNPOD_POD_ID}" ]; then
  cat > /tmp/terminate_query.json << EOF
{"query": "mutation { podTerminate(input: {podId: \"${RUNPOD_POD_ID}\"}) }"}
EOF
  curl -s -m 20 -X POST "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
    -H "Content-Type: application/json" \
    --data @/tmp/terminate_query.json
fi
