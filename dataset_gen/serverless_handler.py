"""
Runpod Serverless用ハンドラー。
1回の呼び出しで1件(または指定チャンク分)の操作列生成+レンダリングを行う。

Runpod Serverlessはこのファイルをコンテナのエントリポイントとして起動し、
キューに積まれたジョブを自動的に並列ワーカーに分配する。
"""
import runpod
import subprocess
import os
import json

BLENDER_BIN = "/opt/blender-4.2.5-linux-x64/blender"
REPO_DIR = "/workspace/repo"


def handler(job):
    job_input = job["input"]

    # デバッグモード: GPU認識状況だけを確認する
    if job_input.get("debug_gpu"):
        nvidia_smi = subprocess.run(["nvidia-smi"], capture_output=True, text=True)
        blender_gpu_check = subprocess.run(
            [BLENDER_BIN, "--background", "--python-expr",
             "import bpy; prefs = bpy.context.preferences.addons['cycles'].preferences; "
             "prefs.compute_device_type = 'CUDA'; prefs.get_devices(); "
             "print('DEVICES:', [(d.name, d.type, d.use) for d in prefs.devices])"],
            capture_output=True, text=True, timeout=60
        )
        return {
            "nvidia_smi_stdout": nvidia_smi.stdout,
            "nvidia_smi_stderr": nvidia_smi.stderr,
            "blender_stdout": blender_gpu_check.stdout,
            "blender_stderr": blender_gpu_check.stderr,
        }

    # デバッグモード2: 1件のレンダリングを詳細ログ付きで実行
    if job_input.get("debug_single_render"):
        import time
        t0 = time.time()
        os.environ["BLENDER_BIN"] = BLENDER_BIN
        ops_gen = subprocess.run(
            ["python3", "-c",
             f"import sys; sys.path.insert(0,'{REPO_DIR}/dataset_gen'); "
             "from op_sampler_v5 import load_templates, instantiate_template; "
             "import json; "
             f"t = load_templates('{REPO_DIR}/dataset_gen/structure_templates_300_v2.json'); "
             "r = instantiate_template(t[5], seed=1); "
             "json.dump(r, open('/tmp/debug_ops.json','w'))"],
            capture_output=True, text=True, timeout=30
        )
        t1 = time.time()
        render = subprocess.run(
            [BLENDER_BIN, "--background", "--python", f"{REPO_DIR}/dataset_gen/build_and_render.py",
             "--", "/tmp/debug_ops.json", "/tmp/debug_out"],
            capture_output=True, text=True, timeout=120
        )
        t2 = time.time()
        return {
            "ops_gen_time": t1 - t0,
            "ops_gen_stderr": ops_gen.stderr[-500:],
            "render_time": t2 - t1,
            "render_stdout": render.stdout[-2000:],
            "render_stderr": render.stderr[-1000:],
            "render_returncode": render.returncode,
        }

    start_idx = job_input.get("start", 0)
    end_idx = job_input.get("end", start_idx + 20)
    templates_path = job_input.get(
        "templates", f"{REPO_DIR}/dataset_gen/structure_templates_300_v2.json"
    )
    out_dir = job_input.get("out_dir", "/workspace/output")

    os.environ["BLENDER_BIN"] = BLENDER_BIN
    result = subprocess.run(
        [
            "python3", f"{REPO_DIR}/dataset_gen/run_batch.py",
            "--start", str(start_idx), "--end", str(end_idx),
            "--workers", "1",  # Serverless側は1ジョブ=1ワーカーなので内部並列は不要
            "--chunk_size", str(end_idx - start_idx),
            "--templates", templates_path,
            "--ops_dir", f"{out_dir}/ops",
            "--out", f"{out_dir}/rendered",
        ],
        cwd=REPO_DIR,
        capture_output=True, text=True, timeout=1800
    )

    return {
        "start": start_idx,
        "end": end_idx,
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-1000:],
        "returncode": result.returncode,
    }


runpod.serverless.start({"handler": handler})
