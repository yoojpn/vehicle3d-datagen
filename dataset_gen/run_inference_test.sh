#!/bin/bash
# 学習済みモデルをダウンロードし、テスト画像に対して推論し、
# 生成された操作列を実際にBlenderで組み立ててレンダリングする(推論の質を目視確認するため)。
POD_TAG="${RUNPOD_POD_ID:-unknown_$(date +%s)}"
LOG_FILE="pod_inference_${POD_TAG}.log"
GITHUB_TOKEN="${GITHUB_TOKEN}"
MODEL_RELEASE_URL="${MODEL_RELEASE_URL}"
TEST_RELEASE_URL="${TEST_RELEASE_URL}"

cd /workspace/repo

echo "=== INFERENCE TEST START ===" > /tmp/status.log

# 学習済みモデルをダウンロード
wget -q "${MODEL_RELEASE_URL}" -O /tmp/train_result.zip
unzip -oq /tmp/train_result.zip -d /tmp/train_result
echo "model downloaded" >> /tmp/status.log

# テスト用データ(1件、学習に使っていない可能性が高い最新のRelease)をダウンロード
wget -q "${TEST_RELEASE_URL}" -O /tmp/test_data.zip
unzip -oq /tmp/test_data.zip -d /tmp/test_data
echo "test data downloaded" >> /tmp/status.log

# テスト画像を1枚選ぶ(最初に見つかったview_00.png)
TEST_IMAGE=$(find /tmp/test_data -name "view_00.png" | head -1)
echo "test_image=${TEST_IMAGE}" >> /tmp/status.log

cd dataset_gen
python3 infer.py \
  --model_path /tmp/train_result/train_output/model_sanity_check.pt \
  --image_path "${TEST_IMAGE}" \
  --out /tmp/generated.txt >> /tmp/status.log 2>&1

echo "=== INFERENCE DONE ===" >> /tmp/status.log
cat /tmp/generated.txt >> /tmp/status.log

# 生成された操作列を実際にBlenderで組み立ててレンダリング
GENERATED_OPS="/tmp/generated_ops.json"
if [ -f "${GENERATED_OPS}" ]; then
  mkdir -p /tmp/inference_render
  /opt/blender-5.2.0-linux-x64/blender --background --python build_and_render.py -- "${GENERATED_OPS}" /tmp/inference_render >> /tmp/status.log 2>&1
  echo "=== RENDER DONE ===" >> /tmp/status.log
fi

cd /workspace
# 結果(元画像、生成された操作列、レンダリング結果)をzip化してアップロード
mkdir -p /tmp/inference_package
cp "${TEST_IMAGE}" /tmp/inference_package/original_input.png 2>/dev/null
cp /tmp/generated.txt /tmp/inference_package/ 2>/dev/null
cp "${GENERATED_OPS}" /tmp/inference_package/ 2>/dev/null
cp -r /tmp/inference_render /tmp/inference_package/rendered_result 2>/dev/null

cd /tmp
zip -qr "/tmp/inference_result_${POD_TAG}.zip" inference_package
echo "zip_exit_code=$?" >> /tmp/status.log

if [ -n "${GITHUB_TOKEN}" ]; then
  cp /tmp/status.log "/workspace/repo/${LOG_FILE}"
  cd /workspace/repo
  git config user.email "pod@local"
  git config user.name "pod-runner"
  git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/yoojpn/vehicle3d-datagen.git"
  git add "${LOG_FILE}"
  for attempt in 1 2 3; do
    timeout 15 git commit -m "inference test ${POD_TAG}"
    timeout 20 git pull --no-edit origin main
    if timeout 20 git push origin main; then
      break
    fi
    sleep $((RANDOM % 15 + 5))
  done

  RELEASE_TAG="inference-${POD_TAG}"
  CREATE_RESP=$(curl -s -m 30 -X POST \
    -H "Authorization: token ${GITHUB_TOKEN}" \
    -H "Content-Type: application/json" \
    "https://api.github.com/repos/yoojpn/vehicle3d-datagen/releases" \
    -d "{\"tag_name\": \"${RELEASE_TAG}\", \"name\": \"Inference ${POD_TAG}\", \"body\": \"inference test\"}")
  UPLOAD_URL=$(echo "$CREATE_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('upload_url','').split('{')[0])" 2>/dev/null)

  if [ -n "${UPLOAD_URL}" ]; then
    curl -s -m 300 -X POST \
      -H "Authorization: token ${GITHUB_TOKEN}" \
      -H "Content-Type: application/zip" \
      --data-binary "@/tmp/inference_result_${POD_TAG}.zip" \
      "${UPLOAD_URL}?name=inference_result_${POD_TAG}.zip"
  fi
fi

if [ -n "${RUNPOD_API_KEY}" ] && [ -n "${RUNPOD_POD_ID}" ]; then
  cat > /tmp/terminate_query.json << EOF
{"query": "mutation { podTerminate(input: {podId: \"${RUNPOD_POD_ID}\"}) }"}
EOF
  curl -s -m 20 -X POST "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
    -H "Content-Type: application/json" \
    --data @/tmp/terminate_query.json
fi
