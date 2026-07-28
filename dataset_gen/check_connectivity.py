import json
import sys


def half_extent_x(ptype, size):
    if ptype in ("box", "wedge"):
        return size[0] / 2
    if ptype == "torus":
        return size[0] + size[1]
    if ptype == "tube":
        return size[0]
    return size[0]


def half_extent_y(ptype, size):
    if ptype in ("box", "wedge"):
        return size[1] / 2
    if ptype == "torus":
        return size[0] + size[1]
    if ptype == "tube":
        return size[0]
    return size[1]


def half_extent_z(ptype, size):
    if ptype == "torus":
        return size[1]
    return size[2] / 2


def bbox_of(ptype, position, size):
    hx, hy, hz = half_extent_x(ptype, size), half_extent_y(ptype, size), half_extent_z(ptype, size)
    x, y, z = position
    return (x - hx, x + hx, y - hy, y + hy, z - hz, z + hz)


def boxes_touch_or_overlap(b1, b2, tol=0.02):
    # 各軸でオーバーラップ(または許容誤差内で接触)しているか
    for i in range(3):
        lo1, hi1 = b1[i*2], b1[i*2+1]
        lo2, hi2 = b2[i*2], b2[i*2+1]
        if hi1 + tol < lo2 or hi2 + tol < lo1:
            return False
    return True


def check_connectivity(ops_path):
    with open(ops_path) as f:
        data = json.load(f)
    ops = data["operations"]

    primitives = []  # (id, ptype, position, size)
    for op in ops:
        if op["type"].startswith("add_"):
            ptype = op["type"].replace("add_", "")
            primitives.append((op["id"], ptype, op["params"]["position"], op["params"]["size"]))

    n = len(primitives)
    boxes = [bbox_of(p[1], p[2], p[3]) for p in primitives]

    # 連結成分をUnion-Findで判定
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for i in range(n):
        for j in range(i+1, n):
            if boxes_touch_or_overlap(boxes[i], boxes[j]):
                union(i, j)

    components = {}
    for i in range(n):
        r = find(i)
        components.setdefault(r, []).append(primitives[i][0])

    return {
        "num_primitives": n,
        "num_components": len(components),
        "components": list(components.values()),
        "is_fully_connected": len(components) == 1
    }


if __name__ == "__main__":
    result = check_connectivity(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
