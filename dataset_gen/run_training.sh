#!/bin/bash
# データ準備(展開のみ、コピーなし)→学習まで通しで実行する。
POD_TAG="${RUNPOD_POD_ID:-unknown_$(date +%s)}"
LOG_FILE="pod_train_${POD_TAG}.log"
GITHUB_TOKEN="${GITHUB_TOKEN}"
EPOCHS="${EPOCHS:-30}"

cd /workspace/repo

echo "=== TRAINING RUN START ===" > /tmp/status.log
echo "start=$(date +%s)" >> /tmp/status.log

bash dataset_gen/prepare_dataset_dirs.sh >> /tmp/status.log 2>&1
echo "=== DATASET PREPARED ===" >> /tmp/status.log

cd dataset_gen
python3 train_sanity_check.py \
  --dataset_root /workspace/dataset_root \
  --epochs "${EPOCHS}" --batch_size 16 --val_ratio 0.1 \
  --out_dir /workspace/train_output >> /tmp/status.log 2>&1

echo "=== TRAINING DONE ===" >> /tmp/status.log
echo "end=$(date +%s)" >> /tmp/status.log

# 学習結果(ログ+モデル)をzip化してReleaseとしてアップロード
cd /workspace
DATASET_ZIP="/tmp/train_result_${POD_TAG}.zip"
zip -qr "${DATASET_ZIP}" train_output 2>>/tmp/status.log
echo "zip_exit_code=$?" >> /tmp/status.log

if [ -n "${GITHUB_TOKEN}" ]; then
  cp /tmp/status.log "/workspace/repo/${LOG_FILE}"
  cd /workspace/repo
  git config user.email "pod@local"
  git config user.name "pod-runner"
  git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/yoojpn/vehicle3d-datagen.git"
  git add "${LOG_FILE}"
  for attempt in 1 2 3; do
    timeout 15 git commit -m "training run ${POD_TAG}"
    timeout 20 git pull --no-edit origin main
    if timeout 20 git push origin main; then
      break
    fi
    sleep $((RANDOM % 15 + 5))
  done

  RELEASE_TAG="training-${POD_TAG}"
  CREATE_RESP=$(curl -s -m 30 -X POST \
    -H "Authorization: token ${GITHUB_TOKEN}" \
    -H "Content-Type: application/json" \
    "https://api.github.com/repos/yoojpn/vehicle3d-datagen/releases" \
    -d "{\"tag_name\": \"${RELEASE_TAG}\", \"name\": \"Training ${POD_TAG}\", \"body\": \"training run\"}")
  UPLOAD_URL=$(echo "$CREATE_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('upload_url','').split('{')[0])" 2>/dev/null)

  if [ -n "${UPLOAD_URL}" ]; then
    curl -s -m 300 -X POST \
      -H "Authorization: token ${GITHUB_TOKEN}" \
      -H "Content-Type: application/zip" \
      --data-binary "@${DATASET_ZIP}" \
      "${UPLOAD_URL}?name=train_result_${POD_TAG}.zip"
  fi
fi

# terminate
if [ -n "${RUNPOD_API_KEY}" ] && [ -n "${RUNPOD_POD_ID}" ]; then
  cat > /tmp/terminate_query.json << EOF
{"query": "mutation { podTerminate(input: {podId: \"${RUNPOD_POD_ID}\"}) }"}
EOF
  curl -s -m 20 -X POST "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
    -H "Content-Type: application/json" \
    --data @/tmp/terminate_query.json
fi
