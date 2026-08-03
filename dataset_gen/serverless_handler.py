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

BLENDER_BIN = "/opt/blender-5.2.0-linux-x64/blender"
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

    # デバッグモード3: コンテナ環境の詳細確認
    if job_input.get("debug_env"):
        checks = {}
        checks["ls_dev"] = subprocess.run(["ls", "-la", "/dev/"], capture_output=True, text=True).stdout
        checks["nvidia_devices"] = subprocess.run(
            ["bash", "-c", "ls -la /dev/nvidia* 2>&1"], capture_output=True, text=True
        ).stdout
        checks["env_nvidia"] = subprocess.run(
            ["bash", "-c", "env | grep -i nvidia"], capture_output=True, text=True
        ).stdout
        checks["cuda_visible"] = subprocess.run(
            ["bash", "-c", "echo $CUDA_VISIBLE_DEVICES"], capture_output=True, text=True
        ).stdout
        checks["nvidia_smi_l"] = subprocess.run(
            ["bash", "-c", "nvidia-smi -L 2>&1"], capture_output=True, text=True
        ).stdout
        # 実際に最小限のCyclesレンダーを1枚だけ試す(タイムアウトを短く区切って確認)
        import time
        t0 = time.time()
        try:
            minimal = subprocess.run(
                [BLENDER_BIN, "--background", "--python-expr",
                 "import bpy; bpy.ops.mesh.primitive_cube_add(); "
                 "s=bpy.context.scene; s.render.engine='CYCLES'; s.cycles.device='GPU'; "
                 "s.render.resolution_x=64; s.render.resolution_y=64; s.cycles.samples=4; "
                 "s.render.filepath='/tmp/mini.png'; "
                 "prefs = bpy.context.preferences.addons['cycles'].preferences; "
                 "prefs.compute_device_type='CUDA'; prefs.get_devices(); "
                 "[setattr(d,'use',True) for d in prefs.devices]; "
                 "print('RENDER_START'); "
                 "bpy.ops.render.render(write_still=True); "
                 "print('RENDER_DONE')"],
                capture_output=True, text=True, timeout=60
            )
            checks["mini_render_stdout"] = minimal.stdout
            checks["mini_render_stderr"] = minimal.stderr
            checks["mini_render_time"] = time.time() - t0
        except subprocess.TimeoutExpired as e:
            checks["mini_render_timeout"] = True
            checks["mini_render_stdout_partial"] = str(e.stdout)[-1500:] if e.stdout else None
            checks["mini_render_stderr_partial"] = str(e.stderr)[-1500:] if e.stderr else None
            checks["mini_render_time"] = time.time() - t0
        return checks

    # デバッグモード4: シーン構築とレンダリングの時間内訳を計測
    if job_input.get("debug_timing"):
        timing_script = f"""
import sys, time, json
sys.path.insert(0, '{REPO_DIR}/dataset_gen')
from op_sampler_v5 import load_templates, instantiate_template
import bpy
from build_and_render import (clear_scene, execute_operations, join_all_meshes,
    setup_camera_and_light, render_views, enable_gpu_rendering)

t0 = time.time()
enable_gpu_rendering()
t1 = time.time()

templates = load_templates('{REPO_DIR}/dataset_gen/structure_templates_300_v2.json')
ops_data = instantiate_template(templates[5], seed=1)
t2 = time.time()

clear_scene()
execute_operations(ops_data['operations'])
joined = join_all_meshes()
t3 = time.time()

cam = setup_camera_and_light()
render_views(cam, '/tmp/timing_test', joined, num_views=6)
t4 = time.time()

result = {{
    'gpu_setup': t1 - t0,
    'ops_generation': t2 - t1,
    'scene_construction': t3 - t2,
    'rendering_6views': t4 - t3,
    'total': t4 - t0,
}}
print('TIMING_RESULT:', json.dumps(result))
"""
        proc = subprocess.run(
            [BLENDER_BIN, "--background", "--python-expr", timing_script],
            capture_output=True, text=True, timeout=120
        )
        return {"stdout": proc.stdout, "stderr": proc.stderr[-1500:]}

    start_idx = job_input.get("start", 0)
    end_idx = job_input.get("end", start_idx + 20)
    templates_path = job_input.get(
        "templates", f"{REPO_DIR}/dataset_gen/structure_templates_300_v2.json"
    )
    out_dir = job_input.get("out_dir", "/runpod-volume/output")

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
