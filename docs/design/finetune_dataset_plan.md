# Flux Dev Finetune 資料集整備計畫

## 目標

讓 Flux Dev 在收到正確的英文 prompt 後，生成符合**台灣室內設計美學**的高品質渲染圖。

這是 **Domain Adaptation**，不是風格分類器：
- LoRA 教模型「怎麼畫」— 台灣室設的打光、材質、構圖、品質水準
- Prompt 決定「畫什麼」— 風格、空間、元素由 caption 自然描述
- 不需要 trigger word，不需要 per-style LoRA

```
輸入 prompt:  "japanese living room, oak slat TV wall, floor-to-ceiling glass"
Base Flux Dev → 生成普通日式客廳
Finetuned LoRA → 生成符合台灣室設美學品質的日式客廳（同樣的 prompt）
```

---

## 現況盤點

### 資料庫 (`public.style_images`)
| 項目 | 數量 |
|------|-----:|
| 總圖片數 | 2,041 |
| 有完整 style_kb（含 caption）| 547 |
| 缺少 style_kb / space / embedding | 1,494（73%）|
| 已有可用英文 caption | 260 |

### 風格分布
| 風格 | 筆數 | 備註 |
|------|-----:|------|
| modern | 797 | |
| nordic | 416 | |
| other | 249 | 需處理 |
| japanese | 213 | |
| industrial | 104 | |
| american | 99 | |
| luxury | 58 | |
| country | 42 | |
| classic | 63 | ✅ neoclassic（24）已合併（2026-06-26）|
| ~~neoclassic~~ | ~~24~~ | ✅ 已合併至 classic |

> `other`（249 筆）需處理，其餘風格全部混入同一訓練集。

### 現有工具
- `style_kb/collection/quality_filter.py` — 本地圖片品質篩選
- `style_kb/extraction/extract_style_kb.py` — Gemini 生成 style_kb JSON（含 caption）
- `style_kb/extraction/label_space_supabase.py` — 空間類型標記
- `style_kb/migration/migrate_neoclassic_storage.py` — ✅ neoclassic → classic 搬移腳本（已執行）

---

## Phase 0：Schema 更新

```sql
ALTER TABLE public.style_images
  ADD COLUMN IF NOT EXISTS width         INTEGER,
  ADD COLUMN IF NOT EXISTS height        INTEGER,
  ADD COLUMN IF NOT EXISTS file_size_kb  FLOAT,
  ADD COLUMN IF NOT EXISTS quality_score FLOAT,   -- 0.0–1.0，綜合品質分數
  ADD COLUMN IF NOT EXISTS quality_flags JSONB,   -- {"blur": true, "too_dark": false, ...}
  ADD COLUMN IF NOT EXISTS caption_en    TEXT,    -- Flux 訓練用英文 caption
  ADD COLUMN IF NOT EXISTS is_selected   BOOLEAN DEFAULT FALSE;  -- 最終入選訓練集
```

---

## Phase 1：品質篩選

品質是這個計畫的核心。LoRA 學到什麼取決於你餵給它什麼，一張模糊或構圖差的圖會污染整個訓練。

### 篩選標準

| 項目 | 門檻 | 說明 |
|------|------|------|
| 解析度 | ≥ 800×600 | 低於此訓練效果差 |
| 檔案大小 | ≥ 100KB | 太小通常是縮圖 |
| 長寬比 | ≤ 2.5:1 | 過於扁或細長排除 |
| 模糊 | Laplacian variance ≥ 50 | 偵測手震/失焦 |
| 重複圖 | MD5 + pHash | 完全重複 + 近似重複 |

### 擴充現有 quality_filter.py 支援 Supabase

```python
# style_kb/collection/quality_filter_supabase.py
import httpx, cv2, numpy as np
from PIL import Image
import io

def compute_blur_score(img: Image.Image) -> float:
    """Laplacian variance — 越低越模糊，< 50 視為模糊。"""
    gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())

def check_image(image_url: str) -> dict:
    resp = httpx.get(image_url, timeout=15)
    img = Image.open(io.BytesIO(resp.content))
    w, h = img.size
    flags = {
        "low_res":    w < 800 or h < 600,
        "too_small":  len(resp.content) < 100 * 1024,
        "bad_ratio":  max(w, h) / min(w, h) > 2.5,
        "blur":       compute_blur_score(img) < 50,
    }
    score = 1.0 - (sum(flags.values()) / len(flags))
    return {"width": w, "height": h, "file_size_kb": len(resp.content)/1024,
            "quality_score": score, "quality_flags": flags}
```

### 預估通過數量

保守估計通過率 70%，扣掉 `other` 249 張：  
(2,041 − 249) × 70% ≈ **1,250 張有效圖**

---

## Phase 2：Caption 整理

每張圖需要一句準確的英文描述，告訴模型「這張圖畫的是什麼」。

### 2-1 遷移現有 caption（547 筆）

`style_kb.ai_params.prompts.positive` 已是品質良好的英文描述，直接搬到 `caption_en`：

```sql
UPDATE public.style_images
SET caption_en = style_kb->'ai_params'->'prompts'->>'positive'
WHERE style_kb IS NOT NULL
  AND style_kb->'ai_params'->'prompts'->>'positive' IS NOT NULL;
```

### 2-2 補生成 1,494 筆缺失 caption

擴充現有 `extract_style_kb.py`，改為直接讀 `image_url` 而非本地檔案：

```python
# 對 style_kb IS NULL 的圖，從 image_url 直接餵 Gemini/Claude
# 生成後寫回 style_kb 欄位，同步填入 caption_en
```

**預估成本：**
- Gemini 1.5 Flash：1,494 張 × ~$0.0004 ≈ **~$0.6 USD**
- Claude Haiku：1,494 張 × ~$0.001 ≈ **~$1.5 USD**

### 2-3 Caption 格式規範

只描述畫面內容，不加任何 trigger word：

```
[風格] [空間], [主要視覺元素], [材質], [色調], [打光], [氛圍]

範例：
nordic living room, light oak modular shelving wall, linen sofa in warm white,
sheepskin throw, matte white walls, soft diffused daylight from floor-to-ceiling
windows, calm and airy atmosphere

japanese bedroom, tatami platform bed, shoji screen partition, warm oak tones,
indirect cove lighting, minimal furniture, serene and grounded atmosphere
```

---

## Phase 3：處理 `other` 分類（249 筆）

這些圖的風格標記不明確，需要決定如何處理。

### 先查看構成

```sql
SELECT source_meta->>'style' AS original_style, COUNT(*)
FROM public.style_images
WHERE style_id = 'other'
GROUP BY 1
ORDER BY 2 DESC;
```

### 處理選項

| 方案 | 做法 | 適用情境 |
|------|------|---------|
| AI 重分類 | 用 Gemini/Claude 看圖歸入現有 9 個風格 | 圖片品質好但標記錯誤 |
| 品質夠就直接納入 | 生成 caption 後不管風格標籤，一樣訓練 | Domain adaptation 不在乎風格標籤 |
| 全部排除 | 不處理，is_selected = FALSE | 先求穩，之後再補 |

> 因為訓練目標是美學品質而非風格分類，只要圖片品質夠好、caption 描述準確，`other` 的圖一樣可以貢獻訓練。

---

## Phase 4：選定訓練集

### 目標總量

Flux Dev LoRA 建議訓練量：**200–800 張**  
- 太少（<100）：學不夠，效果弱
- 太多（>1000）：過擬合風險，且訓練時間長

建議目標：**400–600 張**，確保各風格都有代表。

### 取樣策略

不強制每風格等量，以品質為主要篩選依據：

```sql
-- 標記通過品質篩選且有 caption 的圖
UPDATE public.style_images
SET is_selected = TRUE
WHERE quality_score >= 0.6
  AND caption_en IS NOT NULL
  AND style_id != 'other';   -- other 視 Phase 3 結果決定

-- 若 modern/nordic 數量過多，隨機取樣上限
UPDATE public.style_images
SET is_selected = FALSE
WHERE style_id = 'modern'
  AND is_selected = TRUE
  AND id NOT IN (
    SELECT id FROM public.style_images
    WHERE style_id = 'modern' AND is_selected = TRUE
    ORDER BY quality_score DESC
    LIMIT 150
  );
```

---

## Phase 5：匯出格式

### fal.ai Flux Dev 格式（ZIP）

每張圖搭配同名 `.txt` 檔：

```
training_data/
├── img_0001.jpg
├── img_0001.txt    ← "nordic living room, light oak shelving..."
├── img_0002.jpg
├── img_0002.txt
└── ...
```

### 匯出腳本

```python
# style_kb/export/export_for_flux.py
import zipfile, httpx
from supabase import create_client

def export_training_zip(output_path: str):
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    rows = supabase.table("style_images")\
        .select("image_url, caption_en")\
        .eq("is_selected", True)\
        .not_.is_("caption_en", "null")\
        .execute().data

    with zipfile.ZipFile(output_path, "w") as zf:
        for i, row in enumerate(rows):
            img_bytes = httpx.get(row["image_url"], timeout=15).content
            stem = f"img_{i:04d}"
            zf.writestr(f"{stem}.jpg", img_bytes)
            zf.writestr(f"{stem}.txt", row["caption_en"])

    print(f"匯出完成：{len(rows)} 張 → {output_path}")
```

---

## 執行 Checklist

```
前置作業
[x] neoclassic（24）合併至 classic → classic 現有 63 筆（2026-06-26）
    Storage + Table 均已更新，所有 URL 可存取

Phase 0：Schema
[ ] 執行 ALTER TABLE 新增欄位
    (width, height, file_size_kb, quality_score, quality_flags, caption_en, is_selected)

Phase 1：品質篩選
[ ] 寫 quality_filter_supabase.py（讀 image_url）
[ ] 跑全部 2,041 筆，寫回 quality_score / width / height / quality_flags

Phase 2：Caption
[ ] SQL 遷移現有 547 筆 caption_en
[ ] 補跑 extract_style_kb 對 1,494 筆缺失圖（從 image_url 直接讀）
[ ] 補完 space 空間類型標籤（caption 描述需要）

Phase 3：other 分類
[ ] 查 source_meta 分布，決定處理方式（重分類 / 直接納入 / 排除）

Phase 4：選定訓練集
[ ] 設定 quality_score 門檻
[ ] 執行 is_selected 標記
[ ] 人工抽樣確認 ~30 張品質與 caption 準確度

Phase 5：匯出
[ ] 寫 export_for_flux.py
[ ] 匯出 ZIP，確認圖文配對正確
[ ] 上傳 fal.ai 開始訓練
```

---

## 注意事項

**訓練參數（Flux Dev LoRA 建議）**
- Learning rate：`1e-4`
- Steps：1,000–2,000
- Batch size：1–2
- Rank：16–32

**評估方式**
- 訓練完後用 10–20 個沒見過的 prompt 測試
- 對比 base Flux Dev 與 finetuned 的輸出差異
- 關注：材質細節、打光質感、空間比例感

**版權**
來源為 100interior.com，finetune 用於商業產品前請確認版權條款。
