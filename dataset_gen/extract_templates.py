"""
Objaverseから追加のメッシュをダウンロードし、パーツ分割・接続構造(テンプレート)を抽出する。
GPU不要、CPUのみで完結する処理。
"""
import json
import random
import multiprocessing
import argparse

import objaverse
import trimesh
import numpy as np


def extract_template(mesh_path, uid):
    try:
        scene_or_mesh = trimesh.load(mesh_path, force='scene')
    except Exception:
        return None

    if isinstance(scene_or_mesh, trimesh.Scene):
        parts = [g for g in scene_or_mesh.geometry.values() if isinstance(g, trimesh.Trimesh) and len(g.vertices) > 0]
    else:
        parts = [scene_or_mesh] if isinstance(scene_or_mesh, trimesh.Trimesh) else []

    if len(parts) < 2 or len(parts) > 47:
        return None

    bboxes = []
    for p in parts:
        bounds = p.bounds
        size = bounds[1] - bounds[0]
        center = (bounds[1] + bounds[0]) / 2
        bboxes.append((size, center))

    all_mins = np.min([c - s / 2 for s, c in bboxes], axis=0)
    all_maxs = np.max([c + s / 2 for s, c in bboxes], axis=0)
    overall_size = np.max(all_maxs - all_mins)
    if overall_size < 1e-6:
        return None

    rel_sizes = []
    rel_centers = []
    for size, center in bboxes:
        rel_sizes.append((size / overall_size).round(4).tolist())
        rel_centers.append((center / overall_size).round(4).tolist())

    edges = []
    n = len(parts)
    for i in range(n):
        for j in range(i + 1, n):
            rel_offset = (np.array(rel_centers[j]) - np.array(rel_centers[i])).round(4).tolist()
            edges.append({"a": i, "b": j, "rel_offset": rel_offset})

    return {"uid": uid, "num_parts": n, "rel_sizes": rel_sizes, "edges": edges}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target_count", type=int, default=2000)
    parser.add_argument("--existing_templates", type=str, required=True)
    parser.add_argument("--out", type=str, default="/tmp/structure_templates_expanded.json")
    args = parser.parse_args()

    print("loading annotations...", flush=True)
    annotations = objaverse.load_annotations()
    print(f"total annotations: {len(annotations)}", flush=True)

    filtered_uids = []
    for uid, ann in annotations.items():
        license_info = ann.get("license", "")
        if isinstance(license_info, str):
            low = license_info.lower()
            if any(l in low for l in ["by", "cc0"]) and "nc" not in low and "nd" not in low:
                filtered_uids.append(uid)
    print(f"license-clean count: {len(filtered_uids)}", flush=True)

    random.seed(42)
    sample_uids = random.sample(filtered_uids, min(args.target_count, len(filtered_uids)))
    print(f"sampled: {len(sample_uids)}", flush=True)

    print("downloading objects...", flush=True)
    objects = objaverse.load_objects(uids=sample_uids, download_processes=min(8, multiprocessing.cpu_count()))
    print(f"downloaded: {len(objects)}", flush=True)

    new_templates = []
    failed = 0
    for uid, path in objects.items():
        result = extract_template(path, uid)
        if result:
            new_templates.append(result)
        else:
            failed += 1
    print(f"extracted: {len(new_templates)}, failed/filtered: {failed}", flush=True)

    with open(args.existing_templates) as f:
        existing = json.load(f)
    print(f"existing: {len(existing)}", flush=True)

    combined = existing + new_templates
    print(f"combined total: {len(combined)}", flush=True)

    with open(args.out, "w") as f:
        json.dump(combined, f, ensure_ascii=False)
    print(f"saved to {args.out}", flush=True)


if __name__ == "__main__":
    main()
