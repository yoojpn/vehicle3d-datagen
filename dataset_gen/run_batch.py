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


def render_chunk(args):
    """1つのBlenderプロセス内で複数件をまとめて処理する(起動オーバーヘッド削減)"""
    chunk_id, items, out_dir = args
    manifest_lines = []
    pending = []
    for idx, ops_path in items:
        sample_out = os.path.join(out_dir, f"{idx:06d}")
        if os.path.exists(os.path.join(sample_out, "mesh.glb")):
            continue
        os.makedirs(sample_out, exist_ok=True)
        manifest_lines.append(f"{ops_path}\t{sample_out}")
        pending.append(idx)

    if not manifest_lines:
        return [(idx, "skipped_exists") for idx, _ in items]

    manifest_path = os.path.join(out_dir, f"_manifest_{chunk_id}.manifest")
    with open(manifest_path, "w") as f:
        f.write("\n".join(manifest_lines))

    try:
        # タイムアウトはチャンク内の件数に応じて確保(1件あたり最大60秒を見込む)
        # 実測(Persistent Data有効時)は1件あたり約0.5秒。余裕を見て1件2秒で計算し、
        # 上限は30分(1800秒)に固定する。以前は1件60秒で計算しており、
        # 大きなチャンクでは実質無限のタイムアウトになっていた。
        timeout_sec = min(1800, max(60, len(manifest_lines) * 2))
        result = subprocess.run(
            [BLENDER_BIN, "--background", "--python", BUILD_SCRIPT, "--", manifest_path],
            timeout=timeout_sec, capture_output=True, text=True
        )
        os.remove(manifest_path)
        done_count = result.stdout.count("DONE: ")
        results = []
        for idx in pending:
            results.append((idx, "ok" if done_count > 0 else f"fail: {result.stdout[-300:]} {result.stderr[-300:]}"))
        return results
    except subprocess.TimeoutExpired:
        return [(idx, "timeout") for idx in pending]
    except Exception as e:
        return [(idx, f"error: {e}") for idx in pending]


def chunked(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--chunk_size", type=int, default=20,
                         help="1つのBlenderプロセスで連続処理する件数(起動オーバーヘッド削減)")
    parser.add_argument("--templates", type=str, default="structure_templates_300.json")
    parser.add_argument("--ops_dir", type=str, default="output/ops")
    parser.add_argument("--out", type=str, default="output/rendered")
    args = parser.parse_args()

    os.makedirs(args.ops_dir, exist_ok=True)
    os.makedirs(args.out, exist_ok=True)

    templates = load_templates(args.templates)
    print(f"loaded {len(templates)} templates")

    # 操作列を先に全部生成(軽い処理なので逐次でOK)
    items = []
    for idx in range(args.start, args.end):
        ops_path = generate_ops(idx, templates, args.ops_dir)
        items.append((idx, ops_path))
    print(f"prepared {len(items)} operation sequences")

    chunks = list(chunked(items, args.chunk_size))
    tasks = [(i, chunk, args.out) for i, chunk in enumerate(chunks)]
    print(f"split into {len(tasks)} chunks of up to {args.chunk_size} items each")

    import time
    start_time = time.time()
    ok_count, fail_count = 0, 0
    total = len(items)
    done_items = 0
    with mp.Pool(args.workers) as pool:
        for chunk_results in pool.imap_unordered(render_chunk, tasks):
            for idx, status in chunk_results:
                if status == "ok" or status == "skipped_exists":
                    ok_count += 1
                else:
                    fail_count += 1
                    print(f"  [FAIL] idx={idx}: {status}", flush=True)
            done_items += len(chunk_results)
            elapsed = time.time() - start_time
            rate = done_items / elapsed if elapsed > 0 else 0
            remaining = (total - done_items) / rate if rate > 0 else float("inf")
            print(
                f"progress: {done_items}/{total} ({done_items/total*100:.1f}%)  "
                f"ok={ok_count} fail={fail_count}  "
                f"elapsed={elapsed:.0f}s  eta={remaining:.0f}s",
                flush=True
            )

    print(f"DONE. ok={ok_count} fail={fail_count} total={total}")


if __name__ == "__main__":
    main()
