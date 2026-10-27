#!/usr/bin/env python3
"""
估價 Agent 獨立測試腳本（不需要 Gemini / Supabase / 生成圖）
用途：驗證 KB 搜尋、候選組裝、預算計算是否正確。

用法：
    python scripts/test_quotation.py
    python scripts/test_quotation.py --image artifacts/render/xxx.png
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 讓 Python 找到 designbridge 套件
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_kb_search():
    """測試本地 KB 文字搜尋。"""
    print("=" * 60)
    print("【測試 1】本地 KB 文字搜尋")
    print("=" * 60)

    from designbridge.pricing.furniture_kb import search_kb, _load_local_kb

    kb = _load_local_kb()
    if not kb:
        print("❌ ikea_tw.json 是空的，請先執行：python scripts/scrape_ikea.py")
        return False

    print(f"✅ KB 載入成功：{len(kb)} 件商品")
    print(f"   類別分佈：")
    from collections import Counter
    cnt = Counter(i.get("category") for i in kb)
    for cat, n in sorted(cnt.items()):
        print(f"     {cat}: {n} 件")

    # 測試幾個查詢
    tests = [
        ("沙發", "sofa"),
        ("茶几", "table"),
        ("落地燈", "lamp"),
        ("書架", "storage"),
    ]
    print()
    for query, cat in tests:
        hits = search_kb(query, category=cat, top_k=2)
        if hits:
            h = hits[0]
            print(f"  '{query}' → {h['name']} NT${h['price']:,}")
        else:
            print(f"  '{query}' → 無結果")
    return True


def test_clip_embedding():
    """測試 CLIP embedding（不需要圖片，用隨機向量模擬）。"""
    print()
    print("=" * 60)
    print("【測試 2】Supabase 向量搜尋（match_ikea_products）")
    print("=" * 60)

    import numpy as np
    from designbridge.pricing.furniture_kb import find_top_k_by_embedding

    # 用隨機向量模擬 CLIP query
    rng = np.random.default_rng(42)
    fake_emb = rng.random(512).astype("float32")
    fake_emb /= np.linalg.norm(fake_emb)

    try:
        hits = find_top_k_by_embedding(fake_emb.tolist(), category="sofa", top_k=3)
    except RuntimeError as e:
        print(f"  向量搜尋服務不可用：{e}")
        return False
    if hits:
        print(f"  隨機查詢（category=sofa）→ top-3:")
        for h in hits:
            print(f"    {h['name']} NT${h['price']:,}  sim={h.get('similarity', 0):.3f}")
    else:
        print("  沒有結果（KB 可能沒有 sofa 類別）")
    return True


def test_full_quotation(image_path: str | None = None, skip_gemini: bool = False):
    """完整測試 build_quotation（可指定圖片，無圖片則用備用家具清單）。"""
    print()
    print("=" * 60)
    print("【測試 3】完整估價流程")
    print("=" * 60)

    # --skip-gemini：直接 patch detect_furniture_gemini 回傳空，觸發備用清單
    if skip_gemini:
        import designbridge.pricing.quotation as _q
        _q.detect_furniture_gemini = lambda *a, **kw: []
        print("  ⚡ --skip-gemini：直接使用備用家具清單（不呼叫 Gemini）")

    from designbridge.pricing.quotation import build_quotation

    # 模擬 structured_requirement
    mock_req = {
        "meta": {"room_type": "living_room", "design_goal": "renovation"},
        "style_preferences": {"primary_style": "北歐", "style_strength": 0.7},
    }

    if image_path and Path(image_path).is_file():
        print(f"  使用圖片：{image_path}")
        path = image_path
    else:
        # 找最新生成圖
        render_dir = Path(__file__).parent.parent / "artifacts" / "render"
        pngs = sorted(render_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        if pngs:
            path = str(pngs[0])
            print(f"  使用最新生成圖：{path}")
        else:
            print("  ⚠️  找不到生成圖，建立空白測試圖")
            from PIL import Image as PilImage
            tmp = Path(__file__).parent.parent / "artifacts" / "_test_blank.png"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            PilImage.new("RGB", (512, 512), (200, 200, 200)).save(tmp)
            path = str(tmp)

    result = build_quotation(path, mock_req)

    print()
    print(f"  家具件數：{len(result['furniture_list'])}")
    print(f"  KB 比對：{result['kb_match_count']}/{len(result['furniture_list'])} 件")
    print(f"  建議預算：NT$ {result['total_mid']:,}")
    print()

    for item in result["furniture_list"]:
        top = item["candidates"][0] if item["candidates"] else {}
        sim_str = f"  sim={top.get('similarity', 0):.2f}" if top.get("similarity") else ""
        print(f"  {item['detected_name']} ({item['category']})")
        print(f"    → {top.get('name', '無結果')}  NT$ {top.get('price', 0):,}{sim_str}")

    print()
    print(f"  低預算：NT$ {result['total_low']:,}")
    print(f"  建議  ：NT$ {result['total_mid']:,}")
    print(f"  高規格：NT$ {result['total_high']:,}")

    # 輸出完整 JSON
    out = Path(__file__).parent.parent / "artifacts" / "test_quotation_result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  完整結果已存：{out}")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", help="指定要分析的圖片路徑", default=None)
    parser.add_argument("--skip-gemini", action="store_true", help="跳過 Gemini，直接用備用家具清單")
    args = parser.parse_args()

    kb_ok = test_kb_search()
    test_clip_embedding()
    test_full_quotation(args.image, skip_gemini=args.skip_gemini)

    if not kb_ok:
        print("\n⚠️  KB 是空的，請先執行：")
        print("    python scripts/scrape_ikea.py")
        print("    python scripts/build_ikea_embeddings.py  # 需要 sentence-transformers")
