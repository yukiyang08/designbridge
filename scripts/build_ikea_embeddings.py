#!/usr/bin/env python3
"""
從本地 ikea_tw.json 下載商品圖片 → CLIP ViT-B/32 embedding → 存到 ikea_embeddings.npz。
embedding 矩陣與 JSON 陣列順序一致，furniture_kb.py 直接以 index 對應。

支援斷點續跑：若 .npz 已存在，已有非零 embedding 的商品會跳過。

用法：
    python scripts/build_ikea_embeddings.py
    python scripts/build_ikea_embeddings.py --rebuild   # 忽略已有 .npz，全部重跑
    python scripts/build_ikea_embeddings.py --brand scanteak --rebuild   # 其他品牌
"""

from __future__ import annotations

import argparse
import io
import json
import time
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

_KB_DIR  = Path(__file__).parent.parent / "designbridge" / "furniture_kb"
KB_PATH  = _KB_DIR / "ikea_tw.json"
EMB_PATH = _KB_DIR / "ikea_embeddings.npz"
DIM = 512


def load_clip():
    from sentence_transformers import SentenceTransformer
    print("[embed] 載入 CLIP ViT-B/32 ...")
    m = SentenceTransformer("clip-ViT-B-32")
    print("[embed] 模型就緒")
    return m


def encode(model, pil_img: Image.Image) -> np.ndarray:
    """回傳 L2 normalized (512,) float32 vector。"""
    emb = model.encode(pil_img, convert_to_numpy=True).astype("float32")
    norm = np.linalg.norm(emb)
    return emb / norm if norm > 0 else emb


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true", help="忽略已有 .npz，全部重新計算")
    parser.add_argument("--brand", default="ikea", help="品牌檔名前綴：讀 {brand}_tw.json、寫 {brand}_embeddings.npz")
    args = parser.parse_args()

    global KB_PATH, EMB_PATH
    KB_PATH = _KB_DIR / f"{args.brand}_tw.json"
    EMB_PATH = _KB_DIR / f"{args.brand}_embeddings.npz"

    if not KB_PATH.exists():
        print(f"[embed] 找不到 {KB_PATH}，請先執行 scripts/scrape_ikea.py")
        return

    kb: list[dict] = json.loads(KB_PATH.read_text(encoding="utf-8"))
    n = len(kb)
    print(f"[embed] 共 {n} 件商品")

    # 載入已有 embedding（斷點續跑）
    if EMB_PATH.exists() and not args.rebuild:
        existing = np.load(str(EMB_PATH))["embeddings"].astype("float32")
        if existing.shape == (n, DIM):
            matrix = existing
            print(f"[embed] 載入已有 .npz（{n} 筆），將跳過已有 embedding 的商品")
        else:
            print(f"[embed] .npz 維度不符（{existing.shape} vs ({n},{DIM})），重新建立")
            matrix = np.zeros((n, DIM), dtype="float32")
    else:
        matrix = np.zeros((n, DIM), dtype="float32")

    model = load_clip()
    ok = skip = fail = 0
    SAVE_EVERY = 50     # 每 N 件存一次，防止意外中斷丟資料

    with httpx.Client(timeout=15, follow_redirects=True) as http:
        for i, item in enumerate(kb):
            # 跳過已有 embedding（非零向量）
            if not args.rebuild and np.any(matrix[i] != 0):
                skip += 1
                continue

            img_url = (item.get("image_url") or "").strip()
            if not img_url:
                fail += 1
                print(f"  [{i+1}/{n}] SKIP（無圖）{item.get('name','')[:30]}")
                continue

            try:
                resp = http.get(img_url)
                resp.raise_for_status()
                pil_img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                matrix[i] = encode(model, pil_img)
                ok += 1
                print(f"  [{i+1}/{n}] OK  {item.get('name','')[:40]}")
            except Exception as e:
                fail += 1
                print(f"  [{i+1}/{n}] FAIL {item.get('name','')[:30]}: {e}")

            # 定期存檔
            if (i + 1) % SAVE_EVERY == 0:
                np.savez(str(EMB_PATH), embeddings=matrix)
                print(f"  [checkpoint] 存檔 {i+1}/{n}")
                time.sleep(0.3)
            else:
                time.sleep(0.05)

    # 最終存檔
    EMB_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez(str(EMB_PATH), embeddings=matrix)
    print(f"\n完成！OK={ok}  SKIP={skip}  FAIL={fail}  TOTAL={n}")
    print(f"已存到：{EMB_PATH}（{matrix.nbytes / 1024 / 1024:.1f} MB）")


if __name__ == "__main__":
    main()
