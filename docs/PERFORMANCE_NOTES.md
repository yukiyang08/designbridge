# DesignBridge 效能研究筆記

> 基於實際跑起來的 dev server log 分析，非猜測。所有結論都對照過當前活的原始碼（重構後的
> `designbridge/core/`、`designbridge/layout/`、`designbridge/render/`、`designbridge/pricing/`
> 套件路徑，非重構前已刪除的扁平檔案）。

## 結論先講：瓶頸在哪

單次生成 **1~5 分鐘**，時間全部花在**依序**呼叫外部 API（Gemini / Supabase / fal.ai），
不是本地 CPU/GPU 運算。本地唯一的運算（CLIP embedding、佈局幾何求解）都是毫秒級，不是問題。

**目前影響最大的單一因素：`hint_layout` 是否為 true**（使用者描述是否指定了家具位置/擺放），
它同時決定了要不要跑 layout_agent，也決定了 renderer 要用哪一種生圖 backend——後者的差距是
**30 倍**。

## 各階段耗時分解

實測樣本數字（已排除首次冷啟動下載模型造成的離群值），依 pipeline 順序列出：

| 階段 | 典型範圍 | 變動來源 |
|---|---|---|
| `requirement_analyzer` | 14.5~18.7s | 固定一次 Gemini 呼叫，變動小 |
| `visual_preprocessing`（無照片） | 0.00s | 沒傳 `initial_image` 時直接跳過 |
| `visual_preprocessing.depth_estimation`（**有**照片） | ⚠️ 未實測——本次對話所有 log 都是無照片情境，一律 0.00s，沒有真實樣本 | 本地跑 `Depth-Anything-V2-Large-hf`（[config.py:84](../designbridge/core/config.py#L84)），[`vision.py:48`](../designbridge/layout/vision.py#L48) 用 `@lru_cache` 快取模型，但**沒有像 CLIP evaluator 一樣在 startup 就預熱**（[warmup.py](../designbridge/core/warmup.py) 沒有涵蓋），所以該 server process 第一次收到帶照片的請求時，要多付一次模型載入（甚至下載）成本，之後才會變快 |
| `visual_preprocessing.depth_to_layout`（**有**照片） | ⚠️ 未實測，預期快（純 NumPy/OpenCV 對深度圖做 blob 偵測，[`depth_to_layout.py`](../designbridge/layout/depth_to_layout.py)，不呼叫任何 API） | — |
| `layout_and_style.style_search` | 0~17s（首次 53.6s，冷啟動離群值） | Supabase pgvector 查詢，一般網路延遲 |
| `layout_and_style.layout_agent`（僅 `hint_layout=True` 才執行） | 75~134s | 每輪未收斂就重呼叫一次 Gemini；家具數量多時單輪 LLM 輸出量大，即使 1 輪收斂仍可達 84.77s |
| `layout_and_style_agent`（節點總計） | 0s（`hint_layout=False`）／53~137s（`hint_layout=True`） | = style_search + layout_agent（如有執行） |
| `renderer.gemini_style_analysis`（僅無 KB 快取文字時執行） | 12.87s | 有 Supabase KB 描述快取時整段跳過 |
| `renderer` — `flux_fal`（無 depth，純文字生圖） | 5.01~7.12s | 最快路徑，`hint_layout=False` 時預設走這條 |
| `renderer` — `hf_kontext`（Kontext LoRA，有 depth） | 15~32s | `hint_layout=True` 但 `LAYOUT_DEPTH_CONTROL_BACKEND≠controlnet` 時走這條 |
| `renderer` — `flux_controlnet_depth_fal`（真 ControlNet，有 depth） | **125.42~154.36s** | `hint_layout=True` 且預設值 `LAYOUT_DEPTH_CONTROL_BACKEND=="controlnet"` 時走這條，目前觀察到的單一最大耗時項，可調參數見下方 1.1 節 |
| `clip_evaluator` | 0.3~6.8s | 有 `translate` 子步驟（非英文 prompt 需先翻譯）時偏高，純評分（`evaluate`）本身 <0.5s |
| `quotation_agent` | 35~70s（首次冷啟動曾見 718s，CLIP 模型下載造成，非常態） | 已用 `ThreadPoolExecutor` 平行處理家具比對；`detect_furniture_gemini()` 序列跑在平行迴圈之前，是剩餘瓶頸候選 |

**單次生成總時長對照兩種典型情境：**

| 情境 | 總時長估算 | 決定性因素 |
|---|---|---|
| `hint_layout=False` | 約 55~75s | renderer 走最快的 `flux_fal`，layout 整段跳過 |
| `hint_layout=True`，`LAYOUT_DEPTH_CONTROL_BACKEND=controlnet`（預設） | 約 3~5 分鐘 | layout_agent 迭代 + renderer 用最慢的 ControlNet |
| `hint_layout=True`，若切換成 `hf_kontext` | 約 1.5~2.5 分鐘 | 省下 renderer 那 120 秒左右的差距 |

## 各階段根因與現況

### 1. Renderer backend 選擇 —— 目前最大單一瓶頸

**檔案**：[`designbridge/core/nodes/renderer.py:239-269`](../designbridge/core/nodes/renderer.py#L239)

Backend 依優先序決定：

```
hint_layout=True 且有 projected depth 且 LAYOUT_DEPTH_CONTROL_BACKEND=="controlnet"
    → flux_controlnet_depth_fal（FLUX.1-dev + 真正 ControlNet-Depth，~154s，幾何約束最強）
否則有 depth 且有 HF_TOKEN
    → hf_kontext（Kontext LoRA，~15~32s，較輕量）
否則
    → flux_fal（fal.ai schnell 純文字生圖，~5~7s，完全不吃 depth）
```

**根因**：[`designbridge/core/config.py:74`](../designbridge/core/config.py#L74)
`LAYOUT_DEPTH_CONTROL_BACKEND` 預設值就是 `"controlnet"`。只要 `hint_layout=True`
（使用者提到具體家具位置），系統預設就會走最貴的那條路。

**可調參數（換路徑）**（未套用，待決定）：
把環境變數 `DESIGNBRIDGE_LAYOUT_DEPTH_CONTROL_BACKEND` 改成非 `"controlnet"` 的值，
會自動走 `hf_kontext`，154s → 15~32s（快 5~10 倍）。
**權衡**：ControlNet 對 layout_agent 算出的座標約束力更強；Kontext LoRA 較寬鬆，
家具位置可能沒那麼精準貼合規劃結果，需要實測畫質/佈局精準度後再決定要不要全面切換。

#### 1.1 若不想放棄 ControlNet：參數層面還能調什麼

**檔案**：[`designbridge/render/render_backends.py:453-522`](../designbridge/render/render_backends.py#L453)
（`_render_flux_controlnet_depth_fal`），對應設定在
[`designbridge/core/config.py:78-82`](../designbridge/core/config.py#L78)。

| 參數 | 環境變數 | 預設值 | 對速度的影響 | 對品質的影響 |
|---|---|---|---|---|
| `num_inference_steps` | `DESIGNBRIDGE_FAL_CONTROLNET_STEPS` | `20` | **唯一直接影響速度的參數**——步數與耗時大致成正比，20 步是這條路徑慢的主因之一 | 步數少可能細節較粗糙、偽影變多 |
| `guidance_scale` | `DESIGNBRIDGE_FAL_CONTROLNET_GUIDANCE` | `3.5` | 幾乎不影響速度（CFG 的雙路計算是固定開銷，不隨數值變動） | 數值越高越貼近 prompt，但過高會過曝/失真 |
| `conditioning_scale`（`depth_conditioning_scale`） | 由 LLM 輸出決定，投影深度時上限被 `DESIGNBRIDGE_PROJECTED_DEPTH_MAX_CONDITIONING_SCALE`（預設 `0.5`）鎖住 | — | 不影響速度，只是去噪過程中的權重 | 越高越貼合深度圖幾何，過高在投影深度（非真實照片深度）上會出現「家具浮空盒子」偽影，這也是為何合成深度要特意鎖上限 |

**結構性原因（參數調不動的部分）**：這條路徑呼叫的是 `fal-ai/flux-general`（FLUX.1-dev 架構），
本身就需要比 `flux_fal` 用的 FLUX.1-**schnell**（蒸餾模型，1~4 步就能出圖）多好幾倍的步數才能收斂，
這是模型架構差異，不是單靠調參數能抹平的——`num_inference_steps` 調到個位數，FLUX.1-dev 出圖品質會明顯崩壞，
不像 schnell 本來就是為少步數設計的。

**建議測試方向**：與其整條路徑放棄（換 `hf_kontext`），可以先試著把 `DESIGNBRIDGE_FAL_CONTROLNET_STEPS`
從 20 調到 10~12，實測看時間降幅（理論上接近砍半）跟畫質是否還能接受，作為「保留 ControlNet 幾何約束
但沒那麼慢」的折衷方案。

### 2. `layout_agent` 迭代 —— 次要瓶頸，波動大

**檔案**：[`designbridge/layout/layout_agent.py:731-839`](../designbridge/layout/layout_agent.py#L731)

每輪迭代跑幾何求解 + 打分（快，純數學），沒達 `SCORE_THRESHOLD=0.65` 就重新呼叫一次 Gemini
重規劃家具（慢，網路 I/O），最多跑 `LAYOUT_MAX_ITER`（預設 3，[config.py:92](../designbridge/core/config.py#L92)，
環境變數 `DESIGNBRIDGE_LAYOUT_MAX_ITER`）輪。

**觀察到的行為不一致**：
- 有時 1 輪就收斂（`iterations=1 acceptance_rate=100%`），但**單輪本身**耗時仍可能高達 84.77s
  （13 件家具的複雜 JSON 生成，LLM 輸出量大，非重試造成）。
- 有時 3 輪都不收斂（`acceptance_rate=0%`），代表多打的 2 次 LLM 呼叫是純浪費。

**待驗證**：是否要調低 `LAYOUT_MAX_ITER`、調整 `SCORE_THRESHOLD`，或是針對「單輪 LLM 生成本身
就慢」（家具數量多時）另外優化 prompt / 輸出格式。

### 3. `quotation_agent` —— 已經部分優化過

**檔案**：[`designbridge/pricing/quotation.py:239-303`](../designbridge/pricing/quotation.py#L239)

⚠️ **修正前一版筆記的錯誤**：這裡**已經用 `ThreadPoolExecutor` 平行處理每件家具**
（[quotation.py:281](../designbridge/pricing/quotation.py#L281)，`max_workers=min(8, len(detected))`），
不是原本以為的序列迴圈（先前分析引用到重構前已刪除的舊檔案，該版本才是序列的）。

即使已平行化，實測仍要 35~70s，推測剩餘瓶頸是：
- `detect_furniture_gemini()`（[quotation.py:260](../designbridge/pricing/quotation.py#L260)）——單一
  Gemini vision 呼叫，在平行迴圈**之前**，序列跑，本身可能就要 5~15s。
- 平行批次中最慢的單一項目（例如需要 LLM 估價 fallback 的品項）決定了整批的下限。

**待驗證**：量測 `detect_furniture_gemini` 單獨耗時，以及平行批次中個別項目的耗時分佈，
才能確認還有沒有值得優化的空間。

### 4. Gemini API 呼叫關閉 thinking mode —— 已套用

**檔案**：[`designbridge/render/llm.py:105`](../designbridge/render/llm.py#L105)（`_gemini_client_and_config`）、
[`designbridge/core/config.py:23-25`](../designbridge/core/config.py#L23)

被 `requirement_analyzer`、`layout_agent` 每輪、`clip_evaluator.translate`、
`detect_furniture_gemini` 共用。已加上
`thinking_config=types.ThinkingConfig(thinking_budget=Config.GEMINI_THINKING_BUDGET)`，
`GEMINI_THINKING_BUDGET` 預設 `0`（關閉），可用環境變數 `DESIGNBRIDGE_GEMINI_THINKING_BUDGET` 覆寫。

**待驗證**：套用後尚未實測前後對照的耗時差異——上面表格裡 `requirement_analyzer` /
`layout_agent` 的耗時數字是**套用前**的樣本，之後應重新量測確認實際降幅。

## 排除項（確認過不是問題）

- **GPU**：渲染全部走雲端（fal.ai / HF Inference），本地沒有跑擴散模型運算，加 GPU 對現有瓶頸沒幫助。
  唯一 GPU 有意義的情境是遠端渲染全部失敗、fallback 到本地下載 33GB FLUX.1-schnell
  （`ENABLE_FLUX_FALLBACK`，[renderer.py:293](../designbridge/core/nodes/renderer.py#L293)，最後手段），
  但正常情況不會走到這條路。
  **例外**：`visual_preprocessing`（見上表，僅在使用者有上傳照片時執行）是全流程唯一一段真的在本地跑
  torch 模型推理的地方（深度估計 + 語意分割），[`vision.py:35-45`](../designbridge/layout/vision.py#L35)
  會偵測 `torch.cuda.is_available()` 自動用 GPU。這段的實際耗時本次對話沒有樣本（所有 log 都是無照片
  的文字生成情境），如果常態會有使用者上傳照片，這裡才是真正該量測、GPU 才可能有感的地方。
- **首次模型下載**（CLIP 605MB、bge-m3 等）：一次性成本，`~/.cache/huggingface` 快取後不會重複發生。
- **架構改成純 multi-agent 協商 / 合併成單一 agent**：都不會解決現有瓶頸，目前的線性 pipeline
  （`designbridge/core/graph.py`，共享 state blackboard 模式）符合這個場景本來就該串行依賴的性質；
  真正該做的是把管線內能平行的部分平行化（`quotation_agent` 已示範這個做法）。

## 檔案位置對照（重構後，避免混淆）

| 功能 | 現在的路徑 |
|---|---|
| Graph 定義 | `designbridge/core/graph.py` |
| State schema | `designbridge/core/state.py` |
| Config | `designbridge/core/config.py` |
| 各 graph node（requirement / layout_and_style / renderer / quotation…） | `designbridge/core/nodes/*.py` |
| Layout 幾何求解器 | `designbridge/layout/layout_agent.py` |
| Render backend 實作（fal.ai / HF Inference / local） | `designbridge/render/render_backends.py` |
| Gemini LLM 呼叫封裝 | `designbridge/render/llm.py` |
| 報價/家具比對 | `designbridge/pricing/quotation.py`、`designbridge/pricing/furniture_kb.py` |
| 風格向量搜尋 | `designbridge/style/style_apply.py`、`style_vector.py`、`style_supabase.py` |

> 舊的扁平檔案（`designbridge/nodes.py`、`layout_agent.py`、`render_backends.py`、`graph.py`、
> `llm.py`、`state.py` 直接放在 `designbridge/` 底下）在這次重構中已被刪除，純屬歷史包袱，
> 不要再引用。

## 待辦優先序（尚未套用的修復）

1. **`LAYOUT_DEPTH_CONTROL_BACKEND` 切換評估**（影響最大，154s → 15~32s，但需先評估畫質/精準度權衡）
2. ~~Gemini `thinking_budget=0`~~ —— 已套用（見上方第 4 節），待重新量測實際降幅
3. **`LAYOUT_MAX_ITER` 調整 / 收斂邏輯優化**（視觀察到的 acceptance_rate 決定要不要調）
4. **量測 `detect_furniture_gemini` 與平行批次的個別耗時**（確認 quotation_agent 還有沒有優化空間）
5. **`layout_and_style.style_search` 離群值待查**：這次實測跑到 **107.87s**，比筆記記錄的
   0~17s（甚至冷啟動離群值 53.6s）都高出一截，且這次是有 Supabase 命中（`score=0.590`），
   不是走 fallback。可能是 Supabase 網路延遲當下特別差，或有其他未觀察到的因素，值得下次重現時
   多留意是否穩定重現。
