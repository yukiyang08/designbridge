"""Style-application helpers — Supabase pgvector first, local ChromaDB fallback."""

from __future__ import annotations

from typing import Any

from style_kb.styles import STYLES
from style_kb.style_loras import STYLE_ID_TO_LORA

STYLE_NAME_TO_ID = {name: style_id for style_id, name in STYLES}
STYLE_ID_SET = {style_id for style_id, _ in STYLES}


def resolve_style_loras(style_profile_id: str | None) -> list[dict[str, Any]]:
    """依風格 ID 查表回傳 fal `loras` 參數用的清單；未設定該風格的 LoRA 就回空清單。"""
    if not style_profile_id:
        return []
    entry = STYLE_ID_TO_LORA.get(style_profile_id.lower()) or {}
    path = (entry.get("path") or "").strip()
    if not path:
        return []
    return [{"path": path, "scale": entry.get("scale", 1.0)}]


# ── 工具函式 ──────────────────────────────────────────────────────────────────

def resolve_style_profile_id(
    req: dict[str, Any],
    user_input: dict[str, Any] | None = None,
) -> str | None:
    """從使用者選單或 Gemini 解析結果，決定風格 ID。"""
    user_input = user_input or {}
    explicit_style_id = (user_input.get("style_profile_id") or "").strip()
    if explicit_style_id and explicit_style_id not in ("", "auto"):
        return explicit_style_id if explicit_style_id in STYLE_ID_SET else None

    style_prefs = req.get("style_preferences") or {}
    primary_style = str(style_prefs.get("primary_style") or "").strip()
    if not primary_style:
        return None
    primary_style_lower = primary_style.lower()
    if primary_style_lower in STYLE_ID_SET:
        return primary_style_lower
    return STYLE_NAME_TO_ID.get(primary_style)


def list_available_style_profiles() -> list[dict[str, str]]:
    """列出所有風格（固定清單，不再依賴 aggregated 資料夾）。"""
    return [
        {"style_id": style_id, "style_name": style_name}
        for style_id, style_name in STYLES
    ]


# ── 主要介面 ──────────────────────────────────────────────────────────────────

def build_style_params(
    req: dict[str, Any],
    user_input: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    建立 Renderer 可用的風格參數。

    優先順序：
    1. Supabase pgvector 語義搜尋
    2. 本地 ChromaDB（若 Supabase 不可用）
    """
    if (user_input or {}).get("no_style_reference"):
        return None

    # 使用者自行上傳的風格參考圖（本機路徑，非 URL）：
    # 由 renderer 直接透過 Gemini 分析該圖，不再查 Supabase，避免兩個來源相互干擾
    style_ref = (user_input or {}).get("style_reference_image", "")
    if style_ref and isinstance(style_ref, str) and not style_ref.startswith(("http://", "https://")):
        return None

    style_profile_id = resolve_style_profile_id(req, user_input)
    text_query = (user_input or {}).get("text_prompt", "").strip()
    query = text_query or style_profile_id or "interior design"

    # ── 1. Supabase pgvector 搜尋（文字對比） ──────────────────────────────────
    try:
        from designbridge.style.style_supabase import (
            query_style_images_supabase,
            query_style_image_by_url,
            blend_style_params_supabase,
        )
        if isinstance(style_ref, str) and style_ref.startswith(("http://", "https://")):
            # 使用者已經從候選卡片明確選了某張圖 → 直接用那張的 style_kb，
            # 不要重新搜（重新搜可能搜出別張，導致跟 renderer.py 判斷用的
            # 參考圖不一致，兩張圖的風格描述都被塞進最終 prompt）
            results = query_style_image_by_url(style_ref)
        else:
            results = query_style_images_supabase(
                text_query=query,
                style_id=style_profile_id,
                top_k=3,
            )
        if results:
            return blend_style_params_supabase(results)
    except Exception as e:
        print(f"⚠️  Supabase 向量搜尋失敗，嘗試本地向量庫：{e}")

    # ── 2. 本地 ChromaDB 搜尋 ─────────────────────────────────────────────────
    try:
        from designbridge.style.style_vector import (
            is_vector_store_ready,
            query_style_images,
            blend_style_params,
        )
        if is_vector_store_ready():
            results_local = query_style_images(
                text_query=query,
                style_id=style_profile_id,
                top_k=3,
            )
            if results_local:
                params = blend_style_params(results_local)
                print(f"✅ 本地向量搜尋：top-1 [{results_local[0].doc_id}] score={results_local[0].similarity_score}")
                return params
    except Exception as e:
        print(f"⚠️  本地向量庫查詢失敗：{e}")

    return None
