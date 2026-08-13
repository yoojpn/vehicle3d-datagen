#!/bin/bash
POD_TAG="${RUNPOD_POD_ID:-unknown_$(date +%s)}"
LOG_FILE="pod_extract_${POD_TAG}.log"
GITHUB_TOKEN="${GITHUB_TOKEN}"
TARGET_COUNT="${TARGET_COUNT:-2000}"
OFFSET="${OFFSET:-0}"

cd /workspace/repo
echo "=== TEMPLATE EXTRACTION START ===" > /tmp/status.log
echo "start=$(date +%s)" >> /tmp/status.log

pip install --break-system-packages --quiet objaverse trimesh numpy >> /tmp/status.log 2>&1

cd dataset_gen
python3 extract_templates.py \
  --target_count "${TARGET_COUNT}" \
  --offset "${OFFSET}" \
  --existing_templates structure_templates_300_v2.json \
  --out /tmp/structure_templates_expanded.json >> /tmp/status.log 2>&1

echo "=== EXTRACTION DONE ===" >> /tmp/status.log
echo "end=$(date +%s)" >> /tmp/status.log

if [ -n "${GITHUB_TOKEN}" ] && [ -f /tmp/structure_templates_expanded.json ]; then
  cp /tmp/structure_templates_expanded.json /workspace/repo/dataset_gen/structure_templates_300_v2.json
  cp /tmp/status.log "/workspace/repo/${LOG_FILE}"
  cd /workspace/repo
  git config user.email "pod@local"
  git config user.name "pod-runner"
  git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/yoojpn/vehicle3d-datagen.git"
  git add "${LOG_FILE}" dataset_gen/structure_templates_300_v2.json
  for attempt in 1 2 3; do
    timeout 15 git commit -m "expand templates ${POD_TAG}"
    timeout 20 git pull --no-edit origin main
    if timeout 20 git push origin main; then
      break
    fi
    sleep $((RANDOM % 15 + 5))
  done
fi

if [ -n "${RUNPOD_API_KEY}" ] && [ -n "${RUNPOD_POD_ID}" ]; then
  cat > /tmp/terminate_query.json << EOF
{"query": "mutation { podTerminate(input: {podId: \"${RUNPOD_POD_ID}\"}) }"}
EOF
  curl -s -m 20 -X POST "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
    -H "Content-Type: application/json" \
    --data @/tmp/terminate_query.json
fi
