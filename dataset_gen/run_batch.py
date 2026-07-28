"""
Runpod等のマルチコア環境向け、並列データ生成ランナー。

使い方:
  python3 run_batch.py --start 0 --end 10000 --workers 16 \
      --templates structure_templates_300.json --out output/

処理内容:
  1. 操作列を(存在しなければ)生成
  2. Blender(headless)をサブプロセスで並列起動し、レンダリング+GLB出力
  3. 進捗をログに記録、失敗したサンプルはスキップして続行
"""
import argparse
import json
import os
import random
import subprocess
import multiprocessing as mp
from op_sampler_v5 import instantiate_template, load_templates

BLENDER_BIN = os.environ.get("BLENDER_BIN", "blender")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BUILD_SCRIPT = os.path.join(SCRIPT_DIR, "build_and_render.py")


def generate_ops(idx, templates, ops_dir, seed_base=0):
    ops_path = os.path.join(ops_dir, f"ops_{idx:06d}.json")
    if os.path.exists(ops_path):
        return ops_path
    t = random.choice(templates)
    result = instantiate_template(t, seed=None)
    result["sample_id"] = idx
    with open(ops_path, "w") as f:
        json.dump(result, f, ensure_ascii=False)
    return ops_path


def render_one(args):
    idx, ops_path, out_dir = args
    sample_out = os.path.join(out_dir, f"{idx:06d}")
    os.makedirs(sample_out, exist_ok=True)
    if os.path.exists(os.path.join(sample_out, "mesh.glb")):
        return idx, "skipped_exists"
    try:
        result = subprocess.run(
            [BLENDER_BIN, "--background", "--python", BUILD_SCRIPT, "--", ops_path, sample_out],
            timeout=120, capture_output=True, text=True
        )
        if "DONE" in result.stdout:
            return idx, "ok"
        else:
            return idx, f"fail: {result.stdout[-300:]} {result.stderr[-300:]}"
    except subprocess.TimeoutExpired:
        return idx, "timeout"
    except Exception as e:
        return idx, f"error: {e}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--templates", type=str, default="structure_templates_300.json")
    parser.add_argument("--ops_dir", type=str, default="output/ops")
    parser.add_argument("--out", type=str, default="output/rendered")
    args = parser.parse_args()

    os.makedirs(args.ops_dir, exist_ok=True)
    os.makedirs(args.out, exist_ok=True)

    templates = load_templates(args.templates)
    print(f"loaded {len(templates)} templates")

    # 操作列を先に全部生成(軽い処理なので逐次でOK)
    tasks = []
    for idx in range(args.start, args.end):
        ops_path = generate_ops(idx, templates, args.ops_dir)
        tasks.append((idx, ops_path, args.out))
    print(f"prepared {len(tasks)} operation sequences")

    # レンダリングは重いので並列化
    ok_count, fail_count = 0, 0
    with mp.Pool(args.workers) as pool:
        for i, (idx, status) in enumerate(pool.imap_unordered(render_one, tasks)):
            if status == "ok" or status == "skipped_exists":
                ok_count += 1
            else:
                fail_count += 1
                print(f"  [FAIL] idx={idx}: {status}")
            if (i + 1) % 100 == 0:
                print(f"progress: {i+1}/{len(tasks)}  ok={ok_count} fail={fail_count}")

    print(f"DONE. ok={ok_count} fail={fail_count} total={len(tasks)}")


if __name__ == "__main__":
    main()
