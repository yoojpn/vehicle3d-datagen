"""
司令塔スクリプト。安いCPU pod上で動かす。
複数のGPU podを起動し、進捗を監視し、完了・異常時に確実にterminateする。

Runpod APIキーとGitHubトークンは環境変数で渡す。
"""
import os
import time
import json
import subprocess
import urllib.request

RUNPOD_API_KEY = os.environ["RUNPOD_API_KEY"]
GPU_TYPE = os.environ.get("GPU_TYPE", "NVIDIA GeForce RTX 3090")
NUM_WORKERS = int(os.environ.get("NUM_WORKERS", "3"))
ITEMS_PER_WORKER = int(os.environ.get("ITEMS_PER_WORKER", "10000"))
MAX_RUNTIME_SEC = int(os.environ.get("MAX_RUNTIME_SEC", "36000"))  # 各GPU podの上限(10時間)
IMAGE_NAME = "ghcr.io/yoojpn/vehicle3d-datagen-serverless:latest"
CONTAINER_REGISTRY_AUTH_ID = "cms45vowo0082e21kxx2zvxhw"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")


def runpod_graphql(query):
    req = urllib.request.Request(
        f"https://api.runpod.io/graphql?api_key={RUNPOD_API_KEY}",
        data=json.dumps({"query": query}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def create_gpu_pod(idx, start_idx, num_items):
    name = f"vehicle3d-orch-{idx}"
    query = f'''
mutation {{
  podFindAndDeployOnDemand(input: {{
    cloudType: COMMUNITY, gpuCount: 1, volumeInGb: 0, containerDiskInGb: 15,
    gpuTypeId: "{GPU_TYPE}",
    name: "{name}",
    imageName: "{IMAGE_NAME}",
    containerRegistryAuthId: "{CONTAINER_REGISTRY_AUTH_ID}",
    env: [
      {{key: "GITHUB_TOKEN", value: "{GITHUB_TOKEN}"}},
      {{key: "NUM_SAMPLES", value: "{num_items}"}},
      {{key: "START_IDX", value: "{start_idx}"}},
      {{key: "WORKERS", value: "1"}}
    ],
    dockerArgs: "/workspace/repo/dataset_gen/isolated_render_test.sh",
    ports: "22/tcp"
  }}) {{ id }}
}}
'''
    result = runpod_graphql(query)
    if "errors" in result:
        print(f"worker {idx}: failed to create - {result['errors']}")
        return None
    pod_id = result["data"]["podFindAndDeployOnDemand"]["id"]
    print(f"worker {idx}: created pod {pod_id}")
    return pod_id


def get_pod_status(pod_id):
    query = f'query {{ pod(input: {{podId: "{pod_id}"}}) {{ id desiredStatus }} }}'
    result = runpod_graphql(query)
    if "data" in result and result["data"]["pod"]:
        return result["data"]["pod"]["desiredStatus"]
    return None


def terminate_pod(pod_id):
    query = f'mutation {{ podTerminate(input: {{podId: "{pod_id}"}}) }}'
    runpod_graphql(query)
    print(f"terminated pod {pod_id}")


def check_log_exists(pod_id):
    # GitHub上に pod_isolated_<pod_id>.log があるかチェック
    url = f"https://api.github.com/repos/yoojpn/vehicle3d-datagen/contents/pod_isolated_{pod_id}.log"
    req = urllib.request.Request(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception:
        return False


def main():
    workers = []
    for i in range(NUM_WORKERS):
        start_idx = i * ITEMS_PER_WORKER
        pod_id = create_gpu_pod(i, start_idx, ITEMS_PER_WORKER)
        if pod_id:
            workers.append({"idx": i, "pod_id": pod_id, "start_time": time.time(), "done": False})
        time.sleep(5)

    print(f"started {len(workers)} workers, monitoring...")

    while True:
        all_done = True
        for w in workers:
            if w["done"]:
                continue
            all_done = False
            elapsed = time.time() - w["start_time"]

            # 完了ログが出ているか確認
            if check_log_exists(w["pod_id"]):
                print(f"worker {w['idx']} ({w['pod_id']}): log found, terminating")
                terminate_pod(w["pod_id"])
                w["done"] = True
                continue

            # タイムアウトを超えたら強制終了
            if elapsed > MAX_RUNTIME_SEC:
                print(f"worker {w['idx']} ({w['pod_id']}): timeout exceeded, force terminating")
                terminate_pod(w["pod_id"])
                w["done"] = True
                continue

            status = get_pod_status(w["pod_id"])
            print(f"worker {w['idx']} ({w['pod_id']}): elapsed={elapsed:.0f}s status={status}")

        if all_done:
            print("all workers done")
            break

        time.sleep(120)


if __name__ == "__main__":
    main()
