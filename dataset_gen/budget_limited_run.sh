#!/bin/bash
# 指定した時間(秒)が来たら、その時点までの進捗を保存して終了する。
# 予算(GPU時間)を超えないことを最優先にする設計。
#
# 重要: このスクリプト自体のself-terminateとは別に、
# Runpodのdocker起動コマンド側で「nohup sleep TIME; runpodctl stop pod $RUNPOD_POD_ID」を
# 並行実行する二重の安全装置を必ず併用すること。
# (このスクリプト内の処理が予期せず固まっても、確実に時間切れで停止するため)
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

# ここで一度、途中経過ログだけ先にpushしておく(Release処理で何が起きても記録が残るように)
if [ -n "${GITHUB_TOKEN}" ]; then
  cp /tmp/status.log "/workspace/repo/${LOG_FILE}"
  git config user.email "pod@local"
  git config user.name "pod-runner"
  git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/yoojpn/vehicle3d-datagen.git"
  git add "${LOG_FILE}"
  timeout 15 git commit -m "budget run ${POD_TAG} (pre-release)"
  timeout 20 git pull --no-edit origin main
  timeout 20 git push origin main
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
