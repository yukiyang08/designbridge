"""二手家具推薦：各店家的二手品（scripts/scrape_beg.py 爬北二高、scripts/import_secondhand_csv.py 匯入其他店家，
都寫進 secondhand_tw.json 並同步向量），跟估價的裁切圖比 CLIP 相似度。

二手品只有幾十件，不進 Supabase，也不跟 IKEA 混在同一個候選池（混在一起幾乎不會被排到前面）；
估價時另外比對，接在新品候選後面。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_BASE = Path(__file__).parent.parent / "furniture_kb"
_JSON = _BASE / "secondhand_tw.json"
_NPZ = _BASE / "secondhand_embeddings.npz"

# 二手品是店內實拍（有背景、角度雜），跟裁切圖的相似度比 IKEA 去背商品圖低，門檻不能用 0.75
MIN_SIMILARITY = 0.6
SOURCE = "secondhand"
# 櫃子、桌子種類太雜，偵測名稱對不到細分類（壁掛架、床邊小几）時只會比到外型相近的別種東西，寧可不推薦
_NEEDS_SUBTYPE = {"storage", "table"}
# 系統櫃、廚具是裝潢的一部分，不是買得到的二手家具
_EXPLICIT_ONLY = {"desk-chair", "bar-stool", "table-chair-set"}
_BUILT_IN_RE = re.compile(r"廚|櫥櫃|流理|烤箱|系統|吊櫃|壁掛|懸掛|嵌入|壁櫃")

_cache: tuple | None = None   # (stamp, items, matrix)


def _load():
    """(items, matrix)；資料檔重抓就重新載入。沒有資料或筆數對不上回傳 ([], None)。"""
    global _cache
    stamp = tuple(p.stat().st_mtime if p.exists() else 0 for p in (_JSON, _NPZ))
    if _cache is None or _cache[0] != stamp:
        items, matrix = [], None
        try:
            import numpy as np
            items = json.loads(_JSON.read_text(encoding="utf-8"))
            matrix = np.load(str(_NPZ))["embeddings"].astype("float32")
            if matrix.shape[0] != len(items):
                print(f"[secondhand] 商品 {len(items)} 件、向量 {matrix.shape[0]} 筆不符，"
                      "請執行 build_ikea_embeddings.py --brand secondhand --rebuild")
                items, matrix = [], None
        except FileNotFoundError:
            items, matrix = [], None
        except Exception as e:
            print(f"[secondhand] 載入失敗：{e}")
            items, matrix = [], None
        _cache = (stamp, items, matrix)
    return _cache[1], _cache[2]


def match_secondhand(
    query_embedding: list[float],
    category: str,
    detected_name: str = "",
    top_k: int = 2,
    min_similarity: float = MIN_SIMILARITY,
) -> list[dict]:
    """同大類的二手品依相似度排序；偵測名稱對得到細分類時只在細分類裡找（辦公椅不推薦餐椅），
    細分類沒有二手品就不推薦。"""
    from designbridge.pricing.furniture_kb import subcategories_for
    import numpy as np

    items, matrix = _load()
    if not items or not category or _BUILT_IN_RE.search(detected_name or ""):
        return []
    subs = subcategories_for(category, detected_name)
    if category in _NEEDS_SUBTYPE and not subs:
        return []
    scores = matrix @ np.asarray(query_embedding, dtype="float32")
    results = []
    for i in np.argsort(scores)[::-1]:
        item = items[int(i)]
        sim = float(scores[i])
        if sim < min_similarity:
            break
        if item.get("category") != category:
            continue
        sub = item.get("subcategory")
        if subs and sub not in subs:
            continue
        # 辦公椅、吧台椅、桌椅組外型特殊，偵測名稱明講才推薦（「單人椅」不該推薦辦公椅）
        if sub in _EXPLICIT_ONLY and sub not in subs:
            continue
        results.append({**item, "similarity": round(sim, 4)})
        if len(results) >= top_k:
            break
    return results


def item_id(item: dict) -> str:
    """商品 id：匯入時就有 id；早期北二高資料沒有，用商品編號補（跟收藏、報價存過的 id 一致）。"""
    return item.get("id") or f"beg-{item.get('product_code') or ''}"


def to_candidate(hit: dict) -> dict:
    """轉成估價候選（FurnitureCandidate 加上來源、店家欄位，前端據此標「二手」）。"""
    return {
        "id": item_id(hit),
        "name": hit.get("name") or "",
        "price": int(hit.get("price") or 0),
        "purchase_url": hit.get("url") or "",
        "product_image_url": hit.get("image_url") or "",
        "similarity": hit.get("similarity", 0.0),
        "source": SOURCE,
        "store": hit.get("brand") or "",
    }


def store_counts() -> dict[str, int]:
    """各二手店家的件數（家具查詢頁的品牌選項）；每次讀檔，重抓後不用重啟。"""
    from collections import Counter
    try:
        items = json.loads(_JSON.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    return dict(Counter(it.get("brand") or "二手" for it in items).most_common())


def browse(
    category: str = "",
    min_price: float | None = None,
    max_price: float | None = None,
    brand: str = "",
    style: str = "",
    q: str = "",
    sort: str = "",
    limit: int = 60,
    offset: int = 0,
) -> dict:
    """家具查詢頁的二手清單，篩選與分頁跟 furniture_kb.list_furniture 同一套參數與回傳格式。"""
    try:
        items = json.loads(_JSON.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        items = []
    kw = q.strip().lower()
    rows = [
        {
            "id": item_id(it),
            "name": it.get("name") or "",
            "brand": it.get("brand") or "",
            "category": it.get("category") or "",
            "subcategory": it.get("subcategory") or "",
            "price": int(it.get("price") or 0),
            "currency": it.get("currency") or "TWD",
            "url": it.get("url") or "",
            "image_url": it.get("image_url") or "",
            "style_tags": it.get("style_tags") or [],
            "condition": "二手",
        }
        for it in items
    ]
    rows = [
        r for r in rows
        if (not category or r["category"] == category)
        and (min_price is None or r["price"] >= min_price)
        and (max_price is None or r["price"] <= max_price)
        and (not brand or r["brand"] == brand)
        and (not style or style in r["style_tags"])
        and (not kw or kw in r["name"].lower() or kw in r["brand"].lower())
    ]
    if sort in ("price_asc", "price_desc"):
        rows.sort(key=lambda r: r["price"], reverse=sort == "price_desc")
    return {"items": rows[offset:offset + limit], "total": len(rows)}
