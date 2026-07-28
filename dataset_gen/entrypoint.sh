#!/bin/bash
set -e

# ===== 設定 =====
NUM_SAMPLES="${NUM_SAMPLES:-10000}"
WORKERS="${WORKERS:-8}"
OUT_DIR="/workspace/output"

echo "=== データ生成開始: ${NUM_SAMPLES}件, workers=${WORKERS} ==="
cd /workspace

python3 dataset_gen/run_batch.py \
  --start 0 --end "${NUM_SAMPLES}" \
  --workers "${WORKERS}" \
  --templates dataset_gen/structure_templates_300_v2.json \
  --ops_dir "${OUT_DIR}/ops" \
  --out "${OUT_DIR}/rendered" \
  2>&1 | tee "${OUT_DIR}/generation.log"

GEN_EXIT_CODE=$?
echo "=== データ生成終了(exit code: ${GEN_EXIT_CODE}) ==="

# ===== 結果をまとめて外部ストレージへ退避(任意、S3等を使うなら here) =====
# 例: aws s3 sync ${OUT_DIR} s3://your-bucket/dataset_run_$(date +%s)/
# ここは各自のストレージ設定に合わせて追記してください。
# 退避を入れずに自己終了すると、データが失われるので必ず設定すること。

echo "=== 自己終了処理を開始 ==="

# RunpodのポッドIDは環境変数RUNPOD_POD_IDに自動で入っている
if [ -z "${RUNPOD_POD_ID}" ]; then
  echo "WARNING: RUNPOD_POD_ID が見つかりません。自己終了できません。手動で削除してください。"
  exit 1
fi

if [ -z "${RUNPOD_API_KEY}" ]; then
  echo "WARNING: RUNPOD_API_KEY が環境変数に設定されていません。自己終了できません。"
  echo "ポッド作成時に env に RUNPOD_API_KEY を渡してください。"
  exit 1
fi

curl -s -X POST "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"mutation { podTerminate(input: {podId: \\\"${RUNPOD_POD_ID}\\\"}) }\"}"

echo "=== Terminateリクエスト送信完了 ==="
