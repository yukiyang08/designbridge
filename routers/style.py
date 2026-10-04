"""Style KB search/preview, furniture catalog and style profile endpoints."""
import os
from typing import Optional

from fastapi import APIRouter

from designbridge.style.style_apply import list_available_style_profiles
from style_kb.styles import STYLES

router = APIRouter()

_supabase_client = None

def _get_supabase():
    global _supabase_client
    if _supabase_client is None:
        from supabase import create_client
        _supabase_client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        )
    return _supabase_client

@router.get("/api/style-search")
def search_styles(
    query: str = "",
    style_id: str = "",
    top_k: int = 3,
    diverse: bool = False,
):
    """向量搜尋最相似的風格參考圖，回傳多筆候選供使用者選擇。

    diverse=True（前端在使用者沒填風格描述、也沒手動選風格時傳入）：每個風格各取一張，
    避免通用 fallback 查詢字（房型中文字/"interior design"）只集中命中一兩種風格。
    """
    from designbridge.style.style_supabase import _STYLE_PROMPTS
    from style_kb.styles import STYLES
    style_name_map = {sid: sname for sid, sname in STYLES}

    sid = style_id.strip() or ""
    q = query.strip() or sid or "interior design"
    try:
        from designbridge.style.style_supabase import query_style_images_supabase, query_style_images_diverse

        client = _get_supabase()
        if diverse and not sid:
            # per_style=3（不是 1）是刻意留給前端「下一輪」用的池子——向量搜尋本身是
            # 決定性的，同樣的查詢字重打一次結果不會變，所以一次多要幾張，前端就能在
            # 池子裡輪替顯示，不用每次都重打一樣的 query 卻拿到一樣的結果。
            results = query_style_images_diverse(text_query=q, per_style=3)[: min(top_k, 24)]
        else:
            results = query_style_images_supabase(
                text_query=q,
                style_id=sid or None,
                top_k=min(top_k, 24),
            )
        if not results:
            return []

        # 批次取 style_kb（兩筆查詢，不用 N+1）
        image_urls = [r.image_url for r in results]
        kb_res = client.table("style_images").select("image_url,style_kb").in_("image_url", image_urls).execute()
        kb_map = {r["image_url"]: r.get("style_kb") for r in (kb_res.data or [])}

        candidates = []
        for row in results:
            url = row.image_url          # DB join key
            display_url = row.display_url  # actually-reachable URL to show/round-trip
            s_id = row.style_id
            style_kb = kb_map.get(url)
            fallback = _STYLE_PROMPTS.get(s_id, _STYLE_PROMPTS.get("modern", {}))

            description = None
            tags: list[str] = []
            positive_prompt = fallback.get("positive", "")
            negative_prompt = fallback.get("negative", "")
            colors: dict = {}
            materials: list[str] = []

            if style_kb and isinstance(style_kb, dict):
                desc_raw = style_kb.get("description")
                # v2 schema: {"zh": "...", "en": "..."}；前端顯示用中文版
                description = desc_raw.get("zh") if isinstance(desc_raw, dict) else desc_raw
                tags_raw = (style_kb.get("style_info") or {}).get("tags")
                zh_tags = tags_raw.get("zh") if isinstance(tags_raw, dict) else tags_raw
                if isinstance(zh_tags, list):
                    tags = [str(t) for t in zh_tags if t][:5]
                ai = style_kb.get("ai_params") or {}
                prompts = ai.get("prompts") or {}
                positive_prompt = prompts.get("positive") or positive_prompt
                negative_prompt = prompts.get("negative") or negative_prompt

                # 資訊卡片（hover/點擊 ⓘ）用的補充資料，同樣來自 style_kb
                visual = style_kb.get("visual_elements") or {}
                colors = visual.get("colors") or {}
                for m in visual.get("materials") or []:
                    t = isinstance(m, dict) and m.get("type")
                    if t and t not in materials:
                        materials.append(t)
                materials = materials[:5]

            source_meta = {}
            candidates.append({
                "style_id": s_id,
                "style_name": style_name_map.get(s_id, source_meta.get("style", s_id)),
                "image_url": display_url,
                "similarity": round(float(row.similarity), 4),
                "description": description,
                "tags": tags,
                "positive_prompt": positive_prompt,
                "negative_prompt": negative_prompt,
                "colors": colors,
                "materials": materials,
            })
        return candidates
    except Exception as e:
        print(f"⚠️ style-search error: {e}")
        return []


@router.get("/api/style-preview")
def get_style_preview(
    query: str = "",
    style_id: str = "",
):
    """根據文字語意搜尋最符合的風格參考圖（Supabase pgvector），供前端即時預覽。"""
    sid = style_id.strip() or ""
    q = query.strip() or sid or "interior design"
    try:
        from designbridge.style.style_supabase import query_style_images_supabase

        results = query_style_images_supabase(
            text_query=q,
            style_id=sid or None,
            top_k=1,
        )
        if not results:
            return {"image_url": None}
        row = results[0]
        style_name = row.style_name or row.style_id
        return {
            "image_url": row.display_url,
            "style_name": style_name,
            "similarity": round(row.similarity, 4),
        }
    except Exception as e:
        print(f"⚠️ style-preview error: {e}")
        return {"image_url": None}


# ── 家具查詢 ──────────────────────────────────────────────────────────────────

@router.get("/api/furniture/categories")
def get_furniture_categories():
    """回傳家具 KB 中所有分類。"""
    from designbridge.pricing.furniture_kb import list_categories
    return list_categories()


@router.get("/api/furniture")
def get_furniture(
    category: str = "",
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
):
    """瀏覽 / 篩選家具清單（分類 + 價位區間）。"""
    from designbridge.pricing.furniture_kb import list_furniture
    return list_furniture(category=category, min_price=min_price, max_price=max_price)


@router.get("/api/style-profiles")
def get_style_profiles():
    # 優先回傳磁碟上已有聚合檔的風格
    available = list_available_style_profiles()
    if available:
        return [{"style_id": s["style_id"], "style_name": s["style_name"]} for s in available]
    # fallback：回傳 STYLES 定義的完整清單
    return [{"style_id": sid, "style_name": sname} for sid, sname in STYLES]
