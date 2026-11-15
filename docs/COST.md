# 流程成本與耗時分析

**全部是實測，不是估算。** 兩個資料來源：

- `usage_events`（[`core/usage.py`](../designbridge/core/usage.py)）—— 每次 Gemini／fal 呼叫的
  token、費用、耗時、排隊秒數。743 筆，2026-11-05 ～ 11-15。
- `designs.record.timing_runs`（[`core/timing.py`](../designbridge/core/timing.py) 的 `collect_stages`）
  —— 每次生成的逐階段耗時。420 筆 run，2026-10-18 ～ 11-15；本文只取 2026-11 之後的樣本。

> 取樣偏差：**只有成功的生成會存進 `designs`**，等 180 秒才逾時失敗的請求不在裡面，
> 所以耗時的中位數比真實體感樂觀。費用則是每次呼叫都記，沒有這個問題。

---

## 1. 總覽：一個使用者動作要多久、多少錢

| 動作 | 耗時（中位數） | 成本 | 樣本 |
|---|---|---|---|
| **生成一張圖 ＋ 自動估價** | **115s** | **$0.0851** | n=13 |
| └ 只有生圖 | 105s | $0.0784 | n=47 |
| └ 只有估價 | 10.2s | $0.0056 | n=30 |
| 換風格（整張重生＋估價） | 67s | $0.0851 | n=5 |
| 局部微調（inpaint） | 30.3s | $0.035 | n=10 |
| 照片搬家具 | 26.4s | $0.075 | n=2 |
| 產生全景圖 | 39.3s | $0.100 | n=1 |
| 上傳整層平面圖 → 辨識完成 | 38.4s | $0.0243 | n=5 |
| └ 其中單間家具辨識（6 間背景並行） | 17.4s | $0.0104 | n=6 |
| 照片入口的家具偵測 | 6.0s | $0.0032 | n=14 |

**整層 6 間全部設計完：約 13 分鐘、約 $0.53（NT$ 16）。**
`= 辨識 38s/$0.024 + 6 × (生圖 105s + 估價 10s) / 6 × $0.085`

---

## 2. 生成一張圖：逐階段（n=47）

時間來自 `timing_runs`，成本來自 `usage_events` 的同類呼叫中位數。

| # | 階段 | 耗時 中位 | p90 | 最長 | 成本 | 外部呼叫 |
|---|---|---|---|---|---|---|
| 1 | `requirement_analyzer` | 5.55s | 17.8s | 76.1s | $0.0034 | Gemini ×1 |
| 2 | `visual_preprocessing`（無照片） | 0.00s | 0.2s | 13.2s | $0 | — |
| 2a | └ `.depth_estimation`（有照片） | 4.55s | 4.8s | — | $0 | 本機 Depth Anything V2 |
| 2b | └ `.segmentation`（有照片） | 6.72s | 12.2s | — | $0 | 本機 UPerNet，與 2a **並行**（合計 6.75s） |
| 3 | `layout_and_style.style_search` | 1.93s | 5.6s | 32.3s | $0 | Supabase pgvector |
| 4 | `layout_and_style.reproject` | 8.14s | **50.3s** | **115.8s** | $0 | 純本機 NumPy ⚠️ |
| 5 | `composer` | 2.23s | 22.7s | 129.1s | $0.0034 | Gemini ×1（矛盾時 ×2） |
| 6 | **`renderer`（總計）** | **82.77s** | 153.3s | 224.1s | **$0.075** | |
| 6a | └ `.layout_conditions` | 0.00s | 14.5s | 33.7s | $0 | 前端預算過就命中快取 |
| 6b | └ `.layout_depth_map` ＋ `.layout_edge_map` | 1.5s | — | — | $0 | 本機投影 |
| 6c | └ `.camera_select` | 13.36s | 31.6s | 31.6s | $0 | 相機評分（n=7）⚠️ |
| 6d | └ **`.fal_flux_depth_controlnet`** | **90.20s** | 142.2s | 181.8s | $0.075 | fal（n=32，主要路徑） |
| 6e | └ `.flux_controlnet_depth_fal`（照片深度） | 28.79s | 184.7s | 184.7s | $0.075 | fal（n=6） |
| 6f | └ `.flux_fal`（純文字備援） | 5.88s | 11.5s | — | $0.003 | fal schnell（n=8） |
| 7 | `clip_evaluator.evaluate` | 1.16s | 1.7s | 2.2s | $0 | 本機 CLIP |
| 8 | 估價（另一支 API，自動觸發） | 10.21s | 18.0s | — | $0.0056 | Gemini ×1 |

### 時間軸（中位數）

```
RA 5.6s → vision 0s → style 1.9s → reproject 8.1s → composer 2.2s
  → renderer 82.8s ┬ 條件圖＋相機 ~14s
                   ├ fal 排隊    28.2s   ← 控制不了
                   └ fal 算圖    40.6s
  → clip 1.2s → 〔估價 10.2s〕
  ──────────────────────────────────────── 約 115s / $0.085
```

**renderer 佔 72%，其中 fal 排隊佔整體的 25%。**

---

## 3. 四個入口的完整路徑

### 入口一 A：上傳平面圖（整層）

| 步驟 | 耗時 | 成本 | 呼叫 |
|---|---|---|---|
| 上傳 + 品質檢查 | <1s | $0 | 本機 |
| `/api/detect-rooms` | 約 28s | $0.0083～0.088 | 種子 1 ∥ CubiCasa 2～3.5s → 切割 3～10s → 逐區 **3 票並行** → 門窗 1 |
| `/api/parse-floor-plan` ×6（背景 3 條並行） | 17.4s | $0.0104 | 每間 1 次 Gemini（$0.0017、約 3s） |
| 每間設計 | 115s | $0.0851 | 見第 2 節 |
| **整層 6 間合計** | **約 13 分鐘** | **$0.53** | |

### 入口一 B：自動生成格局

| 步驟 | 耗時 | 成本 |
|---|---|---|
| `/api/generate-room-plan` | <1s | $0（純幾何，不呼叫 AI） |
| 每間設計（多跑 layout agent 提案＋審查） | 115s＋ | $0.0851＋ |

省掉整層辨識的 $0.024，但每間多一次 layout agent。
`/api/generate-layout` 只有 1 個樣本（$0.0573、119.7s），而且是 `thinking_budget=-1` 時代的，**不可信**。

### 入口二：改造現有空間（照片）

| 步驟 | 耗時 | 成本 |
|---|---|---|
| `/api/photo-layout`（家具偵測 ∥ 本機深度／分割） | 6.0s | $0.0032 |
| 換風格 `restyle`（整張重生） | 約 67s | $0.0851 |
| 搬家具 `/api/photo-move` | 26.4s | $0.075 |
| 局部微調 | 30.3s | $0.035 |

實測整串（偵測＋生圖＋估價）中位數 **220s / $0.092**（n=5）。

### 入口三：從想法開始（跳過排版）

沒有照片也沒有 scene_graph，走 2D 平面圖投影或純文字。純文字備援只要 5.9s / $0.003，
**但那條路不吃任何結構條件，出來的圖跟使用者的空間無關**。

---

## 4. 每一個外部呼叫的單價與耗時

### Gemini（`gemini-3.6-flash`，$0.75／$3.75 每百萬 token，輸入／輸出）

思考 token 算輸出價。近五天中位數：輸入 1,606、輸出 312 token；**輸入佔 43%、輸出佔 57%**。

| 呼叫（程式位置） | 每次成本 | 每次耗時 | 備註 |
|---|---|---|---|
| `requirement_analyzer`（[requirement.py:255](../designbridge/core/nodes/requirement.py#L255)） | $0.0034 | 5.6s | 提示詞 4,173 字 |
| `composer`（[composer.py:178](../designbridge/core/nodes/composer.py#L178)） | $0.0034 | 2.2s | `max_tokens=360` |
| 估價 `detect_furniture`（[quotation.py:147](../designbridge/pricing/quotation.py#L147)） | $0.0056 | 4.9s | 帶 1 張渲染圖 |
| 估價 `_estimate_price_llm` | $0.0003 | <1s | 只有配對不到的品項 |
| 單房家具辨識（[floorplan_parse.py:141](../designbridge/layout/floorplan_parse.py#L141)） | $0.0017 | 3.0s | 思考 2048，有內容快取 |
| 房間種子點（[floorplan_parse.py:298](../designbridge/layout/floorplan_parse.py#L298)） | $0.0021 | 3.6s | |
| 逐區辨識（[floorplan_parse.py:497](../designbridge/layout/floorplan_parse.py#L497)） | $0.0062 | 5.8s | **×3 票，並行** |
| 門窗辨識（[floorplan_upload_plan.py:342](../designbridge/layout/floorplan_upload_plan.py#L342)） | ~$0.006 | ~6s | 與門弧幾何並行 |
| 照片家具偵測（[photo_fengshui.py:114](../designbridge/layout/photo_fengshui.py#L114)） | $0.0033 | 6.3s | |
| layout agent 提案＋審查（[layout_agent.py:23、31](../designbridge/layout/layout_agent.py#L23)） | $0.029 ⚠️ | 43s ⚠️ | n=2，思考 -1 時代 |
| 微調指令解析（[adjuster.py:43](../designbridge/core/nodes/adjuster.py#L43)） | 小 | 3.1s | `max_tokens` 300／500 |
| 風格參考圖分析（[render_prompt.py:101](../designbridge/render/render_prompt.py#L101)） | 小 | — | 只有自行上傳參考圖才跑 |
| CLIP 翻譯（[clip_evaluator.py:40](../designbridge/render/clip_evaluator.py#L40)） | ≈0 | 3.1s | prompt 是英文就跳過 |

**延遲幾乎只跟輸出 token 有關，跟輸入長度無關：**

| 輸出 token（含思考） | n | 中位數 | p90 |
|---|---|---|---|
| 0–300 | 222 | 3.1s | 7.2s |
| 300–1k | 262 | 6.0s | 9.9s |
| 1k–2k | 58 | 9.9s | 15.8s |
| 2k–4k | 122 | 17.0s | 24.5s |
| 4k+ | 38 | **33.3s** | 66.1s |

所以 `thinking_budget=-1` 不只貴 4 倍，還慢 2～3 倍（11-07 那批實驗單次最長 182 秒、$0.046）。

### fal（按百萬像素**無條件進位**計費；輸出長邊固定 1024，最大 1.0 MP → 每張都是 1 MP 的錢）

| 用途 | 端點 | 每張 | 總耗時 中位 | 排隊 | 純算圖 |
|---|---|---|---|---|---|
| 主要生圖（深度＋邊緣 ControlNet） | `fal-ai/flux-general` | **$0.075** | **68.8s** | 28.2s | 40.6s |
| 照片搬家具（挖洞補背景） | `flux-general/inpainting` | $0.075 | 26.4s | 0s | 26.4s |
| 全景圖 | `flux-pro/v1/fill` | $0.050 | 20.2s | 4.0s | 16.2s |
| 局部微調／擴圖 | `flux-lora-fill` | $0.035 | 6.5s | 2.9s | 3.6s |
| 純文字備援 | `flux/schnell` | $0.003 | 2.9s | 1.7s | 1.2s |
| 商品 3D 模型 | `hunyuan3d/v2` | 另計 | — | — | 未使用 |

### GPU（Modal 自架，目前 `MODAL_MODE=off` 沒有在用）

Modal **按秒計費**，只有容器在跑時才收；每次呼叫結束後容器還會多活「閒置等待」那段
（`profiles.py` 的 `scaledown`），這段推論有計費、官方沒明說。

| GPU | 每秒 | 冷啟動 | 純算圖（Union 42 步） | 純算圖（路徑① 20 步） | 用在哪個模式 |
|---|---|---|---|---|---|
| **L40S** | $0.000542 | 約 54s | 18～21s | 7.8s | `dev`（閒置 60s 關） |
| **H100** | $0.001097 | 約 40s | 8～9s | 3.7s | `demo`（閒置 600s 關） |
| A100-80GB | $0.000694 | 約 45s | 19～21.5s | — | 不用（跟 L40S 一樣慢、貴 28%） |

一個工作階段的費用 ＝ (冷啟動 ＋ 閒置等待) × 每秒價 ＋ 張數 × 算圖秒數 × 每秒價：

| 模式 | 固定成本（冷啟動＋閒置） | 每張加計 | 1 張 | 3 張 | 10 張 |
|---|---|---|---|---|---|
| `dev`（L40S，閒置 60s） | $0.062 | $0.011 | $0.073 | $0.094 | $0.172 |
| `demo`（H100，閒置 600s） | **$0.702** | $0.010 | $0.712 | $0.732 | $0.801 |
| fal（對照） | $0 | $0.075 | $0.075 | $0.225 | $0.750 |

- **`dev` 從第 2 張起就比 fal 便宜**，10 張只要 fal 的 23%；而且算圖 20s 比 fal 的 68.8s（含排隊）快。
- **`demo` 的 600 秒閒置是陷阱**：每次刷新 /studio 都會暖機，一個工作階段固定 $0.7，
  可能一張圖都沒生。展示前再開，展示完立刻關。
- 實測 `modal.render` 中位數 6.08s（n=3），`renderer.flux_controlnet_depth_modal` 59.0s（含冷啟動）。
- 細節與部署指令見 [MODAL_GPU.md](MODAL_GPU.md)；**品質尚未驗收**，對外不要寫成已完成。

### 本機（CPU，不花錢但花時間）

開發機沒有 GPU，下面全部跑在 12 核 CPU 上：

| 模型／運算 | 耗時 中位 | 用在哪 |
|---|---|---|
| LaMa 補背景 | 11.9s | 局部微調、照片搬家具 |
| UPerNet 語義分割 | 6.7s | 視覺前處理（與深度並行） |
| Depth Anything V2 | 4.6s | 視覺前處理 |
| SAM2 分割 | 3.7s | 微調選取（首次載模型 61s） |
| CubiCasa5K 牆體預測 | 2～3.5s | 平面圖辨識 |
| CLIP 評分 | 1.2s | 每張圖生成後 |
| 房間切割（NumPy） | 3～10s | 平面圖辨識 |

這些是「免費」的部分，但加起來佔照片入口與平面圖辨識相當大的比例。
換成 GPU 可以砍掉大半，但目前沒有本機 GPU。

---

## 5. 瓶頸排序

### 省時間

1. **fal 排隊 28.2s（佔 25%）** —— 控制不了，只能換 provider 或自架。
2. **fal 算圖 40.6s** —— 步數是直接槓桿（`FAL_DEPTH_STEPS=42`），但
   [CONTROLNET_PARAM_TEST.md](experiments/CONTROLNET_PARAM_TEST.md) 實測 14 步品質最差、20 步最好，不要盲砍。
3. **`reproject` p90 50.3s、最長 115.8s** —— 純 NumPy、不碰網路卻能跑近兩分鐘，
   **整條鏈裡最該查的異常**，家具多時會爆。
4. **`camera_select` 13.4s** —— 同一個房間佈局沒變就不該重算，可快取。
5. **估價的 10s 疊在生圖之後** —— 改成點開才估，感知時間直接少 10 秒。
6. **`composer` p90 22.7s、最長 129s** —— 偵測到矛盾會回頭再問一輪。

### 省錢

1. **估價快取** —— 估價是 LLM 最大單項（近五天 $0.100／20 次）。`swapStyle` 存進
   `styleSwapCache` 的是估價前的物件（[render.js:231](../frontend/src/composables/design-flow/render.js#L231)），
   切回看過的風格會對同一張圖再送一次 $0.0056。三行可修。
2. **估價改點開才跑** —— 試風格的圖不需要報價。
3. **背景預跑只跑前 2～3 間** —— `prefetchUploadedRooms` 把整層每間都辨識（$0.0017×N），
   使用者通常只設計 2～3 間。
4. **別再用 `thinking_budget=-1` 跑整批** —— 11-07 一天就燒掉 $2.31。
5. **少生沒人要的圖** —— 每張 $0.075 是所有 Gemini 優化加起來的好幾倍。
   整層批次套風格一次就是 N × $0.075。

> **比例要記住**：近五天生圖 $1.74（78%）、Gemini $0.50（22%）。
> 十天資料裡 Gemini 看似佔 54%，那是 11-07 跑平面圖實驗的一次性支出。

---

## 6. 記帳本身的兩個問題

1. **`flux/schnell` 單價記錯 25 倍** —— 它不在 `usage.py` 的 `FAL_PRICE_PER_MP` 裡，
   被套用預設 $0.075，fal 官方是 $0.003／MP。補一行 `"fal-ai/flux/schnell": 0.003`。
   十天帳面 $7.52 實際約 $7.09。
2. **背景執行緒記不到 `route`** —— 695 次 LLM 有 442 次 route 是空的（跑在 thread pool 裡，
   `usage.start_request` 的 contextvar 沒跟著進去）。金額正確，但分不出是哪個 API 花的，
   所以第 3 節的「每路由成本」會低估，真實值要看第 1 節用時間分群算出來的數字。

## 來源

- [fal flux-general](https://fal.ai/models/fal-ai/flux-general)（$0.075／MP）、
  [fal flux/schnell](https://fal.ai/models/fal-ai/flux-1/schnell/llms.txt)（$0.003／MP）、
  [fal 計價文件](https://docs.fal.ai/documentation/model-apis/pricing)（按 MP 進位）
- Gemini 3.6 Flash 單價（第三方彙整，官方頁未直接取得，促銷價 2027-01 起翻倍）：
  [requesty](https://www.requesty.ai/models/vertex/gemini-3.6-flash)、
  [Gemini API Pricing 2026](https://www.maximem.ai/blog/gemini-api-pricing-2026)
- 本專案實測：`usage_events`（743 筆）、`designs.record.timing_runs`（420 筆）
