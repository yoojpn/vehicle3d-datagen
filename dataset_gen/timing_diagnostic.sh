#!/bin/bash
# コールドスタート・環境準備段階の時間だけを計測する(GPU/Blenderレンダリングは実行しない)
POD_TAG="${RUNPOD_POD_ID:-unknown_$(date +%s)}"
LOG_FILE="pod_timing_diag_${POD_TAG}.log"

echo "=== TIMING DIAGNOSTIC (no blender render) ===" > /tmp/status.log
echo "start_time=$(date +%s)" >> /tmp/status.log

echo "checking repo state..." >> /tmp/status.log
ls -la /workspace/repo >> /tmp/status.log 2>&1

echo "python3 check:" >> /tmp/status.log
python3 --version >> /tmp/status.log 2>&1

echo "blender check:" >> /tmp/status.log
/opt/blender-5.2.0-linux-x64/blender --version >> /tmp/status.log 2>&1

echo "nvidia-smi check:" >> /tmp/status.log
nvidia-smi >> /tmp/status.log 2>&1

echo "end_time=$(date +%s)" >> /tmp/status.log

cd /workspace/repo
if [ -n "${GITHUB_TOKEN}" ]; then
  cp /tmp/status.log "/workspace/repo/${LOG_FILE}"
  git config user.email "pod@local"
  git config user.name "pod-runner"
  git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/yoojpn/vehicle3d-datagen.git"
  git add "${LOG_FILE}"
  timeout 15 git commit -m "timing diag ${POD_TAG}"
  timeout 20 git pull --no-edit origin main
  timeout 20 git push origin main
fi

if [ -n "${RUNPOD_API_KEY}" ] && [ -n "${RUNPOD_POD_ID}" ]; then
  cat > /tmp/terminate_query.json << EOF
{"query": "mutation { podTerminate(input: {podId: \"${RUNPOD_POD_ID}\"}) }"}
EOF
  curl -s -m 20 -X POST "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
    -H "Content-Type: application/json" \
    --data @/tmp/terminate_query.json
fi
