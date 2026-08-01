#!/bin/bash
set -e

# ===== 設定 =====
NUM_SAMPLES="${NUM_SAMPLES:-100000}"
WORKERS="${WORKERS:-8}"
OUT_DIR="/workspace/output"
SPHERON_API_KEY="${SPHERON_API_KEY}"
SPHERON_INSTANCE_ID="${SPHERON_INSTANCE_ID}"

echo "=== 環境準備 ==="
apt-get update -qq && apt-get install -y -qq wget xz-utils git python3-pip > /dev/null
wget -q https://download.blender.org/release/Blender4.2/blender-4.2.5-linux-x64.tar.xz -O /tmp/blender.tar.xz
tar xf /tmp/blender.tar.xz -C /opt/
export BLENDER_BIN="/opt/blender-4.2.5-linux-x64/blender"

git clone https://github.com/yoojpn/vehicle3d-datagen.git /workspace/repo
cd /workspace/repo
pip3 install -q trimesh numpy

echo "=== データ生成開始: ${NUM_SAMPLES}件, workers=${WORKERS} ==="
python3 dataset_gen/run_batch.py \
  --start 0 --end "${NUM_SAMPLES}" \
  --workers "${WORKERS}" \
  --templates dataset_gen/structure_templates_300_v2.json \
  --ops_dir "${OUT_DIR}/ops" \
  --out "${OUT_DIR}/rendered" \
  2>&1 | tee "${OUT_DIR}/generation.log"

echo "=== データ生成終了 ==="

# ===== 結果を退避(必須:自己終了するとVM内のデータは消えるため) =====
# Spheronのボリューム機能、またはS3等、外部ストレージへの退避をここに追加する
# 例:
# pip3 install -q awscli
# aws s3 sync ${OUT_DIR} s3://your-bucket/dataset_run_$(date +%s)/
echo "警告: 外部ストレージへの退避スクリプトが未設定です。実行前に必ず設定してください。"

echo "=== 自己終了処理を開始 ==="

if [ -z "${SPHERON_API_KEY}" ] || [ -z "${SPHERON_INSTANCE_ID}" ]; then
  echo "WARNING: SPHERON_API_KEY または SPHERON_INSTANCE_ID が未設定です。自己終了できません。"
  exit 1
fi

curl -s -X DELETE "https://app.spheron.ai/api/deployments/${SPHERON_INSTANCE_ID}" \
  -H "Authorization: Bearer ${SPHERON_API_KEY}"

echo "=== 終了リクエスト送信完了 ==="
