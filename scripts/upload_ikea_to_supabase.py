#!/usr/bin/env python3
"""
把本地各品牌的 {brand}_tw.json + {brand}_embeddings.npz（品牌清單見 furniture_kb._BRANDS）
上傳到 Supabase 的 ikea_products table（表名沿用，現在也放其他品牌）。
上傳前請先在 Supabase SQL Editor 執行 scripts/sql/furniture_products_v2.sql（新增品牌、尺寸等欄位）。

用法：
    python scripts/upload_ikea_to_supabase.py              # dry run，只印出會做什麼
    python scripts/upload_ikea_to_supabase.py --upload      # 實際上傳
    python scripts/upload_ikea_to_supabase.py --upload --rebuild  # 清空 table 後重新上傳
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

import numpy as np

from designbridge.pricing.furniture_kb import _BRANDS

KB_DIR = Path(__file__).parent.parent / "designbridge" / "furniture_kb"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

TABLE = "ikea_products"
BATCH_SIZE = 100


def get_client():
    try:
        from supabase import create_client
    except ImportError:
        print("請先安裝: pip install supabase")
        sys.exit(1)
    return create_client(SUPABASE_URL, SERVICE_ROLE_KEY)


def load_data() -> tuple[list[dict], np.ndarray]:
    kb: list[dict] = []
    parts: list[np.ndarray] = []
    for brand in _BRANDS:
        kb_path, emb_path = KB_DIR / f"{brand}_tw.json", KB_DIR / f"{brand}_embeddings.npz"
        if not kb_path.exists():
            continue
        items = json.loads(kb_path.read_text(encoding="utf-8"))
        if not emb_path.exists():
            print(f"❌ 找不到 {emb_path.name}，請先執行 scripts/build_ikea_embeddings.py --brand {brand}")
            sys.exit(1)
        matrix = np.load(str(emb_path))["embeddings"].astype("float32")
        if len(items) != len(matrix):
            print(f"❌ {brand}：商品 {len(items)} 件與向量 {len(matrix)} 筆不符，請重新執行 build_ikea_embeddings.py --brand {brand}")
            sys.exit(1)
        print(f"  {brand}: {len(items)} 件")
        kb += items
        parts.append(matrix)
    matrix = np.concatenate(parts)

    zero_rows = int(np.all(matrix == 0, axis=1).sum())
    if zero_rows:
        print(f"⚠️  有 {zero_rows} 筆 embedding 是全零（下載圖片失敗），仍會上傳，但比對時相似度會很低")

    return kb, matrix


def build_rows(kb: list[dict], matrix: np.ndarray) -> list[dict]:
    rows = []
    for item, emb in zip(kb, matrix):
        rows.append({
            "name": item.get("name") or "",
            "category": item.get("category") or "",
            "subcategory": item.get("subcategory"),
            "brand": item.get("brand") or "IKEA",
            "series": item.get("series"),
            "product_code": item.get("product_code"),
            "color": item.get("color"),
            "width_cm": item.get("width_cm"),
            "depth_cm": item.get("depth_cm"),
            "height_cm": item.get("height_cm"),
            "price": int(item.get("price") or 0),
            "currency": item.get("currency") or "TWD",
            "url": item.get("url") or "",
            "image_url": item.get("image_url") or "",
            "style_tags": item.get("style_tags") or [],
            "embedding": emb.tolist(),
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload", action="store_true", help="實際上傳（預設 dry run）")
    parser.add_argument("--rebuild", action="store_true", help="上傳前先清空 table")
    args = parser.parse_args()

    dry_run = not args.upload

    kb, matrix = load_data()
    print(f"共 {len(kb)} 筆家具，embedding 維度 {matrix.shape[1]}")

    if dry_run:
        print("\n[dry run] 不會實際上傳，加上 --upload 才會寫入 Supabase")
        print("範例（第 1 筆）：")
        sample = build_rows(kb[:1], matrix[:1])[0]
        sample_preview = {**sample, "embedding": f"<{len(sample['embedding'])} floats>"}
        print(json.dumps(sample_preview, ensure_ascii=False, indent=2))
        return

    if not SUPABASE_URL or not SERVICE_ROLE_KEY:
        print("❌ 缺少 SUPABASE_URL 或 SUPABASE_SERVICE_ROLE_KEY（請確認 .env）")
        sys.exit(1)

    client = get_client()

    if args.rebuild:
        print(f"清空 table {TABLE} ...")
        client.table(TABLE).delete().neq("id", 0).execute()

    rows = build_rows(kb, matrix)
    total = len(rows)
    uploaded = 0

    for i in range(0, total, BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        client.table(TABLE).insert(batch).execute()
        uploaded += len(batch)
        print(f"  已上傳 {uploaded}/{total}")

    print(f"\n完成！共上傳 {uploaded} 筆到 {TABLE}")


if __name__ == "__main__":
    main()
