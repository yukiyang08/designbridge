# designbridge/quotation.py
"""估價 Agent 核心邏輯（Path 2）：
  Gemini Vision bbox 偵測 → SAM2/bbox crop → CLIP embedding → Supabase pgvector 搜尋 → top-3 候選
"""

from __future__ import annotations

import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from designbridge.render.llm import call_llm
from designbridge.core.schemas import FurnitureCandidate, FurnitureItem, QuotationResultJSON


# ── Prompts ────────────────────────────────────────────────────────────────────

_IDENTIFY_BBOX_PROMPT = """\
請分析這張室內設計圖，識別圖中所有可見的主要家具與軟裝物件。

請以純 JSON 陣列回傳（不要加任何說明文字），格式如下：
[
  {
    "name_zh": "三人座沙發",
    "category": "sofa",
    "bbox": [0.05, 0.40, 0.55, 0.85]
  }
]

bbox 為 [x1, y1, x2, y2]，值為 0~1 的比例座標（左上角到右下角）。
category 必須是：sofa / table / chair / lamp / rug / curtain / storage / bed / shelf / other
只列出主要且明顯可見的物件（至多 8 件），勿過度細分。
"""

_ESTIMATE_PROMPT = """\
請為以下家具品項估算台灣市場的合理購買價格（新台幣）。
家具：{name_zh}
請直接回答一個整數，不要加任何說明。範例：12000
"""

# ── CLIP model (lazy singleton) ────────────────────────────────────────────────

_clip_model: Any = None


def _get_clip_model():
    global _clip_model
    if _clip_model is None:
        from sentence_transformers import SentenceTransformer
        _clip_model = SentenceTransformer("clip-ViT-B-32")
    return _clip_model


# ── Helper functions ───────────────────────────────────────────────────────────

def _parse_json_array(text: str) -> list[dict]:
    text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`")
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return []


def _parse_price(text: str) -> int | None:
    nums = re.findall(r"\d[\d,]*", text.strip())
    if nums:
        try:
            return int(nums[0].replace(",", ""))
        except ValueError:
            pass
    return None


# ── Core functions ─────────────────────────────────────────────────────────────

# 當 Gemini 失敗時，依房間類型給預設家具清單
_ROOM_DEFAULTS: dict[str, list[tuple[str, str]]] = {
    "living_room":  [("沙發", "sofa"), ("茶几", "table"), ("電視櫃", "storage"), ("落地燈", "lamp")],
    "bedroom":      [("床架", "bed"), ("床頭櫃", "table"), ("衣櫃", "storage"), ("檯燈", "lamp")],
    "dining_room":  [("餐桌", "table"), ("餐椅", "chair"), ("餐廳燈", "lamp")],
    "kitchen":      [("廚房收納", "storage"), ("餐椅", "chair")],
    "study":        [("書桌", "table"), ("書椅", "chair"), ("書架", "storage"), ("桌燈", "lamp")],
    "children_room":[("兒童床", "bed"), ("書桌", "table"), ("書椅", "chair"), ("書架", "storage")],
}


def _fallback_furniture(room_type: str) -> list[dict]:
    """Gemini 失敗時的備用清單，不含 bbox（直接用 KB 文字搜尋）。"""
    defaults = _ROOM_DEFAULTS.get(room_type) or _ROOM_DEFAULTS["living_room"]
    return [{"name_zh": name, "category": cat, "bbox": []} for name, cat in defaults]


def detect_furniture_gemini(image_path: str, style_hint: str = "") -> list[dict]:
    """
    Gemini Vision 偵測家具，回傳 [{"name_zh", "category", "bbox":[x1,y1,x2,y2]}]。
    bbox 座標為 0~1 的比例值。失敗時回傳空 list（由 build_quotation 補 fallback）。
    """
    prompt = _IDENTIFY_BBOX_PROMPT
    if style_hint:
        prompt += f"\n圖片風格提示：{style_hint}"
    try:
        response = call_llm(prompt, images=[image_path], json_mode=True)
        items = _parse_json_array(response)
        return items if isinstance(items, list) else []
    except Exception as e:
        print(f"[quotation] Gemini furniture detection failed: {e}")
        return []


def get_clip_embedding(image_crop) -> list[float]:
    """
    用 CLIP ViT-B/32 對 PIL Image crop 做 image embedding，回傳 512 維 list（L2 normalized）。
    """
    import numpy as np
    model = _get_clip_model()
    emb = model.encode(image_crop, convert_to_numpy=True)
    norm = float(np.linalg.norm(emb))
    if norm > 0:
        emb = emb / norm
    return emb.tolist()


def crop_image_by_bbox(img, bbox_ratio: list[float]):
    """
    依 bbox_ratio [x1,y1,x2,y2]（0~1）從 PIL Image 裁切出家具 crop。
    若 bbox 超出邊界或太小則回傳 None。
    """
    w, h = img.size
    x1, y1, x2, y2 = bbox_ratio
    px1, py1 = int(x1 * w), int(y1 * h)
    px2, py2 = int(x2 * w), int(y2 * h)
    # 至少 20×20 px
    if px2 - px1 < 20 or py2 - py1 < 20:
        return None
    px1, py1 = max(0, px1), max(0, py1)
    px2, py2 = min(w, px2), min(h, py2)
    return img.crop((px1, py1, px2, py2))


def _estimate_price_llm(name_zh: str) -> int:
    """LLM 估算市場價格（fallback）。"""
    prompt = _ESTIMATE_PROMPT.format(name_zh=name_zh)
    try:
        response = call_llm(prompt)
        price = _parse_price(response)
        return price if price else 5000
    except Exception:
        return 5000


# ── Main build function ────────────────────────────────────────────────────────

def _process_furniture_item(raw: dict, img: Any) -> tuple[FurnitureItem, bool]:
    """Resolve one detected furniture item to KB candidates. Returns (item, matched_kb).

    Independent per item (own crop/embedding/DB lookup), so build_quotation runs
    this concurrently across all detected items instead of one at a time.
    """
    from designbridge.pricing.furniture_kb import find_top_k_by_embedding, search_kb

    name_zh: str = raw.get("name_zh") or raw.get("name_en") or "家具"
    category: str = raw.get("category") or ""
    bbox_ratio: list[float] = raw.get("bbox") or []

    candidates: list[FurnitureCandidate] = []
    matched_kb = False

    # shelf → storage（爬蟲分類統一用 storage）
    if category == "shelf":
        category = "storage"

    # ── 嘗試 CLIP + Supabase pgvector ──
    if img is not None and len(bbox_ratio) == 4:
        try:
            crop = crop_image_by_bbox(img, bbox_ratio)
            if crop is not None:
                emb = get_clip_embedding(crop)
                kb_hits = find_top_k_by_embedding(emb, category=category, top_k=3)
                if kb_hits:
                    matched_kb = True
                    sims = [round(float(h.get("similarity") or 0), 4) for h in kb_hits]
                    print(f"[quotation] '{name_zh}' ({category}) 向量比對 top-{len(kb_hits)} 相似度：{sims}")
                    for hit in kb_hits:
                        candidates.append({
                            "id": str(hit.get("id") or ""),
                            "name": hit.get("name") or name_zh,
                            "price": int(hit.get("price") or 0),
                            "purchase_url": hit.get("url") or "",
                            "product_image_url": hit.get("image_url") or "",
                            "similarity": round(float(hit.get("similarity") or 0), 4),
                        })
                else:
                    print(f"[quotation] '{name_zh}' ({category}) 無相似度達門檻的候選，改用文字搜尋 fallback")
        except Exception as e:
            print(f"[quotation] CLIP/vector search error for '{name_zh}': {e}")

    # ── Fallback：本地 JSON 關鍵字搜尋 ──
    if not candidates:
        text_hits = search_kb(name_zh, category=category, top_k=3)
        if text_hits:
            matched_kb = True
            for hit in text_hits:
                candidates.append({
                    "id": str(hit.get("id") or ""),
                    "name": hit.get("name") or name_zh,
                    "price": int(hit.get("price") or 0),
                    "purchase_url": hit.get("url") or "",
                    "product_image_url": hit.get("image_url") or "",
                    "similarity": 0.5,
                })

    # ── Fallback：LLM 估算 ──
    if not candidates:
        estimated = _estimate_price_llm(name_zh)
        candidates.append({
            "id": "",
            "name": name_zh,
            "price": estimated,
            "purchase_url": "",
            "product_image_url": "",
            "similarity": 0.0,
        })

    item: FurnitureItem = {
        "detected_name": name_zh,
        "category": category,
        "candidates": candidates,
        "selected_index": 0,
    }
    return item, matched_kb


def build_quotation(
    image_path: str,
    req: dict,
    preselected: list[dict] | None = None,
) -> QuotationResultJSON:
    """
    1. detect_furniture_gemini() → 家具清單 + bbox
    2. 每件家具（平行處理，見 _process_furniture_item）：
       a. 依 bbox 裁切 crop
       b. CLIP embedding
       c. find_top_k_by_embedding() → top-3 IKEA 候選（Supabase pgvector）
       d. fallback：search_kb()（本地 JSON）
       e. 最終 fallback：LLM 估算
    3. 併入 preselected（使用者在「家具查詢」頁手動勾選的家具，直接視為已確定候選）
    4. 計算 total_low / mid / high
    5. 回傳 QuotationResultJSON
    """
    from PIL import Image
    from designbridge.pricing.furniture_kb import _get_supabase_client, _load_local_kb, _load_embeddings

    # 取風格提示
    style_hint = ""
    style_pref = req.get("style_preferences") or {}
    if isinstance(style_pref, dict):
        style_hint = style_pref.get("primary_style") or ""

    detected = detect_furniture_gemini(image_path, style_hint)

    # Gemini 失敗（或圖片無法辨識）→ 用房間類型備用清單
    if not detected:
        room_type = (req.get("meta") or {}).get("room_type") or "living_room"
        detected = _fallback_furniture(room_type)
        print(f"[quotation] Gemini 失敗，使用備用清單（{room_type}，{len(detected)} 件）")

    try:
        img = Image.open(image_path).convert("RGB")
    except Exception as e:
        print(f"[quotation] cannot open image: {e}")
        img = None

    # 預先載入 lazy singleton（CLIP model / Supabase client / 本地 KB 快取），
    # 避免多執行緒同時第一次觸發初始化造成 race condition。
    _get_clip_model()
    _get_supabase_client()
    _load_local_kb()
    _load_embeddings()

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(detected)))) as executor:
        results = list(executor.map(lambda raw: _process_furniture_item(raw, img), detected))

    furniture_list: list[FurnitureItem] = [item for item, _ in results]
    kb_match_count = sum(1 for _, matched in results if matched)

    # ── 使用者手動勾選的家具（家具查詢頁）優先併入，視為已確定候選 ──
    for sel in (preselected or []):
        furniture_list.insert(0, {
            "detected_name": sel.get("name") or "家具",
            "category": sel.get("category") or "",
            "candidates": [{
                "id": str(sel.get("id") or ""),
                "name": sel.get("name") or "",
                "price": int(sel.get("price") or 0),
                "purchase_url": sel.get("url") or "",
                "product_image_url": sel.get("image_url") or "",
                "similarity": 1.0,
            }],
            "selected_index": 0,
        })
        kb_match_count += 1

    # ── 計算三檔預算（以各品項第 0 候選價格為基準）──
    total_mid = sum(
        item["candidates"][0]["price"] if item["candidates"] else 0
        for item in furniture_list
    )
    total_low = int(total_mid * 0.8)
    total_high = int(total_mid * 1.3)

    return {
        "furniture_list": furniture_list,
        "total_low": total_low,
        "total_mid": total_mid,
        "total_high": total_high,
        "currency": "TWD",
        "kb_match_count": kb_match_count,
    }
