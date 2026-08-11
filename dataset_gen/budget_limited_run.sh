#!/bin/bash
# 前回までの失敗(件数を大きくしすぎ、zip化・アップロードの後処理時間を
# 見積もらないままtimeoutを設定していたため、データが失われた)を踏まえ、
# 件数を最初から小さく固定し、後処理の時間まで含めて確実に収まる設計にする。
NUM_SAMPLES="${NUM_SAMPLES:-3000}"  # 1回のポッドで処理する固定件数(後処理時間を確実に見積もれる規模)
RENDER_TIMEOUT_SEC="${RENDER_TIMEOUT_SEC:-5400}"  # レンダリング自体の上限(90分、3000件なら十分な余裕)
START_IDX="${START_IDX:-0}"
WORKERS="${WORKERS:-1}"
GITHUB_TOKEN="${GITHUB_TOKEN}"
OUT_DIR="/workspace/output_budget"
POD_TAG="${RUNPOD_POD_ID:-unknown_$(date +%s)}"
LOG_FILE="pod_budget_${POD_TAG}.log"

cd /workspace/repo

echo "=== FIXED-COUNT RUN: ${NUM_SAMPLES} samples, render_timeout=${RENDER_TIMEOUT_SEC}s ===" > /tmp/status.log
echo "start=$(date +%s)" >> /tmp/status.log

# 件数を固定し、レンダリング部分にだけtimeoutをかける(後処理はtimeoutの外)
timeout "${RENDER_TIMEOUT_SEC}" python3 dataset_gen/run_batch.py \
  --start "${START_IDX}" --end "$((START_IDX + NUM_SAMPLES))" \
  --workers "${WORKERS}" \
  --templates dataset_gen/structure_templates_300_v2.json \
  --ops_dir "${OUT_DIR}/ops" \
  --out "${OUT_DIR}/rendered" >> /tmp/status.log 2>&1

echo "=== TIME LIMIT REACHED OR RUN COMPLETED ===" >> /tmp/status.log
echo "end=$(date +%s)" >> /tmp/status.log

# 複数ポッド並列実行時、git pushが同時に競合するのを避けるため、
# 後処理開始前にランダムな遅延(0〜60秒)を入れる
STAGGER=$((RANDOM % 60))
echo "stagger_delay=${STAGGER}s" >> /tmp/status.log
sleep "${STAGGER}"

# 完了した件数を数える
COMPLETED=$(find "${OUT_DIR}/rendered" -name "mesh.glb" 2>/dev/null | wc -l)
echo "completed_count=${COMPLETED}" >> /tmp/status.log

# ここで一度、途中経過ログだけ先にpushしておく(Release処理で何が起きても記録が残るように)
if [ -n "${GITHUB_TOKEN}" ]; then
  cp /tmp/status.log "/workspace/repo/${LOG_FILE}"
  git config user.email "pod@local"
  git config user.name "pod-runner"
  git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/yoojpn/vehicle3d-datagen.git"
  git add "${LOG_FILE}"
  for attempt in 1 2 3; do
    timeout 15 git commit -m "budget run ${POD_TAG} (pre-release)"
    timeout 20 git pull --no-edit origin main
    if timeout 20 git push origin main; then
      break
    fi
    sleep $((RANDOM % 15 + 5))
  done
fi

# 生成物本体(画像・GLB)をzip化してGitHub Releaseとしてアップロードする
DATASET_ZIP="/tmp/dataset_${POD_TAG}.zip"
echo "zipping dataset..." >> /tmp/status.log
cd "${OUT_DIR}" && zip -qr "${DATASET_ZIP}" ops rendered 2>>/tmp/status.log
echo "zip_exit_code=$?" >> /tmp/status.log
ls -la "${DATASET_ZIP}" >> /tmp/status.log 2>&1

if [ -n "${GITHUB_TOKEN}" ]; then
  RELEASE_TAG="dataset-${POD_TAG}"
  CREATE_RESP=$(curl -s -m 30 -X POST \
    -H "Authorization: token ${GITHUB_TOKEN}" \
    -H "Content-Type: application/json" \
    "https://api.github.com/repos/yoojpn/vehicle3d-datagen/releases" \
    -d "{\"tag_name\": \"${RELEASE_TAG}\", \"name\": \"Dataset ${POD_TAG}\", \"body\": \"completed_count=${COMPLETED}\"}")
  echo "create_release_response: ${CREATE_RESP}" >> /tmp/status.log

  UPLOAD_URL=$(echo "$CREATE_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('upload_url','').split('{')[0])" 2>>/tmp/status.log)
  echo "release_upload_url=[${UPLOAD_URL}]" >> /tmp/status.log

  if [ -n "${UPLOAD_URL}" ]; then
    UPLOAD_RESP=$(curl -s -m 120 -w "HTTPSTATUS:%{http_code}" -X POST \
      -H "Authorization: token ${GITHUB_TOKEN}" \
      -H "Content-Type: application/zip" \
      --data-binary "@${DATASET_ZIP}" \
      "${UPLOAD_URL}?name=dataset_${POD_TAG}.zip" 2>>/tmp/status.log)
    echo "upload_response: ${UPLOAD_RESP}" >> /tmp/status.log
  else
    echo "upload_confirmed=0_no_upload_url" >> /tmp/status.log
  fi
fi

if [ -n "${GITHUB_TOKEN}" ]; then
  cp /tmp/status.log "/workspace/repo/${LOG_FILE}"
  git config user.email "pod@local"
  git config user.name "pod-runner"
  git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/yoojpn/vehicle3d-datagen.git"
  git add "${LOG_FILE}"
  timeout 15 git commit -m "budget run ${POD_TAG}"
  timeout 20 git pull --no-edit origin main
  timeout 20 git push origin main

  # push成功を実際にGitHub API経由で確認する(確認できるまで最大3回リトライ)
  PUSH_CONFIRMED=0
  for check in 1 2 3; do
    sleep 5
    RESP=$(curl -s -m 15 -H "Authorization: token ${GITHUB_TOKEN}" \
      "https://api.github.com/repos/yoojpn/vehicle3d-datagen/contents/${LOG_FILE}")
    if echo "$RESP" | grep -q '"content"'; then
      PUSH_CONFIRMED=1
      break
    fi
  done
  echo "push_confirmed=${PUSH_CONFIRMED}" >> /tmp/status.log
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
