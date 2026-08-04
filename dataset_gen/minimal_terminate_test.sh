#!/bin/bash
echo "=== MINIMAL TERMINATE TEST ===" > /tmp/status.log
echo "RUNPOD_POD_ID=${RUNPOD_POD_ID}" >> /tmp/status.log
echo "RUNPOD_API_KEY_len=${#RUNPOD_API_KEY}" >> /tmp/status.log

# まずネットワーク到達性そのものを確認
echo "--- testing network reachability ---" >> /tmp/status.log
curl -s -m 10 -o /dev/null -w "http_code=%{http_code}\n" https://api.runpod.io/graphql >> /tmp/status.log 2>&1
echo "curl_exit_code=$?" >> /tmp/status.log

echo "--- attempting terminate ---" >> /tmp/status.log
cat > /tmp/terminate_query.json << EOF
{"query": "mutation { podTerminate(input: {podId: \"${RUNPOD_POD_ID}\"}) }"}
EOF
cat /tmp/terminate_query.json >> /tmp/status.log

RESULT=$(curl -s -m 15 -X POST "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
  -H "Content-Type: application/json" \
  --data @/tmp/terminate_query.json 2>&1)
echo "curl_exit_code=$?" >> /tmp/status.log
echo "result=${RESULT}" >> /tmp/status.log

echo "--- pushing final log ---" >> /tmp/status.log
cd /workspace/repo
cp /tmp/status.log /workspace/repo/pod_status.log
git config user.email "pod@local"
git config user.name "pod-runner"
git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/yoojpn/vehicle3d-datagen.git"
git add pod_status.log
git commit -m "minimal terminate test $(date +%s)"
timeout 20 git push origin main
echo "push_exit_code=$?"
