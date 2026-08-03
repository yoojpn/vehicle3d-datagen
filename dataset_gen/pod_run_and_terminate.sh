#!/bin/bash
set -e

NUM_SAMPLES="${NUM_SAMPLES:-10}"
WORKERS="${WORKERS:-1}"
OUT_DIR="/workspace/output"

cd /workspace/repo

echo "=== START: ${NUM_SAMPLES} samples ==="
python3 dataset_gen/run_batch.py \
  --start 0 --end "${NUM_SAMPLES}" \
  --workers "${WORKERS}" \
  --templates dataset_gen/structure_templates_300_v2.json \
  --ops_dir "${OUT_DIR}/ops" \
  --out "${OUT_DIR}/rendered"

echo "=== DONE, self-terminating ==="

if [ -n "${RUNPOD_API_KEY}" ] && [ -n "${RUNPOD_POD_ID}" ]; then
  curl -s -X POST "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "{\"query\": \"mutation { podTerminate(input: {podId: \\\"${RUNPOD_POD_ID}\\\"}) }\"}"
else
  echo "WARNING: cannot self-terminate, missing RUNPOD_API_KEY or RUNPOD_POD_ID"
fi
