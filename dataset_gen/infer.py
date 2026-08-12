"""
学習済みモデルで、画像から操作列を自己回帰的に生成する推論スクリプト。

実行例:
python3 infer.py --model_path model_sanity_check.pt --image_path test.png --out ops_generated.json
"""
import argparse
import json
import sys
import os

import torch
from PIL import Image
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from op_tokenizer import TOKEN_TO_ID, ID_TO_TOKEN, VOCAB_SIZE, dequantize, decode_operations
from train_sanity_check import FullModel


def load_image(path, image_size=224):
    image = Image.open(path).convert("RGB").resize((image_size, image_size))
    arr = torch.tensor(np.array(image), dtype=torch.float32).permute(2, 0, 1) / 255.0
    return arr.unsqueeze(0)  # [1, 3, H, W]


def generate(model, image_tensor, device, max_len=256):
    model.eval()
    image_tensor = image_tensor.to(device)
    img_feat = model.image_encoder(image_tensor)

    generated = [TOKEN_TO_ID["<start>"]]
    with torch.no_grad():
        for _ in range(max_len - 1):
            input_ids = torch.tensor([generated], dtype=torch.long, device=device)
            logits = model.decoder(img_feat, input_ids)
            next_token_logits = logits[0, -1, :]
            next_token = torch.argmax(next_token_logits).item()
            generated.append(next_token)
            if next_token == TOKEN_TO_ID["<end>"]:
                break

    return generated


def tokens_to_readable(token_ids):
    """デバッグ用: トークンID列を人間が読める文字列に変換"""
    tokens = [ID_TO_TOKEN.get(t, f"UNK_{t}") for t in token_ids]
    return " ".join(tokens)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_path", type=str, required=True)
    parser.add_argument("--image_path", type=str, required=True)
    parser.add_argument("--out", type=str, default="generated_tokens.txt")
    parser.add_argument("--max_len", type=int, default=256)
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"device: {device}")

    model = FullModel(VOCAB_SIZE, max_len=args.max_len).to(device)
    model.load_state_dict(torch.load(args.model_path, map_location=device))
    print("model loaded")

    image_tensor = load_image(args.image_path)
    generated = generate(model, image_tensor, device, max_len=args.max_len)

    readable = tokens_to_readable(generated)
    print("generated tokens:")
    print(readable)

    with open(args.out, "w") as f:
        f.write(readable + "\n")
        f.write(str(generated))

    # Blenderで組み立てられる形式の操作列JSONも出力する
    ops = decode_operations(generated)
    ops_json_path = args.out.replace(".txt", "_ops.json")
    with open(ops_json_path, "w") as f:
        json.dump({"operations": ops, "num_parts": len(ops)}, f, ensure_ascii=False, indent=2)
    print(f"decoded {len(ops)} operations, saved to {ops_json_path}")

    print(f"saved to {args.out}")


if __name__ == "__main__":
    main()
