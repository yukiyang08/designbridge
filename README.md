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
uvicorn api:app --reload --reload-exclude "*/artifacts/*" --host 0.0.0.0 --port 8000
```

`--reload-exclude` 是必要的：`artifacts/` 底下每次生成都會不斷寫入新的圖片／glb 檔，若不排除，`--reload` 會偵測到這些檔案變動而重啟整個後端 process（打斷正在進行的生成、清空已載入的模型）。

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
uvicorn api:app --reload --reload-exclude "*/artifacts/*" --host 0.0.0.0 --port 8000

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


### 圖片生成後端優先序

```
有深度圖：fal.ai FLUX depth ControlNet → HF Kontext
只有 2D 平面圖：fal.ai 投影深度 ControlNet → HF Kontext（以平面圖當引導）
純文字：HF Inference → fal.ai FLUX schnell
全部失敗：回報 render_error，不產圖
```

### 風格搜尋

Supabase pgvector 語意搜尋（需 `SUPABASE_URL` + KEY）；失敗時不帶風格參考生成。

---

## 專案結構

```
designbridge/
├── api.py                      # FastAPI 後端
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
│   ├── style_apply.py          # 風格參數建立（Supabase pgvector）
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

## 環景圖

### Text2Room（按需生成）

用 FLUX Fill 逐側 outpaint 把畫面向左右延伸，拼成環景圖。因為單次約需 30–60 秒，
**不放在自動流程裡**：使用者在結果頁按「生成 3D全景模擬」才呼叫 `POST /api/generate-panorama`。
需要 `FAL_KEY`。

---

## 常見問題

**Q：Windows 執行報 UnicodeEncodeError**
→ 確認 `.env` 有 `PYTHONUTF8=1`，且用 `start_app.bat` 啟動（而非直接 `python`）

**Q：style_params 是 None，沒有風格**
→ 確認 `SUPABASE_URL` 和 `SUPABASE_SERVICE_ROLE_KEY` 有設定，且 `pip install supabase` 已執行

**Q：generated_image 是 placeholder（純白圖）**
→ 確認 `HF_TOKEN` 有設定；或本地有 GPU 且 `DESIGNBRIDGE_ENABLE_SDXL_FALLBACK=true`

