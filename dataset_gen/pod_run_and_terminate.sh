#!/bin/bash
# 注意: set -e は意図的に使わない。途中のどのコマンドが失敗しても、
# 最後のself-terminateまで必ず到達させるため。

NUM_SAMPLES="${NUM_SAMPLES:-10}"
WORKERS="${WORKERS:-1}"
START_IDX="${START_IDX:-0}"
GITHUB_TOKEN="${GITHUB_TOKEN}"

# ポッドごとに完全に独立した出力先・ログファイル名にする(他ポッドとの干渉を防ぐ)
POD_TAG="${RUNPOD_POD_ID:-unknown_$(date +%s)}"
OUT_DIR="/workspace/output_${POD_TAG}"
LOG_FILE="pod_status_${POD_TAG}.log"

cd /workspace/repo

echo "=== START: ${NUM_SAMPLES} samples (pod=${POD_TAG}, start_idx=${START_IDX}) ===" > /tmp/status.log

python3 dataset_gen/run_batch.py \
  --start "${START_IDX}" --end "$((START_IDX + NUM_SAMPLES))" \
  --workers "${WORKERS}" \
  --templates dataset_gen/structure_templates_300_v2.json \
  --ops_dir "${OUT_DIR}/ops" \
  --out "${OUT_DIR}/rendered" >> /tmp/status.log 2>&1

echo "=== DONE ===" >> /tmp/status.log
echo "REACHED_POST_PROCESSING" >> /tmp/status.log

# ログをGitHubに書き戻す(ファイル名がポッドごとに違うので、他ポッドとコンフリクトしない)
if [ -n "${GITHUB_TOKEN}" ]; then
  cp /tmp/status.log "/workspace/repo/${LOG_FILE}"
  git config user.email "pod@local"
  git config user.name "pod-runner"
  git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/yoojpn/vehicle3d-datagen.git"
  git add "${LOG_FILE}"

  PUSH_OK=0
  for attempt in 1 2 3; do
    timeout 15 git commit -m "pod ${POD_TAG} status $(date +%s)" 2>&1 | head -5
    timeout 20 git pull --no-edit origin main 2>&1 | head -5
    if timeout 20 git push origin main 2>&1 | head -5; then
      PUSH_OK=1
      break
    fi
    sleep 3
  done
  echo "PUSH_OK=${PUSH_OK}" >> /tmp/status.log
fi

# terminateは必ず実行する(push成否に関わらず)
echo "attempting self-terminate: POD_ID=${RUNPOD_POD_ID}" >> /tmp/status.log

TERMINATE_RESULT="not_attempted"
if [ -n "${RUNPOD_API_KEY}" ] && [ -n "${RUNPOD_POD_ID}" ]; then
  cat > /tmp/terminate_query.json << EOF
{"query": "mutation { podTerminate(input: {podId: \"${RUNPOD_POD_ID}\"}) }"}
EOF
  TERMINATE_RESULT=$(curl -s -m 20 -X POST "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
    -H "Content-Type: application/json" \
    --data @/tmp/terminate_query.json 2>&1)
else
  TERMINATE_RESULT="missing_env_vars"
fi
echo "terminate_result=${TERMINATE_RESULT}" >> /tmp/status.log
