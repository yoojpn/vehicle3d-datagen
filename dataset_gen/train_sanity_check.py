"""
「配管検査」用の最小構成学習スクリプト。
- 画像エンコーダ: CLIP(事前学習済み、凍結)
- 操作列デコーダ: 数千万パラメータの小さいTransformer(新規学習)
- 目的: lossが下がるか確認するだけ。精度は求めない。

Kaggle Notebook上での実行を想定(torch, transformersはプリインストール済み)。

実行例:
python3 train_sanity_check.py --data_dir /kaggle/working/output/rendered_main --epochs 30
"""
import argparse
import json
import os
import glob
import random

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from PIL import Image

from op_tokenizer import encode_operations, VOCAB_SIZE, TOKEN_TO_ID


class VehicleDataset(Dataset):
    def __init__(self, data_dir, ops_dir, image_size=224, max_len=256):
        self.samples = []
        self.image_size = image_size
        self.max_len = max_len

        sample_dirs = sorted(glob.glob(os.path.join(data_dir, "*")))
        for d in sample_dirs:
            if not os.path.isdir(d):
                continue
            idx = os.path.basename(d)
            ops_path = os.path.join(ops_dir, f"ops_{idx}.json")
            view0_path = os.path.join(d, "view_00.png")
            if os.path.exists(ops_path) and os.path.exists(view0_path):
                self.samples.append((view0_path, ops_path))

        print(f"dataset loaded: {len(self.samples)} samples")

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, i):
        img_path, ops_path = self.samples[i]
        image = Image.open(img_path).convert("RGB").resize((self.image_size, self.image_size))
        import numpy as np
        image = torch.tensor(np.array(image), dtype=torch.float32).permute(2, 0, 1) / 255.0

        with open(ops_path) as f:
            data = json.load(f)
        tokens = encode_operations(data["operations"])
        tokens = tokens[:self.max_len]
        pad_len = self.max_len - len(tokens)
        input_ids = tokens + [TOKEN_TO_ID["<pad>"]] * pad_len
        return image, torch.tensor(input_ids, dtype=torch.long)


class SimpleImageEncoder(nn.Module):
    """事前学習済みCLIPが使えない場合のフォールバック軽量CNNエンコーダ。
    まずはこれで配管検査を行い、後でCLIPに差し替え可能にしておく。"""
    def __init__(self, out_dim=256):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(3, 32, 4, 2, 1), nn.ReLU(),   # 224->112
            nn.Conv2d(32, 64, 4, 2, 1), nn.ReLU(),  # 112->56
            nn.Conv2d(64, 128, 4, 2, 1), nn.ReLU(), # 56->28
            nn.Conv2d(128, 256, 4, 2, 1), nn.ReLU(),# 28->14
            nn.AdaptiveAvgPool2d(1),
        )
        self.proj = nn.Linear(256, out_dim)

    def forward(self, x):
        h = self.net(x).flatten(1)
        return self.proj(h)  # [B, out_dim]


class OpDecoder(nn.Module):
    def __init__(self, vocab_size, d_model=256, nhead=8, num_layers=6, max_len=256):
        super().__init__()
        self.token_emb = nn.Embedding(vocab_size, d_model)
        self.pos_emb = nn.Embedding(max_len, d_model)
        decoder_layer = nn.TransformerDecoderLayer(d_model=d_model, nhead=nhead, batch_first=True)
        self.decoder = nn.TransformerDecoder(decoder_layer, num_layers=num_layers)
        self.out_proj = nn.Linear(d_model, vocab_size)
        self.max_len = max_len

    def forward(self, img_feat, input_ids):
        B, L = input_ids.shape
        positions = torch.arange(L, device=input_ids.device).unsqueeze(0).expand(B, L)
        tok = self.token_emb(input_ids) + self.pos_emb(positions)

        memory = img_feat.unsqueeze(1)  # [B, 1, d_model]
        causal_mask = nn.Transformer.generate_square_subsequent_mask(L).to(input_ids.device)
        h = self.decoder(tgt=tok, memory=memory, tgt_mask=causal_mask)
        return self.out_proj(h)  # [B, L, vocab_size]


class FullModel(nn.Module):
    def __init__(self, vocab_size, d_model=256, max_len=256):
        super().__init__()
        self.image_encoder = SimpleImageEncoder(out_dim=d_model)
        self.decoder = OpDecoder(vocab_size, d_model=d_model, max_len=max_len)

    def forward(self, images, input_ids):
        img_feat = self.image_encoder(images)
        logits = self.decoder(img_feat, input_ids)
        return logits


def count_parameters(model):
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_dir", type=str, required=True)
    parser.add_argument("--ops_dir", type=str, required=True)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--max_len", type=int, default=256)
    parser.add_argument("--out_dir", type=str, default="/kaggle/working/train_output")
    parser.add_argument("--val_ratio", type=float, default=0.1,
                         help="検証用に取り分ける割合(この分は学習に一切使わない)")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"device: {device}")

    full_dataset = VehicleDataset(args.data_dir, args.ops_dir, max_len=args.max_len)
    val_size = int(len(full_dataset) * args.val_ratio)
    train_size = len(full_dataset) - val_size
    generator = torch.Generator().manual_seed(42)  # 毎回同じ分割になるよう固定
    train_dataset, val_dataset = torch.utils.data.random_split(
        full_dataset, [train_size, val_size], generator=generator
    )
    print(f"train: {train_size} samples, val: {val_size} samples (held out, never trained on)")

    loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True, num_workers=2)
    val_loader = DataLoader(val_dataset, batch_size=args.batch_size, shuffle=False, num_workers=2)

    model = FullModel(VOCAB_SIZE, max_len=args.max_len).to(device)
    print(f"model parameters: {count_parameters(model):,}")

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    pad_id = TOKEN_TO_ID["<pad>"]
    criterion = nn.CrossEntropyLoss(ignore_index=pad_id)

    log_path = os.path.join(args.out_dir, "loss_log.txt")
    loss_history = []

    import time
    train_start = time.time()
    total_batches_all_epochs = len(loader) * args.epochs
    batches_done_total = 0

    for epoch in range(args.epochs):
        model.train()
        total_loss = 0.0
        num_batches = 0
        for batch_i, (images, input_ids) in enumerate(loader):
            images, input_ids = images.to(device), input_ids.to(device)

            # teacher forcing: 入力は最後を除く、正解は最初を除く(1つずらす)
            decoder_input = input_ids[:, :-1]
            target = input_ids[:, 1:]

            logits = model(images, decoder_input)
            loss = criterion(logits.reshape(-1, VOCAB_SIZE), target.reshape(-1))

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            total_loss += loss.item()
            num_batches += 1
            batches_done_total += 1

            elapsed = time.time() - train_start
            rate = batches_done_total / elapsed if elapsed > 0 else 0
            remaining = (total_batches_all_epochs - batches_done_total) / rate if rate > 0 else float("inf")
            print(
                f"epoch {epoch+1}/{args.epochs}  batch {batch_i+1}/{len(loader)}  "
                f"batch_loss={loss.item():.4f}  elapsed={elapsed:.0f}s  eta={remaining:.0f}s",
                flush=True
            )

        avg_loss = total_loss / max(num_batches, 1)

        # 検証データでのloss(学習に一切使っていないデータ)
        model.eval()
        val_total_loss = 0.0
        val_batches = 0
        with torch.no_grad():
            for images, input_ids in val_loader:
                images, input_ids = images.to(device), input_ids.to(device)
                decoder_input = input_ids[:, :-1]
                target = input_ids[:, 1:]
                logits = model(images, decoder_input)
                v_loss = criterion(logits.reshape(-1, VOCAB_SIZE), target.reshape(-1))
                val_total_loss += v_loss.item()
                val_batches += 1
        val_avg_loss = val_total_loss / max(val_batches, 1)

        print(f"=== epoch {epoch+1}/{args.epochs} DONE  train_loss={avg_loss:.4f}  val_loss={val_avg_loss:.4f} ===", flush=True)
        loss_history.append((avg_loss, val_avg_loss))
        with open(log_path, "a") as f:
            f.write(f"{epoch+1}\t{avg_loss:.6f}\t{val_avg_loss:.6f}\n")

    model_path = os.path.join(args.out_dir, "model_sanity_check.pt")
    torch.save(model.state_dict(), model_path)
    print(f"model saved to {model_path}")
    print("TRAINING_DONE")


if __name__ == "__main__":
    main()
