"""
v5: 実データから抽出した「構造テンプレート」(接続グラフ+相対サイズ)を使い、
プリミティブの種類・具体的な寸法・回転はランダムに再生成する。

これにより:
- 配置の「トポロジー」は実物由来 -> 自然な繋がり方になりやすい
- 具体的な形状・寸法は全てランダム生成 -> 著作権的にクリーン、多様性も確保
"""
import random
import json

PRIMITIVES = ["box", "cylinder", "sphere", "cone", "torus", "wedge", "tube"]
DEFORM_POOL = ["bevel", "bevel", "bevel", "taper", "solidify", "bend", "twist", "smooth"]


def sample_primitive_size(ptype, base):
    """プリミティブ種類ごとにパラメータの意味が異なるため、種類別にサイズを組み立てる"""
    j = lambda v: round(v * random.uniform(0.85, 1.15), 3)
    if ptype == "torus":
        # [major_radius, minor_radius]
        major = j(base * 0.5)
        minor = j(major * random.uniform(0.2, 0.4))
        return [major, minor]
    elif ptype == "tube":
        # [outer_radius, wall_ratio(0-1), height]
        return [j(base * 0.4), round(random.uniform(0.2, 0.5), 2), j(base)]
    else:
        # box/cylinder/sphere/cone/wedge は共通で [x, y, z] サイズ
        return [j(base), j(base), j(base * random.uniform(0.6, 1.4))]


def sample_deform_op(op_id, idx):
    dtype = random.choice(DEFORM_POOL)
    if dtype == "bevel":
        params = {"width": round(random.uniform(0.03, 0.1), 3), "segments": random.randint(2, 3)}
    elif dtype == "taper":
        params = {"factor": round(random.uniform(-0.35, 0.35), 2), "axis": random.choice(["x", "y", "z"])}
    elif dtype == "solidify":
        params = {"thickness": round(random.uniform(0.02, 0.06), 3)}
    elif dtype in ("bend", "twist"):
        params = {"angle": round(random.uniform(-0.5, 0.5), 2), "axis": random.choice(["x", "y", "z"])}
    else:  # smooth
        params = {"factor": round(random.uniform(0.3, 0.8), 2), "iterations": random.randint(1, 3)}
    return {"id": f"op{idx}_{dtype}", "type": dtype, "target": op_id, "params": params}


def _ensure_min_separation(offset, ptype_a, size_a, ptype_b, size_b):
    """オフセットが小さすぎて片方がもう片方に飲み込まれるのを防ぐ。
    パーツ半径の和の最低60%は離すことを保証する。"""
    import math
    offset_len = math.sqrt(sum(v*v for v in offset))
    min_required = (half_extent_x(ptype_a, size_a) + half_extent_x(ptype_b, size_b)) * 0.6
    if offset_len < min_required:
        if offset_len < 1e-6:
            # オフセットがほぼゼロの場合、ランダムな方向に押し出す
            direction = [random.uniform(-1, 1) for _ in range(3)]
            dlen = math.sqrt(sum(v*v for v in direction)) or 1.0
            direction = [v / dlen for v in direction]
        else:
            direction = [v / offset_len for v in offset]
        return [d * min_required for d in direction]
    return offset


def half_extent_x(ptype, size):
    if ptype == "box" or ptype == "wedge":
        return size[0] / 2
    if ptype == "torus":
        return size[0] + size[1]  # major+minor radius
    if ptype == "tube":
        return size[0]  # outer radius
    return size[0]  # cylinder/sphere/cone: 半径


def half_extent_y(ptype, size):
    if ptype == "box" or ptype == "wedge":
        return size[1] / 2
    if ptype == "torus":
        return size[0] + size[1]
    if ptype == "tube":
        return size[0]
    return size[1]


def half_extent_z(ptype, size):
    if ptype == "torus":
        return size[1]  # minor radius
    if ptype == "tube":
        return size[2] / 2
    return size[2] / 2


def load_templates(path="structure_templates.json"):
    with open(path) as f:
        return json.load(f)


def instantiate_template(template, global_scale=None, seed=None):
    if seed is not None:
        random.seed(seed)

    if global_scale is None:
        global_scale = round(random.uniform(1.5, 3.5), 2)

    n = template["num_parts"]
    rel_sizes = template["rel_sizes"]  # 各パーツの相対サイズ(0-1、最大パーツ基準)
    edges = template["edges"]

    # 各パーツにランダムなプリミティブ種類と実寸法を割り当てる
    ptypes = [random.choice(PRIMITIVES) for _ in range(n)]
    sizes = []
    for i in range(n):
        base_scale = max(rel_sizes[i]) * global_scale
        base_scale = max(base_scale, 0.08)
        sizes.append(sample_primitive_size(ptypes[i], base_scale))

    # 最初のパーツ(index 0)を原点・地面接地の基準にする
    positions = [None] * n
    positions[0] = [0.0, 0.0, half_extent_z(ptypes[0], sizes[0])]

    # edges を使って残りのパーツ位置を決める(BFS的に、既知の位置から相対オフセットで求める)
    resolved = {0}
    remaining_edges = list(edges)
    progress = True
    while remaining_edges and progress:
        progress = False
        still_pending = []
        for e in remaining_edges:
            a, b = e["a"], e["b"]
            if a in resolved and b not in resolved:
                base_pos = positions[a]
                offset = [v * global_scale for v in e["rel_offset"]]
                offset = _ensure_min_separation(offset, ptypes[a], sizes[a], ptypes[b], sizes[b])
                positions[b] = [base_pos[k] + offset[k] for k in range(3)]
                resolved.add(b)
                progress = True
            elif b in resolved and a not in resolved:
                base_pos = positions[b]
                offset = [-v * global_scale for v in e["rel_offset"]]
                offset = _ensure_min_separation(offset, ptypes[b], sizes[b], ptypes[a], sizes[a])
                positions[a] = [base_pos[k] + offset[k] for k in range(3)]
                resolved.add(a)
                progress = True
            else:
                still_pending.append(e)
        remaining_edges = still_pending

    # グラフから孤立してしまったパーツ(接続情報がなかった場合)は原点付近に配置
    for i in range(n):
        if positions[i] is None:
            positions[i] = [round(random.uniform(-0.3, 0.3), 2) * global_scale,
                             round(random.uniform(-0.3, 0.3), 2) * global_scale,
                             half_extent_z(ptypes[i], sizes[i])]

    # 地面(z<0)にめり込んでいるパーツがあれば底上げする
    min_z = min(positions[i][2] - half_extent_z(ptypes[i], sizes[i]) for i in range(n))
    if min_z < 0:
        for i in range(n):
            positions[i][2] -= min_z

    # ops列を組み立てる
    ops = []
    op_ids = []
    for i in range(n):
        op_id = f"op{i}"
        ops.append({
            "id": op_id, "type": f"add_{ptypes[i]}",
            "params": {"size": [round(v, 3) for v in sizes[i]],
                       "position": [round(v, 3) for v in positions[i]]}
        })
        op_ids.append(op_id)
        # 変形を付与(拡張した変形プールからランダムに選ぶ)
        if random.random() < 0.75:
            ops.append(sample_deform_op(op_id, i))

    return {"operations": ops, "num_parts": n, "num_operations": len(ops), "source_template": template["uid"]}


if __name__ == "__main__":
    templates = load_templates()
    print(f"loaded {len(templates)} templates")
    for i, t in enumerate(templates[:3]):
        result = instantiate_template(t, seed=500 + i)
        with open(f"batch5/ops_{i:03d}.json", "w") as f:
            json.dump(result, f, ensure_ascii=False)
        print(f"template {i}: {t['num_parts']} parts -> generated ops_{i:03d}.json")
