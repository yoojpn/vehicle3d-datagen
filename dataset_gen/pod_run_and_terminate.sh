#!/bin/bash
# 注意: set -e は意図的に使わない。途中のどのコマンドが失敗しても、
# 最後のself-terminateまで必ず到達させるため。

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
echo "REACHED_POST_PROCESSING" >> /tmp/status.log

# ログをGitHubに書き戻す(1回だけ、失敗しても後続処理は止めない)
if [ -n "${GITHUB_TOKEN}" ]; then
  cp /tmp/status.log /workspace/repo/pod_status.log
  git config user.email "pod@local"
  git config user.name "pod-runner"
  git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/yoojpn/vehicle3d-datagen.git"
  git add pod_status.log
  timeout 15 git commit -m "pod run status $(date +%s)" 2>&1 | head -5
  timeout 20 git push origin main 2>&1 | head -5
  echo "PUSH_ATTEMPTED" >> /tmp/status.log
fi

# terminateは必ず実行する(push成否に関わらず)
echo "attempting self-terminate: POD_ID=${RUNPOD_POD_ID}"
if [ -n "${RUNPOD_API_KEY}" ] && [ -n "${RUNPOD_POD_ID}" ]; then
  curl -s -m 20 -X POST "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "{\"query\": \"mutation { podTerminate(input: {podId: \\\"${RUNPOD_POD_ID}\\\"}) }\"}"
else
  echo "WARNING: cannot self-terminate, missing RUNPOD_API_KEY or RUNPOD_POD_ID"
fi


