#!/bin/bash
set -e

NUM_SAMPLES="${NUM_SAMPLES:-10}"
WORKERS="${WORKERS:-1}"
OUT_DIR="/workspace/output"
GITHUB_TOKEN="${GITHUB_TOKEN}"

cd /workspace/repo

echo "=== START: ${NUM_SAMPLES} samples ===" > /tmp/status.log

python3 dataset_gen/run_batch.py \
  --start 0 --end "${NUM_SAMPLES}" \
  --workers "${WORKERS}" \
  --templates dataset_gen/structure_templates_300_v2.json \
  --ops_dir "${OUT_DIR}/ops" \
  --out "${OUT_DIR}/rendered" >> /tmp/status.log 2>&1

echo "=== DONE ===" >> /tmp/status.log

# 結果ログをGitHubに書き戻す(ログ確認手段がないための対策)
if [ -n "${GITHUB_TOKEN}" ]; then
  cp /tmp/status.log /workspace/repo/pod_status.log
  git config user.email "pod@local"
  git config user.name "pod-runner"
  git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/yoojpn/vehicle3d-datagen.git"
  git add pod_status.log
  git commit -m "pod run status $(date +%s)" || true
  git push origin main || true
fi

echo "=== self-terminating ===" >> /tmp/status.log
echo "DEBUG: RUNPOD_API_KEY set=$([ -n "${RUNPOD_API_KEY}" ] && echo yes || echo no)" >> /tmp/status.log
echo "DEBUG: RUNPOD_POD_ID=${RUNPOD_POD_ID}" >> /tmp/status.log

if [ -n "${RUNPOD_API_KEY}" ] && [ -n "${RUNPOD_POD_ID}" ]; then
  TERMINATE_RESULT=$(curl -s -X POST "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "{\"query\": \"mutation { podTerminate(input: {podId: \\\"${RUNPOD_POD_ID}\\\"}) }\"}")
  echo "DEBUG: terminate result: ${TERMINATE_RESULT}" >> /tmp/status.log
else
  echo "WARNING: cannot self-terminate, missing RUNPOD_API_KEY or RUNPOD_POD_ID" >> /tmp/status.log
fi

# terminate結果を含めて再度push
if [ -n "${GITHUB_TOKEN}" ]; then
  cp /tmp/status.log /workspace/repo/pod_status.log
  git add pod_status.log
  git commit -m "pod run status (final) $(date +%s)" || true
  git push origin main || true
fi

