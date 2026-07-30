"""
操作列(JSON)をトークン列に変換する。
LLM的な「次のトークン予測」で学習できる形式にする。

トークン化方針:
- 操作タイプ(add_box, bevel, mirror等)は語彙として離散化
- 数値パラメータ(size, position等)は一定の刻み幅で量子化してトークン化
- target等の参照は「何個前のadd操作を指すか」という相対インデックスにする
  (絶対ID文字列だと語彙が爆発するため)
"""
import json

# 操作タイプの語彙(build_and_render.pyのBUILDERS/MODIFIERSと対応)
OP_TYPES = [
    "add_box", "add_cylinder", "add_sphere", "add_cone", "add_torus", "add_wedge", "add_tube",
    "bevel", "taper", "subdivide", "mirror", "array",
    "bend", "twist", "shear", "solidify", "displace",
    "remesh", "decimate", "smooth", "extrude", "inset",
]

SPECIAL_TOKENS = ["<pad>", "<start>", "<end>", "<sep>"]

# 数値量子化の設定: -3.0〜3.0の範囲を0.05刻みで121ビンに量子化
NUM_MIN, NUM_MAX, NUM_STEP = -3.0, 3.0, 0.05
NUM_BINS = int(round((NUM_MAX - NUM_MIN) / NUM_STEP)) + 1  # 121

AXIS_TOKENS = ["axis_x", "axis_y", "axis_z"]


def build_vocab():
    vocab = list(SPECIAL_TOKENS)
    vocab += [f"OP_{t}" for t in OP_TYPES]
    vocab += [f"NUM_{i}" for i in range(NUM_BINS)]
    vocab += AXIS_TOKENS
    vocab += ["TARGET_REL"]  # 直後に相対インデックスの数値トークンが続く
    token_to_id = {t: i for i, t in enumerate(vocab)}
    id_to_token = {i: t for i, t in enumerate(vocab)}
    return token_to_id, id_to_token


TOKEN_TO_ID, ID_TO_TOKEN = build_vocab()
VOCAB_SIZE = len(TOKEN_TO_ID)


def quantize(value):
    v = max(NUM_MIN, min(NUM_MAX, value))
    bin_idx = int(round((v - NUM_MIN) / NUM_STEP))
    return f"NUM_{bin_idx}"


def dequantize(token):
    bin_idx = int(token.split("_")[1])
    return NUM_MIN + bin_idx * NUM_STEP


def encode_operations(ops):
    """操作列(dictのリスト)をトークンID列に変換"""
    tokens = ["<start>"]
    id_position = {}  # op_id -> このopが何番目のadd操作か(相対参照用)
    add_count = 0

    for op in ops:
        op_type = op["type"]
        tokens.append(f"OP_{op_type}")

        if op_type.startswith("add_"):
            id_position[op["id"]] = add_count
            add_count += 1
            for v in op["params"].get("size", []):
                tokens.append(quantize(v))
            tokens.append("<sep>")
            for v in op["params"].get("position", []):
                tokens.append(quantize(v))
        else:
            # target を「現在のadd数からの相対距離」として表現
            target_id = op.get("target")
            if target_id in id_position:
                rel = add_count - 1 - id_position[target_id]
                tokens.append("TARGET_REL")
                tokens.append(quantize(rel))
            params = op.get("params", {})
            for k, v in params.items():
                if k == "axis":
                    tokens.append(f"axis_{v}")
                elif isinstance(v, (int, float)):
                    tokens.append(quantize(v))
        tokens.append("<sep>")

    tokens.append("<end>")
    return [TOKEN_TO_ID[t] for t in tokens if t in TOKEN_TO_ID]


if __name__ == "__main__":
    print(f"vocab size: {VOCAB_SIZE}")
    sample = {
        "operations": [
            {"id": "op0", "type": "add_box", "params": {"size": [1.5, 0.8, 0.6], "position": [0, 0, 0.3]}},
            {"id": "op1", "type": "bevel", "target": "op0", "params": {"width": 0.05, "segments": 2}},
        ]
    }
    encoded = encode_operations(sample["operations"])
    print(f"encoded length: {len(encoded)}")
    print(f"tokens: {[ID_TO_TOKEN[i] for i in encoded]}")
