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
