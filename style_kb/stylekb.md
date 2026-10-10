# Supabase style_kb 現況（DesignBridge）

## 1. 目前資料流（Runtime）

1. `build_style_params()` 先嘗試 Supabase 向量檢索（`designbridge/style_apply.py`）。
2. Supabase 回傳候選後，`blend_style_params_supabase()` 會以 **top-1 命中圖片** 為主（`designbridge/style_supabase.py`）。
3. 下載 top-1 的 `image_url` 到本地 `artifacts/style_ref/`，作為 `reference_image_path`。
4. Renderer 實際使用控制圖優先序：
   - 使用者上傳 `style_reference_image`
   - Supabase 下載後的 `reference_image_path`
   - depth map（若前兩者都沒有）

---

## 2. style params 來源優先序（已更新）

目前依照最新規則，只保留兩層：

- **Priority 1：命中圖片的 `style_kb`**
  - 透過 `image_url + style_id` 回查 `style_images.style_kb`
  - 優先讀取：
    - `style_kb.ai_params.prompts.positive`
    - `style_kb.ai_params.prompts.negative`
    - `style_kb.ai_params.recommended_ip_adapter_weight`
    - `style_kb.description`
    - `style_kb.visual_elements.materials`

- **Priority 2：`_STYLE_PROMPTS` fallback**
  - 若 `style_kb` 缺欄位或不存在，回退到 `style_id` 對應模板
  - `style_id` 不在字典內時，再 fallback 到 `modern`

> 注意：目前 **不使用 top-k 融合**（不做 similarity 加權合成參數）。

---

## 3. 當前 `blend_style_params_supabase()` 行為

- 只採用 `results[0]`（top-1）決定 `style_profile_id`
- `style_prompt` / `negative_prompt`：先吃 `style_kb`，缺漏才吃 `_STYLE_PROMPTS`
- `style_strength`：
  - 優先用 `recommended_ip_adapter_weight`（並 clamp 到 0~1）
  - 否則預設 `0.8`
- `style_summary`：來自 `style_kb.description`
- `material_recommendations`：由 `style_kb.visual_elements.materials` 組合
- `source`：
  - 有讀到 `style_kb`：`supabase_style_kb`
  - 否則：`supabase_vector`

---

## 4. Supabase 失敗時 fallback

`build_style_params()` 只走 Supabase 向量檢索；失敗則回傳 `None`（僅用基礎 prompt 生成）。

---

## 5. 與 IP-Adapter 的關係（目前還未使用IP-Adapter）

- 目前 `style_kb` 提供的是「可讀、可控」參數（prompt/材質/摘要/強度）。
- 若後續接入 IP-Adapter，建議保留此層：
  - `style_kb` 作為顯式控制
  - IP-Adapter 作為隱式視覺風格注入

這樣可以兼顧可控性（可調參）與視覺一致性（更像參考圖）。

---

## 6. Supabase 風格圖片張數統計（`style_images`）

更新時間：2026-04-29（專案：`DesignBridge`）

- `american`: 86
- `classic`: 21
- `country`: 19
- `industrial`: 48
- `japanese`: 100
- `luxury`: 54
- `modern`: 100
- `neoclassic`: 20
- `nordic`: 100

總計：548 張
