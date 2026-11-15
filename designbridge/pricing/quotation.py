# designbridge/quotation.py
"""估價 Agent 核心邏輯（Path 2）：
  Gemini Vision bbox 偵測 → bbox 裁切 → CLIP embedding → 向量搜尋 → 細分類篩選／風格加分／同系列去重 → top-3 候選
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from designbridge.render.llm import call_llm
from designbridge.core.schemas import FurnitureCandidate, FurnitureItem, QuotationResultJSON

# 名稱 → 商品庫的大類（覆蓋 Gemini 給的 category）
_CATEGORY_BY_NAME = [
    (r"床頭櫃|床邊櫃|電視櫃|視聽櫃", "storage"),
    (r"單人沙發|沙發椅|主人椅|長凳|長椅", "chair"),
]


# ── Prompts ────────────────────────────────────────────────────────────────────

_IDENTIFY_BBOX_PROMPT = """\
請分析這張室內設計圖，識別圖中所有可見的主要家具與軟裝物件。

請以純 JSON 陣列回傳（不要加任何說明文字），格式如下：
[
  {
    "name_zh": "餐椅",
    "category": "chair",
    "quantity": 2,
    "box_2d": [520, 610, 900, 720],
    "boxes_2d": [[520, 610, 900, 720], [530, 760, 890, 850]]
  }
]

box_2d 為 [ymin, xmin, ymax, xmax]，0–1000 的整數（圖片左上角是 0,0、右下角是 1000,1000）。
框要緊貼物件看得到的輪廓：上下左右都不要留白，也不要把旁邊的家具或地板框進來；
被遮住一部分的家具只框看得到的部分。
同款只列一筆：boxes_2d 列出圖中這款每一件的 box_2d（4 張一樣的餐椅就列 4 個框），
box_2d 填其中最完整、最清楚的那一件；quantity 是實際件數（不確定時填 boxes_2d 的數量）。
category 必須是：sofa / table / chair / lamp / rug / curtain / storage / bed / shelf / other
列出主要且明顯可見的家具與軟裝（至多 10 款），植物、單椅、邊桌、層架也要列，勿過度細分成零件。
天花板燈具（崁燈、軌道燈、吸頂燈、吊燈）即使很小也要列出，不佔上述 10 款名額；
name_zh 用「崁燈」「軌道燈」「吸頂燈」「吊燈」這類名稱。
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


def _quantity_of(raw: dict) -> int:
    try:
        n = int(raw.get("quantity") or 1)
    except (TypeError, ValueError):
        n = 1
    return max(1, min(max(n, len(_boxes_of(raw))), 12))   # 框比件數多就以框為準；上限防 Gemini 亂報


def _box_ratio(box) -> list[float]:
    """Gemini 的 box_2d [ymin, xmin, ymax, xmax]（0–1000）→ [x1, y1, x2, y2]（0~1）；格式不對回傳 []。"""
    try:
        y0, x0, y1, x1 = (max(0.0, min(1000.0, float(v))) / 1000 for v in box)
    except (TypeError, ValueError):
        return []
    if x1 <= x0 or y1 <= y0:
        return []
    return [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]


def _boxes_of(raw: dict) -> list[list[float]]:
    """這款家具每一件的框（0~1 的 [x1, y1, x2, y2]），第一個是拿去比對商品的那件。
    box_2d 用 Gemini 原生格式（比要它回 0~1 小數準）；舊格式 bbox 也接受。"""
    main = _box_ratio(raw["box_2d"]) if raw.get("box_2d") else list(raw.get("bbox") or [])
    rest = [b for b in (_box_ratio(x) for x in raw.get("boxes_2d") or []) if b and b != main]
    return ([main] if len(main) == 4 else []) + rest


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
    if px2 <= px1 or py2 <= py1:
        return None
    # 崁燈這類小物件 bbox 太細（1024 寬的圖上常不到 20px），向量比對沒資訊；往外撐到至少 64px
    px1, px2 = px1 - max(0, 64 - (px2 - px1)) // 2, px2 + max(0, 64 - (px2 - px1)) // 2
    py1, py2 = py1 - max(0, 64 - (py2 - py1)) // 2, py2 + max(0, 64 - (py2 - py1)) // 2
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

def preload_quotation_resources() -> None:
    """先載入 lazy singleton（CLIP / Supabase / 本地 KB），免得多執行緒同時第一次初始化。"""
    from designbridge.pricing.furniture_kb import _get_supabase_client, _load_embeddings, _load_local_kb

    _get_clip_model()
    _get_supabase_client()
    _load_local_kb()
    _load_embeddings()


def _process_furniture_item(raw: dict, img: Any, style_id: str = "") -> tuple[FurnitureItem, bool]:
    """Resolve one detected furniture item to KB candidates. Returns (item, matched_kb).

    Independent per item (own crop/embedding/DB lookup), so build_quotation runs
    this concurrently across all detected items instead of one at a time.
    """
    from designbridge.pricing.furniture_kb import (
        _SMALL_FIXTURE_SUBS, recommend_products, search_kb, subcategories_for,
    )

    name_zh: str = raw.get("name_zh") or raw.get("name_en") or "家具"
    category: str = raw.get("category") or ""
    bbox_ratio: list[float] = (_boxes_of(raw) or [[]])[0]

    candidates: list[FurnitureCandidate] = []
    matched_kb = False

    # shelf → storage（爬蟲分類統一用 storage）
    if category == "shelf":
        category = "storage"
    # 盆栽、抱枕、鏡子、掛畫：Gemini 歸在 other，商品庫放在 decor
    if category == "other" and subcategories_for("decor", name_zh):
        category = "decor"
    # Gemini 的大類偶爾跟商品庫不同（床頭櫃給 table、單人沙發給 sofa），向量搜尋先依大類篩選就撈不到
    for pattern, cat in _CATEGORY_BY_NAME:
        if re.search(pattern, name_zh):
            category = cat
            break

    # ── 嘗試 CLIP + Supabase pgvector ──
    if img is not None and len(bbox_ratio) == 4:
        try:
            crop = crop_image_by_bbox(img, bbox_ratio)
            if crop is not None:
                emb = get_clip_embedding(crop)
                kb_hits = recommend_products(emb, category=category, detected_name=name_zh, style_id=style_id, top_k=3)
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
    # 崁燈、軌道燈本地 JSON 沒有，文字搜尋只會比到吊燈、檯燈這些不同種的燈，寧可走 LLM 估價；
    # other 在商品庫沒有商品，文字搜尋只會撈到名稱相近的別種東西（電視 → 電視櫃）
    if not candidates and category != "other" and not (subcategories_for(category, name_zh) & _SMALL_FIXTURE_SUBS):
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
    # 結果圖上滑到這件家具就標出對應商品（前端 StepResult 的熱區）
    if len(bbox_ratio) == 4:
        item["bbox"] = [round(float(v), 4) for v in bbox_ratio]
    return item, matched_kb


def build_quotation(
    image_path: str,
    req: dict,
    preselected: list[dict] | None = None,
    style_id: str = "",
) -> QuotationResultJSON:
    """
    1. detect_furniture_gemini() → 家具清單 + bbox
    2. 每件家具（平行處理，見 _process_furniture_item）：
       a. 依 bbox 裁切 crop
       b. CLIP embedding
       c. recommend_products() → top-3 候選（向量搜尋後依細分類篩選、渲染圖風格加分、同系列去重）
       d. fallback：search_kb()（本地 JSON）
       e. 最終 fallback：LLM 估算
    3. 併入 preselected（使用者在「家具查詢」頁手動勾選的家具，直接視為已確定候選）
    4. 計算 total_low / mid / high
    5. 回傳 QuotationResultJSON
    """
    from PIL import Image
    from designbridge.core.timing import log_stage, timed_call

    # 取風格提示
    style_hint = ""
    style_pref = req.get("style_preferences") or {}
    if isinstance(style_pref, dict):
        style_hint = style_pref.get("primary_style") or ""

    with ThreadPoolExecutor(max_workers=1) as pre:
        preloading = pre.submit(preload_quotation_resources)
        detected = timed_call("quotation.detect_furniture", None, detect_furniture_gemini, image_path, style_hint)
        preloading.result()

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

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(detected)))) as executor:
        with log_stage("quotation.match_furniture"):
            results = list(executor.map(lambda raw: _process_furniture_item(raw, img, style_id), detected))

    # 同款多件展開成多筆：前端會把候選相同的合併成 ×N，總價逐件相加。
    # 每一件換上自己的框，結果圖上每張餐椅都能滑到；框不夠的沿用比對商品那件的框
    furniture_list: list[FurnitureItem] = []
    for raw, (item, _) in zip(detected, results):
        boxes = _boxes_of(raw)
        for k in range(_quantity_of(raw)):
            copy = {**item}
            if k < len(boxes):
                copy["bbox"] = boxes[k]
            furniture_list.append(copy)
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
