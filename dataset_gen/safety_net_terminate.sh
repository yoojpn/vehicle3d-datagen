#!/bin/bash
# メインの処理(budget_limited_run.sh)とは独立して動く安全装置。
# 指定時間が来たら、メイン処理の状態に関わらず強制的にポッドを終了する。
SAFETY_TIME_SEC="${SAFETY_TIME_SEC:-33000}"  # メインのTIME_LIMIT_SECより少し長めに設定

sleep "${SAFETY_TIME_SEC}"

if [ -n "${RUNPOD_API_KEY}" ] && [ -n "${RUNPOD_POD_ID}" ]; then
  cat > /tmp/safety_terminate_query.json << EOF
{"query": "mutation { podTerminate(input: {podId: \"${RUNPOD_POD_ID}\"}) }"}
EOF
  curl -s -m 20 -X POST "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
    -H "Content-Type: application/json" \
    --data @/tmp/safety_terminate_query.json
fi
