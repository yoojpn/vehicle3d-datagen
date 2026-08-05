#!/bin/bash
# self-terminateを行わない。push(結果確認用)はする。
# これで「terminateがpush完了前にコンテナを殺している」可能性を切り分ける。
NUM_SAMPLES="${NUM_SAMPLES:-100}"
WORKERS="${WORKERS:-1}"
START_IDX="${START_IDX:-0}"
GITHUB_TOKEN="${GITHUB_TOKEN}"
OUT_DIR="/workspace/output_isolated"
POD_TAG="${RUNPOD_POD_ID:-unknown_$(date +%s)}"
LOG_FILE="pod_isolated_${POD_TAG}.log"

cd /workspace/repo

echo "=== ISOLATED TEST START: ${NUM_SAMPLES} samples ===" > /tmp/status.log
echo "start=$(date +%s)" >> /tmp/status.log

python3 dataset_gen/run_batch.py \
  --start "${START_IDX}" --end "$((START_IDX + NUM_SAMPLES))" \
  --workers "${WORKERS}" \
  --templates dataset_gen/structure_templates_300_v2.json \
  --ops_dir "${OUT_DIR}/ops" \
  --out "${OUT_DIR}/rendered" >> /tmp/status.log 2>&1

echo "=== ISOLATED TEST DONE ===" >> /tmp/status.log
echo "end=$(date +%s)" >> /tmp/status.log

if [ -n "${GITHUB_TOKEN}" ]; then
  cp /tmp/status.log "/workspace/repo/${LOG_FILE}"
  git config user.email "pod@local"
  git config user.name "pod-runner"
  git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/yoojpn/vehicle3d-datagen.git"
  git add "${LOG_FILE}"
  timeout 15 git commit -m "isolated test ${POD_TAG}"
  timeout 20 git pull --no-edit origin main
  timeout 20 git push origin main
  echo "push_done=$(date +%s)" >> /tmp/status.log
  cp /tmp/status.log "/workspace/repo/${LOG_FILE}"
  git add "${LOG_FILE}"
  timeout 15 git commit -m "isolated test final ${POD_TAG}"
  timeout 20 git push origin main
fi

echo "NO SELF-TERMINATE - waiting for manual termination"
sleep 300
