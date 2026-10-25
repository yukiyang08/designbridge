# designbridge/furniture_kb.py
"""家具知識庫搜尋（IKEA 與其他品牌，見 _BRANDS）。
  主要路徑：Supabase pgvector RPC（match_ikea_products）
  Fallback 1：本地 numpy cosine 搜尋（ikea_embeddings.npz，Supabase 未設定或呼叫失敗時使用）
  Fallback 2：本地 JSON 關鍵字搜尋
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_BASE = Path(__file__).parent.parent / "furniture_kb"
# 每個品牌一份 {brand}_tw.json + {brand}_embeddings.npz，依此順序接起來，商品與向量的 index 對應
_BRANDS = ("ikea", "scanteak", "hola")

# ── 快取 ────────────────────────────────────────────────────────────────────────

_kb_cache: list[dict] | None = None
_emb_cache: Any = None          # numpy (N, 512) float32，與 _kb_cache 等長
_cache_stamp: tuple | None = None   # 各品牌資料檔的修改時間，變了就重新載入
_supabase_client: Any = None

# CLIP cosine similarity 門檻：低於此值視為「無合適候選」，不硬塞結果
MIN_SIMILARITY = 0.75

TABLE = "ikea_products"
RPC_NAME = "match_ikea_products"


def _load_brand_items(brand: str) -> list[dict]:
    path = _BASE / f"{brand}_tw.json"
    if not path.exists():
        return []
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    for item in items:
        item.setdefault("brand", "IKEA" if brand == "ikea" else brand)
    return items


def _refresh_if_changed() -> None:
    """資料檔重抓或重標風格後自動重新載入；uvicorn --reload 只看程式碼，不會因 JSON 變動重啟。"""
    global _kb_cache, _emb_cache, _cache_stamp
    stamp = tuple(
        p.stat().st_mtime if p.exists() else 0
        for brand in _BRANDS
        for p in (_BASE / f"{brand}_tw.json", _BASE / f"{brand}_embeddings.npz")
    )
    if stamp != _cache_stamp:
        _kb_cache, _emb_cache, _cache_stamp = None, None, stamp


def _load_local_kb() -> list[dict]:
    global _kb_cache
    _refresh_if_changed()
    if _kb_cache is None:
        _kb_cache = [item for brand in _BRANDS for item in _load_brand_items(brand)]
    return _kb_cache


def _load_embeddings():
    """載入本地 numpy embedding 矩陣，lazy cache。回傳 ndarray (N,512) 或 None。"""
    global _emb_cache
    _refresh_if_changed()
    if _emb_cache is None:
        import numpy as np
        parts = []
        for brand in _BRANDS:
            n = len(_load_brand_items(brand))
            path = _BASE / f"{brand}_embeddings.npz"
            emb = None
            if path.exists():
                try:
                    emb = np.load(str(path))["embeddings"].astype("float32")
                except Exception as e:
                    print(f"[furniture_kb] 載入 {path.name} 失敗：{e}")
            if emb is None or emb.shape[0] != n:
                # 缺向量或筆數不符：補零向量維持 index 對應（相似度 0，不會被選中）
                if n:
                    print(f"[furniture_kb] {brand} 向量缺少或筆數不符（{n} 件），請執行 build_ikea_embeddings.py --brand {brand}")
                emb = np.zeros((n, 512), dtype="float32")
            parts.append(emb)
        matrix = np.concatenate(parts) if parts else np.zeros((0, 512), dtype="float32")
        _emb_cache = matrix if matrix.any() else False   # 全部是零 = 沒有可用向量
    return _emb_cache if _emb_cache is not False else None


# ── Supabase pgvector（主要路徑）───────────────────────────────────────────────

def _get_supabase_client():
    """取得 Supabase client，未設定環境變數則回傳 None（不拋錯，讓上層 fallback）。"""
    global _supabase_client
    if _supabase_client is None:
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        if not url or not key:
            _supabase_client = False
        else:
            try:
                from supabase import create_client
                _supabase_client = create_client(url, key)
            except Exception as e:
                print(f"[furniture_kb] Supabase client 初始化失敗：{e}")
                _supabase_client = False
    return _supabase_client if _supabase_client is not False else None


def _find_top_k_supabase(
    query_embedding: list[float],
    category: str,
    top_k: int,
    min_similarity: float,
) -> list[dict] | None:
    """呼叫 Supabase RPC match_ikea_products。回傳 None 代表呼叫失敗（讓上層改走本地 fallback）。"""
    client = _get_supabase_client()
    if client is None:
        return None
    try:
        res = client.rpc(RPC_NAME, {
            "query_embedding": query_embedding,
            "filter_category": category or "",
            "match_count": top_k,
            "match_threshold": min_similarity,
        }).execute()
        return res.data or []
    except Exception as e:
        print(f"[furniture_kb] Supabase RPC 呼叫失敗，改用本地 fallback：{e}")
        return None


# ── 向量搜尋（本地 numpy fallback）─────────────────────────────────────────────

def find_top_k_by_embedding(
    query_embedding: list[float],
    category: str = "",
    top_k: int = 3,
    min_similarity: float = MIN_SIMILARITY,
) -> list[dict]:
    """
    向量搜尋入口：優先呼叫 Supabase pgvector RPC，失敗或未設定環境變數則
    fallback 到本地 numpy cosine 搜尋（ikea_embeddings.npz）。

    相似度低於 min_similarity 的候選不會被回傳（視為「無合適候選」），
    避免硬塞不相關的 top-3 結果。若最終沒有任何候選達標，回傳空 list。
    """
    supabase_hits = _find_top_k_supabase(query_embedding, category, top_k, min_similarity)
    if supabase_hits is not None:
        return supabase_hits

    return _find_top_k_local(query_embedding, category, top_k, min_similarity)


def _find_top_k_local(
    query_embedding: list[float],
    category: str = "",
    top_k: int = 3,
    min_similarity: float = MIN_SIMILARITY,
) -> list[dict]:
    """本地 numpy cosine 搜尋，embedding 矩陣與 ikea_tw.json 順序對應。"""
    import numpy as np

    matrix = _load_embeddings()
    kb = _load_local_kb()

    if matrix is None or len(kb) == 0:
        return []

    if len(kb) != len(matrix):
        print(f"[furniture_kb] KB({len(kb)}) 與 embedding({len(matrix)}) 長度不符，跳過向量搜尋")
        return []

    q = np.array(query_embedding, dtype="float32")
    scores = matrix @ q                     # (N,) cosine similarity（已 L2 normalize）
    order = np.argsort(scores)[::-1]        # 由高到低

    results = []
    below_threshold_logged = False
    for idx in order:
        if len(results) >= top_k:
            break
        item = kb[int(idx)]
        if category and item.get("category") != category:
            continue
        sim = float(scores[idx])
        if sim < min_similarity:
            if not below_threshold_logged:
                print(
                    f"[furniture_kb] 相似度 {sim:.4f} < 門檻 {min_similarity}，"
                    f"停止搜尋（category={category or 'any'}，已找到 {len(results)} 筆）"
                )
                below_threshold_logged = True
            break
        results.append({**item, "similarity": round(sim, 4)})

    return results


# ── 推薦：細分類篩選、風格加分、同系列去重 ───────────────────────────────────────

# 偵測到的家具名稱 → 只在這些細分類裡找（例如茶几不跟餐桌比）；沒對應到的名稱不篩選
_SUBCATEGORY_RULES: dict[str, list[tuple[str, set[str]]]] = {
    "table": [(r"桌椅組|一桌|餐桌組", {"table-chair-set"}),
              (r"茶几|茶幾|邊桌|邊几|邊幾|咖啡桌|角几|角幾|矮桌", {"coffee-side-table"}),
              (r"化妝桌|梳妝", {"dressing-table", "desk"}),
              (r"書桌|工作桌|電腦桌|辦公桌", {"desk"}),
              (r"餐桌|吧台|吧檯", {"dining-table"})],
    "chair": [(r"吧台椅|吧檯椅|高腳", {"bar-stool"}),
              (r"書桌椅|辦公椅|電腦椅|工作椅", {"desk-chair"}),
              (r"腳凳|腳椅", {"footstool", "stool"}),
              (r"長凳|長椅", {"bench"}),
              (r"凳", {"stool", "footstool"}),
              (r"單椅|扶手椅|休閒椅|沙發椅|搖椅|躺椅|單人沙發|主人椅", {"armchair"}),
              (r"餐椅", {"dining-chair"})],
    "sofa": [(r"沙發床", {"sofa-bed", "sofa"})],
    "storage": [(r"電視櫃|視聽櫃", {"tv-bench"}),
                (r"床頭櫃|床邊櫃|床頭几", {"bedside-table"}),
                (r"衣櫃|衣櫥", {"wardrobe"}),
                (r"斗櫃|抽屜櫃|五斗|收納抽屜", {"chest-of-drawers"}),
                (r"展示櫃|玻璃櫃|酒櫃", {"display-cabinet", "sideboard"}),
                (r"書櫃|書架", {"bookcase", "open-storage"}),
                (r"層架|置物架|開放式|格櫃", {"open-storage", "bookcase"}),
                (r"餐櫃|邊櫃|收納櫃|櫥櫃|矮櫃", {"sideboard", "chest-of-drawers"})],
    "lamp": [(r"吊燈", {"pendant-lamp"}),
             (r"吸頂燈|天花板燈|嵌燈|筒燈", {"ceiling-lamp"}),
             (r"落地燈|立燈", {"floor-lamp"}),
             (r"桌燈|檯燈|台燈", {"table-lamp", "desk-lamp"}),
             (r"壁燈", {"wall-lamp"})],
    "rug": [(r"走道|長條", {"runner"})],
}
STYLE_BONUS = 0.0    # 商品風格跟渲染圖相同時排序分數加多少；風格標籤還不夠準、效果也量不出來，先關閉
_POOL_SIZE = 40      # 先依大類別取這麼多候選，再篩選、去重


def subcategories_for(category: str, detected_name: str) -> set[str]:
    import re
    for pattern, subs in _SUBCATEGORY_RULES.get(category, []):
        if re.search(pattern, detected_name or ""):
            return subs
    return set()


def recommend_products(
    query_embedding: list[float],
    category: str = "",
    detected_name: str = "",
    style_id: str = "",
    top_k: int = 3,
    min_similarity: float = MIN_SIMILARITY,
    style_bonus: float = STYLE_BONUS,
    search=None,
) -> list[dict]:
    """估價推薦：向量搜尋取候選後，排除桌椅組、依細分類篩選、風格相符加分、同系列只留一件，
    最後才套用相似度門檻。

    細分類有商品就只在細分類裡推薦，達不到門檻寧可不推薦（茶几不推薦餐桌）；
    商品庫完全沒有該細分類時才退回整個大類。門檻放在最後，推薦結果才不會隨門檻改變。
    search 預設為 find_top_k_by_embedding（評估腳本可傳入本地搜尋）。
    """
    search = search or find_top_k_by_embedding
    pool = search(query_embedding, category, _POOL_SIZE, 0.0)
    # Supabase 回傳的欄位不含 style_tags，用網址對回本地資料補上
    local = {item.get("url"): item for item in _load_local_kb()}
    pool = [{**local.get(h.get("url"), {}), **h} for h in pool]

    subs = subcategories_for(category, detected_name)
    if "table-chair-set" not in subs:
        pool = [h for h in pool if h.get("subcategory") != "table-chair-set"]
    if subs:
        preferred = [h for h in pool if h.get("subcategory") in subs]
        if preferred:
            pool = preferred

    for h in pool:
        bonus = style_bonus if style_id and style_id in (h.get("style_tags") or []) else 0.0
        h["score"] = round(float(h.get("similarity") or 0) + bonus, 4)
    pool.sort(key=lambda h: h["score"], reverse=True)

    results, seen = [], set()
    for h in pool:
        # 同系列不同顏色、尺寸只留一件，3 個推薦才會是 3 種款式
        key = (h.get("brand"), h.get("series")) if h.get("series") else (h.get("brand"), h.get("name"))
        if key in seen:
            continue
        seen.add(key)
        if float(h.get("similarity") or 0) >= min_similarity:
            results.append(h)
        if len(results) >= top_k:
            break
    return results


# ── 關鍵字搜尋（text fallback）─────────────────────────────────────────────────

def _score_item(item: dict, query: str, category: str) -> float:
    score = 0.0
    name  = (item.get("name") or "").lower()
    cat   = (item.get("category") or "").lower()
    tags  = [t.lower() for t in (item.get("style_tags") or [])]

    if category and cat == category.lower():
        score += 2.0
    for token in query.lower().split():
        if token and token in name:
            score += 1.0
        if token and any(token in tag for tag in tags):
            score += 0.5
    return score


def search_kb(query: str, category: str = "", top_k: int = 3) -> list[dict]:
    """本地 JSON 關鍵字搜尋（向量搜尋失敗時的 fallback）。"""
    kb = _load_local_kb()
    if not kb:
        return []
    scored = sorted(
        ((item, _score_item(item, query, category)) for item in kb),
        key=lambda x: x[1], reverse=True,
    )
    return [item for item, score in scored[:top_k] if score > 0]


# ── 家具查詢（供前端瀏覽 / 篩選使用）───────────────────────────────────────────

def list_categories() -> list[str]:
    """回傳本地 KB 中所有出現過的家具分類（依名稱排序）。"""
    kb = _load_local_kb()
    return sorted({item.get("category", "") for item in kb if item.get("category")})


def list_filters() -> dict:
    """家具查詢頁的品牌、風格篩選選項與件數（依件數多到少）。"""
    from collections import Counter
    from style_kb.styles import STYLES
    kb = _load_local_kb()
    brands = Counter(item.get("brand") or "IKEA" for item in kb)
    styles = Counter(tag for item in kb for tag in item.get("style_tags") or [])
    names = dict(STYLES)
    return {
        "brands": [{"value": b, "label": b, "count": n} for b, n in brands.most_common()],
        "styles": [{"value": s, "label": names.get(s, s), "count": n} for s, n in styles.most_common()],
    }


def list_furniture(
    category: str = "",
    min_price: float | None = None,
    max_price: float | None = None,
    brand: str = "",
    style: str = "",
) -> list[dict]:
    """回傳符合分類 / 價位區間的家具清單（本地 JSON KB）。

    - category 為空字串代表不篩選分類
    - min_price / max_price 為 None 代表不限制該端
    """
    kb = _load_local_kb()
    results = []
    for item in kb:
        if category and item.get("category") != category:
            continue
        if brand and (item.get("brand") or "IKEA") != brand:
            continue
        if style and style not in (item.get("style_tags") or []):
            continue
        price = item.get("price")
        if price is None:
            continue
        if min_price is not None and price < min_price:
            continue
        if max_price is not None and price > max_price:
            continue
        results.append(item)
    return results
