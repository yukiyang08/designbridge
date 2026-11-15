# DesignBridge 常用指令

> 所有指令在專案根目錄 (`DesignBridge/`) 執行

---

## 爬蟲

```powershell
# 爬指定風格（第一次加 --refresh-manifest 同步去重清單）
python -m style_kb.scrapper.scraper_100_images --refresh-manifest --style-filter 鄉村風
python -m style_kb.scrapper.scraper_100_images --style-filter 工業風
python -m style_kb.scrapper.scraper_100_images --style-filter 美式風
python -m style_kb.scrapper.scraper_100_images --style-filter 古典風
python -m style_kb.scrapper.scraper_100_images --style-filter 奢華風

# 限制張數（測試用）
python -m style_kb.scrapper.scraper_100_images --style-filter 鄉村風 --target 50
```

風格對照：現代風 / 北歐風 / 日式風 / 工業風 / 美式風 / 古典風 / 新古典 / 奢華風 / 鄉村風 / 混搭風

---

## 整理 & 上傳

```powershell
# 把 raw/ 依風格分類到 images/<style_id>/（--limit 0 = 不限張數）
python -m style_kb.collection.sort_raw_images --copy --limit 0

# 上傳到 Supabase（dry run 預覽）
python -m style_kb.vector.upload_to_supabase

# 實際上傳（全部）
python -m style_kb.vector.upload_to_supabase --upload

# 只上傳指定風格
python -m style_kb.vector.upload_to_supabase --upload --style country
python -m style_kb.vector.upload_to_supabase --upload --style industrial
```

style_id 對照：modern / nordic / japanese / industrial / american / classic / luxury / country / other

---

## 品質過濾（YOLO）

```powershell
# 掃描全部未評分圖片（背景執行）
python -m style_kb.collection.quality_filter_supabase --run

# 只掃描指定風格
python -m style_kb.collection.quality_filter_supabase --run --style modern

# 重新掃描已評分的圖片
python -m style_kb.collection.quality_filter_supabase --run --reset

# 測試用（只掃 10 張）
python -m style_kb.collection.quality_filter_supabase --run --sample 10
```

---

## Caption 生成（AI）

```powershell
# 預設 dry-run：AI 生成結果暫存到 caption_review.json，不寫 DB
python -m style_kb.collection.generate_captions                # 全部未標記
python -m style_kb.collection.generate_captions --sample 5    # 只跑 5 張
python -m style_kb.collection.generate_captions --style modern # 只跑指定風格

# 直接寫 DB（跳過人工審核，請先確認品質）
python -m style_kb.collection.generate_captions --run
```

Provider（兩者皆使用 Gemini 2.5 Flash）：
  --provider auto    預設，fal.ai 優先，失敗自動切 Gemini API
  --provider fal     只用 fal.ai（FAL_KEY）
  --provider gemini  只用直連 Gemini API（GEMINI_API_KEY）

寫入欄位：`caption_en`、`space`（中文）、`style_id`（覆蓋）、`ai_style_confidence`、`caption_model`、`caption_at`
風格改變時自動搬 Storage 檔案並更新 `image_path` / `image_url`。

---

## 審查伺服器

```powershell
# ── Caption 人工審核模式（先跑 dry-run，再開審核）──
python -m style_kb.collection.review_server --from-json
# 瀏覽器：看 AI 建議（風格 / 空間 / caption）→ 可修改 → 「✓ 批准」寫入 DB
# 「批准全部」一次送出所有卡片
# 批准後從 caption_review.json 移除，重整頁面顯示剩餘數量

# ── 品質審查模式（YOLO 過濾後審查圖片）──
python -m style_kb.collection.review_server           # 全部圖片
python -m style_kb.collection.review_server --flagged-only  # 只看有問題的圖
# 瀏覽器重整 = 自動從 DB 拉最新資料
# 可在卡片底部展開 AI 標記面板，編輯風格 / 空間 / caption 後按「儲存」
```

## 更新審查頁面（靜態）

```powershell
# 重新產生 review.html 並開啟
python -m style_kb.collection.generate_review --open
```

---

## 圖片審查

```powershell
# 生成審查頁面（全部圖片）並開啟瀏覽器
python -m style_kb.collection.generate_review --open

# 只看有問題的圖（score < 1.0）
python -m style_kb.collection.generate_review --flagged-only --open

# 只看指定風格
python -m style_kb.collection.generate_review --style country --open
```

---

## 刪除圖片（Storage + Table 一起）

```powershell
# 從審查頁面複製 IDs 後執行
python -m style_kb.collection.purge_rejected --ids <uuid1>,<uuid2>,...

# 先 dry run 確認
python -m style_kb.collection.purge_rejected --ids <uuid1>,<uuid2>,... --dry-run
```

---

## 查看進度（即時）

```powershell
python -c "
from supabase import create_client; from dotenv import load_dotenv; import os
load_dotenv()
c = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY'])
r = c.table('style_images').select('id', count='exact').not_.is_('quality_score','null').execute()
t = c.table('style_images').select('id', count='exact').execute()
print(f'已評分：{r.count} / {t.count} ({r.count/t.count*100:.0f}%)')
"
```

---

## 各風格張數（DB）

```powershell
python -c "
from supabase import create_client; from dotenv import load_dotenv; import os
load_dotenv()
c = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY'])
rows = c.table('style_images').select('style_id').execute().data
from collections import Counter
for k,v in sorted(Counter(r['style_id'] for r in rows).items(), key=lambda x:-x[1]):
    print(f'  {k:12} {v}')
"
```

---

## 平面圖辨識

```powershell
# 牆線模型權重（部署機必做；約 70 MB，存到 models/cubicasa/，缺檔時退回規則式牆線）
python scripts/fetch_cubicasa_weights.py

# 評估資料（都存到 test/data/，git 已忽略）
python scripts/fetch_cubicasa_subset.py --n 50     # CubiCasa5K 子集，附逐間房標註
python scripts/fetch_tw_floorplans.py --n 30       # 台灣配置圖，附坪數與格局

# 三組切割比較（CubiCasa 官方程式在 ablation_tests/cubicasa5k/，用它的 venv）
ablation_tests/cubicasa5k/.venv/Scripts/python ablation_tests/cubicasa5k/experiment3.py --taiwan test/data/floorplans_tw/*.jpg --cubicasa 50
```

結果與做法見 `test/FLOORPLAN_SEGMENTATION_EXPERIMENT.md`、`docs/FLOORPLAN_ACCURACY.md`。
