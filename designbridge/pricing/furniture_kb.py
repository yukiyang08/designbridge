# designbridge/furniture_kb.py
"""IKEA 家具知識庫搜尋。
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
_LOCAL_KB_PATH  = _BASE / "ikea_tw.json"
_EMB_PATH       = _BASE / "ikea_embeddings.npz"

# ── 快取 ────────────────────────────────────────────────────────────────────────

_kb_cache: list[dict] | None = None
_emb_cache: Any = None          # numpy (N, 512) float32，與 _kb_cache 等長
_supabase_client: Any = None

# CLIP cosine similarity 門檻：低於此值視為「無合適候選」，不硬塞結果
MIN_SIMILARITY = 0.75

TABLE = "ikea_products"
RPC_NAME = "match_ikea_products"


def _load_local_kb() -> list[dict]:
    global _kb_cache
    if _kb_cache is None:
        if _LOCAL_KB_PATH.exists():
            try:
                _kb_cache = json.loads(_LOCAL_KB_PATH.read_text(encoding="utf-8"))
            except Exception:
                _kb_cache = []
        else:
            _kb_cache = []
    return _kb_cache


def _load_embeddings():
    """載入本地 numpy embedding 矩陣，lazy cache。回傳 ndarray (N,512) 或 None。"""
    global _emb_cache
    if _emb_cache is None:
        if _EMB_PATH.exists():
            try:
                import numpy as np
                data = np.load(str(_EMB_PATH))
                _emb_cache = data["embeddings"].astype("float32")   # (N, 512)
            except Exception as e:
                print(f"[furniture_kb] 載入 embedding 失敗：{e}")
                _emb_cache = False          # 標記為「已嘗試但失敗」
        else:
            _emb_cache = False
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


def list_furniture(
    category: str = "",
    min_price: float | None = None,
    max_price: float | None = None,
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
        price = item.get("price")
        if price is None:
            continue
        if min_price is not None and price < min_price:
            continue
        if max_price is not None and price > max_price:
            continue
        results.append(item)
    return results
