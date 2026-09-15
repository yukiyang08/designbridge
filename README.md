# DesignBridge

使用 **LangGraph** 編排的多代理室內設計工作流。現在建議使用 **FastAPI + Vue**。系統規格請見 `docs/DesignBridge.md`，Agent/JSON 規格請見 `docs/SCHEMAS.md`。

## 快速啟動（Vue + FastAPI）

### 1) 安裝依賴

在專案根目錄執行：

```bash
pip install -r requirements.txt
cd frontend
npm install
cd ..
```

### 2) 啟動後端（FastAPI）

在專案根目錄執行：

```bash
uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

後端啟動後可用：
- `http://localhost:8000`
- `http://localhost:8000/docs`（Swagger）

### 3) 啟動前端（Vue）

另開一個終端機，在專案根目錄執行：

```bash
cd frontend
npm run dev
```

前端啟動後瀏覽器開 Vite 顯示的網址（通常是 `http://localhost:5173`）。

### 4) 一鍵啟動（Windows）

可直接執行：

```bat
start_app.bat
```

它會自動開兩個視窗，分別啟動 FastAPI 與 Vue。

## 舊版啟動（Streamlit）

若仍需使用舊測試介面，可在專案根目錄執行：

```bash
streamlit run app.py
```

若指令無效，可改用：

```bash
python -m streamlit run app.py
```

啟動後瀏覽器開 `http://localhost:8501`。

## API 設定（Gemini）

Requirement Analyzer 會優先用 **Google Gemini API** 解析需求；若未設定或失敗，會自動 fallback 到規則式解析。

### 1) 安裝依賴

```bash
pip install -r requirements.txt
pip install supabase
cd frontend && npm install && cd ..
```

### 2. 設定 `.env`

在專案根目錄（有 `api.py` 的那層）新增 `.env`：

```env
PYTHONUTF8=1

# LLM（call_llm 直連 Gemini）
# GEMINI_API_KEY=你的_gemini_api_key

# 圖片生成：雲端 HF Inference（有 token 就不需要本地 GPU）
HF_TOKEN=你的_hf_token

# Supabase 風格向量庫（必填，才能用語意風格搜尋）
SUPABASE_URL=https://你的專案.supabase.co
SUPABASE_SERVICE_ROLE_KEY=你的_service_role_key

# 圖片生成模型：flux | sdxl | sd（預設 sdxl）
DESIGNBRIDGE_LOCAL_MODEL_TYPE=flux

# 動態 routing（選填，開啟後 design_director 改用 LLM 讀 SKILL.md 決策）
# DESIGNBRIDGE_ENABLE_DYNAMIC_ROUTING=true
```

> **PYTHONUTF8=1 在 Windows 必填**，否則中文 emoji print 會 crash。

### 3. 啟動

**Windows 一鍵啟動：**
```bat
start_app.bat
```

會同時開兩個視窗：FastAPI（port 8000）＋ Vue 前端（port 5173）。

**手動啟動：**
```bash
# 視窗 1：後端
uvicorn api:app --reload --host 0.0.0.0 --port 8000

# 視窗 2：前端
cd frontend && npm run dev
```

瀏覽器開 `http://localhost:5173`

---

## API Keys 申請

| Key | 申請位置 | 用途 |
|---|---|---|
| `GEMINI_API_KEY` | [Google AI Studio](https://makersuite.google.com/app/apikey) | LLM 需求分析 + 動態 routing（直連 Gemini） |
| `GEMINI_API_KEYS`（選填） | 同上，逗號分隔多組 | `GEMINI_API_KEY` 失敗（額度用盡等）時依序換下一把 |
| `HF_TOKEN` | [Hugging Face Settings](https://huggingface.co/settings/tokens)（Read 權限）| 雲端圖片生成（Flux/SDXL），免本地 GPU |
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | Supabase 專案設定 | 風格向量庫搜尋 |

---

## 功能說明

### 動態 Routing（SKILL.md 語意調度）

`skills/` 目錄下每個 Agent 都有一份 `SKILL.md`，描述它的能力與適用場景。

- **預設（rule-based）**：根據 `hint_layout`、`hint_style`、`edit_scope` 的數值做 IF-ELSE 判斷
- **LLM-based**：設定 `DESIGNBRIDGE_ENABLE_DYNAMIC_ROUTING=true` 後，由 Gemini 閱讀 SKILL.md 自行語意判斷

LLM routing 的優勢：能理解語意模糊的請求（「讓客廳更有質感」、英文輸入）、處理 edit_scope 與語意衝突的情況，任何失敗自動 fallback 回 rule-based。

### 圖片生成後端優先序

```
1. HF Inference API（有 HF_TOKEN，雲端，不需下載模型）
2. 本地 Flux / SDXL / SD（需 GPU，由 DESIGNBRIDGE_LOCAL_MODEL_TYPE 決定）
3. PIL 佔位圖（開發用 fallback）
```

### 風格搜尋優先序

```
1. Supabase pgvector 語意搜尋（需 SUPABASE_URL + KEY）
2. 本地 ChromaDB 向量庫（需先建立索引）
3. Aggregated JSON fallback（目前只有 modern / country / luxury）
```

---

## 專案結構

```
designbridge/
├── api.py                      # FastAPI 後端
├── app.py                      # Streamlit 測試 UI（舊版）
├── start_app.bat               # Windows 一鍵啟動
├── .env                        # API Keys（不進 git）
├── requirements.txt
├── designbridge/               # 核心模組
│   ├── graph.py                # LangGraph 工作流定義
│   ├── nodes.py                # 所有 Agent 節點實作
│   ├── config.py               # 設定與 feature flags
│   ├── llm.py                  # 統一 LLM 介面（Gemini）
│   ├── router.py               # LLM-based 動態 routing
│   ├── skill_registry.py       # 讀取 SKILL.md 供 Router 使用
│   ├── prompts.py              # Prompt 模板
│   ├── state.py                # LangGraph State schema
│   ├── schemas.py              # 所有 TypedDict 定義
│   ├── style_apply.py          # 風格參數建立（Supabase → ChromaDB → JSON）
│   ├── style_supabase.py       # Supabase 向量搜尋
│   ├── vision.py               # 深度估測 + 語意分割
│   └── inpaint.py              # SD Inpainting 工具
├── skills/                     # Agent 能力文件（SKILL.md）
│   ├── design-director/
│   ├── requirement-analyzer/
│   ├── layout-planner/
│   ├── style-advisor/
│   ├── design-adjuster/
│   ├── image-renderer/
│   └── visual-preprocessor/
├── style_kb/                   # 風格知識庫
│   ├── aggregated/             # 預聚合 JSON（modern / country / luxury）
│   └── styles.py               # 風格 ID 清單
├── frontend/                   # Vue 前端
└── artifacts/                  # 產出（depth / segmentation / render）
```

---

## 3D 場景重建與環景圖

把渲染完成的設計圖 + 深度圖反投影成可互動的 3D 內容。分兩條路，用環境變數切換。

### 深度網格（預設）

`renderer` 之後的 `depth_cloud` node 會把設計圖與深度圖反投影成帶貼圖的三角網格，輸出到
`artifacts/room_mesh/{task_id}/room_mesh.glb`。深度落差超過門檻的相鄰像素不連面，
藉此保留物件邊界。無需額外設定，也不需 API key。

### 環景圖（Text2Room，按需生成）

用 FLUX Fill 逐側 outpaint 把畫面向左右延伸，拼成環景圖。因為單次約需 30–60 秒，
**不放在自動流程裡**：使用者在結果頁按「生成 3D全景模擬」才呼叫 `POST /api/generate-panorama`。
需要 `FAL_KEY`。

### 環境變數

```env
# 反投影前先用 AI 擴圖，填補網格旋轉時邊緣的破洞（需 FAL_KEY）
DESIGNBRIDGE_ENABLE_MESH_OUTPAINT=false
DESIGNBRIDGE_MESH_OUTPAINT_BORDER=0.2      # 四邊各擴張的比例

# 讓自動流程直接跑 Text2Room 環景（預設 false → 只產單視角 GLB）
DESIGNBRIDGE_ENABLE_TEXT2ROOM=false
DESIGNBRIDGE_TEXT2ROOM_AZIMUTHS=-30,30

# 環景每側 outpaint 幾次。預設 1 只覆蓋約 150°，其餘角度在球面上會是鏡射
# 填色而非 AI 補的內容；3 次覆蓋約 300°，4 次可補滿 360°，但每加一次
# 就是多一次 fal.ai 呼叫（+30~60 秒／次）
DESIGNBRIDGE_TEXT2ROOM_STEPS_PER_SIDE=3
```

### 前端

`ResultPanel.vue` 內嵌 `PanoramaViewer`（three.js 球面貼圖 + OrbitControls）與
`PointCloudViewer`（PLY 點雲）。`/api/generate` 回傳 `room_glb_url`、
`room_panorama_url`、`depth_cloud_url` 三個欄位。

---

## 常見問題

**Q：Windows 執行報 UnicodeEncodeError**
→ 確認 `.env` 有 `PYTHONUTF8=1`，且用 `start_app.bat` 啟動（而非直接 `python`）

**Q：style_params 是 None，沒有風格**
→ 確認 `SUPABASE_URL` 和 `SUPABASE_SERVICE_ROLE_KEY` 有設定，且 `pip install supabase` 已執行

**Q：generated_image 是 placeholder（純白圖）**
→ 確認 `HF_TOKEN` 有設定；或本地有 GPU 且 `DESIGNBRIDGE_ENABLE_SDXL_FALLBACK=true`

**Q：動態 routing 沒有作用**
→ 確認 `.env` 有 `DESIGNBRIDGE_ENABLE_DYNAMIC_ROUTING=true`，且 terminal 輸出有 `[design_director] LLM router: ...`

---

## 舊版 Streamlit 介面

```bash
streamlit run app.py
# 或
python -m streamlit run app.py
```

開啟 `http://localhost:8501`
