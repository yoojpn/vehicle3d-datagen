#!/bin/bash
# 指定した時間(秒)が来たら、その時点までの進捗を保存して終了する。
# 予算(GPU時間)を超えないことを最優先にする設計。
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

# 時間制限で確実に終わらせているので、あとは手動確認で終了する(terminateは呼ばない)
echo "READY_FOR_MANUAL_TERMINATION" >> /tmp/status.log
cp /tmp/status.log "/workspace/repo/${LOG_FILE}" 2>/dev/null
cd /workspace/repo && git add "${LOG_FILE}" 2>/dev/null && git commit -m "final ${POD_TAG}" 2>/dev/null; timeout 20 git push origin main 2>/dev/null
sleep 60
