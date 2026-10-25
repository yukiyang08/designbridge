# designbridge/furniture_kb.py
"""IKEA 家具知識庫搜尋。
  向量比對：Supabase pgvector RPC（match_ikea_products），失敗丟 RuntimeError，由呼叫端決定改用關鍵字或 LLM 估價
  關鍵字搜尋與家具瀏覽：本地 ikea_tw.json（隨程式部署的靜態資料）
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_BASE = Path(__file__).parent.parent / "furniture_kb"
_LOCAL_KB_PATH  = _BASE / "ikea_tw.json"

# ── 快取 ────────────────────────────────────────────────────────────────────────

_kb_cache: list[dict] | None = None
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


# ── Supabase pgvector───────────────────────────────────────────────

def _get_supabase_client():
    """取得 Supabase client，未設定環境變數則回傳 None（不拋錯）。"""
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
) -> list[dict]:
    """呼叫 Supabase RPC match_ikea_products。無達標候選回空 list；未設定或呼叫失敗丟 RuntimeError。"""
    client = _get_supabase_client()
    if client is None:
        raise RuntimeError("Supabase 未設定（SUPABASE_URL／SUPABASE_SERVICE_ROLE_KEY），無法做向量比對")
    try:
        res = client.rpc(RPC_NAME, {
            "query_embedding": query_embedding,
            "filter_category": category or "",
            "match_count": top_k,
            "match_threshold": min_similarity,
        }).execute()
        return res.data or []
    except Exception as e:
        raise RuntimeError(f"match_ikea_products 呼叫失敗：{e}") from e


# ── 向量搜尋 ───────────────────────────────────────────────────────────────────

def find_top_k_by_embedding(
    query_embedding: list[float],
    category: str = "",
    top_k: int = 3,
    min_similarity: float = MIN_SIMILARITY,
) -> list[dict]:
    """Supabase pgvector 向量搜尋；相似度低於 min_similarity 的候選不回傳，無達標則回空 list；服務故障丟 RuntimeError。"""
    return _find_top_k_supabase(query_embedding, category, top_k, min_similarity)


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
    """本地 JSON 關鍵字搜尋（向量比對無候選時使用）。"""
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
