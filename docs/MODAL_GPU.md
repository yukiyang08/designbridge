# Modal GPU 自架生圖（取代 fal 的 ControlNet 生圖）

狀態：已接進後端，`.env` 開關預設關閉，失敗或逾時自動退回 fal。**「品質與 fal 一樣好」還沒驗收**（見第 5 節），對外不要寫成已完成。

## 1. 用法

`.env` 只有一個變數，**沒設 = `off` = 全走 fal**：

| `DESIGNBRIDGE_MODAL_MODE` | 用途 | 後端 | 部署 |
|---|---|---|---|
| `off`（預設） | 不用 Modal | 全走 fal | — |
| `dev` | 平常開發、省錢 | 開 Modal、不暖機 | L40S、閒置 60 秒關 |
| `demo` | 展示 | 開 Modal、進 /studio 就暖機 | H100、閒置 600 秒關 |

- 改模式要**重啟後端**；GPU／閒置要**重新部署**：`python scripts/modal_flux/deploy.py`（`--show` 只看設定）。想調整 GPU 或閒置時間，改 `scripts/modal_flux/profiles.py`。
- 部署是全隊共用、同名覆蓋，**只由一個人部署**。其他成員只要 `pip install modal`、`python -m modal setup` 登入、自己 `.env` 設 `DESIGNBRIDGE_MODAL_MODE`，不需要 Hugging Face token 或自己的 GPU。

確認有用到 Modal：生圖時後端 log 出現 `☁️ Modal GPU ... 推理中` 再接 `✅ Modal GPU 完成`；出現 `退回 fal` 表示失敗，原因在括號裡。耗時面板的 Modal 那列會標「冷啟動」或「暖機」。

## 2. 加速機制

- **暖機**（只有 `demo`）：進 /studio 時前端呼叫 `/api/modal-warmup`，後端叫起 Union 路徑的容器，啟動時預載 8 個風格 LoRA。暖機本身要錢，所以 `dev` 不暖機。
- **條件圖預先計算**：停在風格選擇頁時，前端呼叫 `/api/prefetch-layout-conditions`，後端先算好 Union 路徑的相機評分、邊緣圖與深度圖；按生圖時命中就直接讀檔，家具／房間尺寸／輸出比例變了會自動重算。
- 換風格預設不再補跑深度估計（`DESIGNBRIDGE_STYLE_SWAP_DEPTH_LOCK=true` 才跑）。

## 3. 覆蓋範圍

兩條 ControlNet 路徑都接了（同一個部署，用 `mode` 切換）：

| 路徑 | 何時用 | 模型 | 步數 |
|---|---|---|---|
| ① `flux_controlnet_depth_*` | 已有深度圖 | 深度 + 邊緣兩個 ControlNet（`two`） | 20 |
| ② `flux_depth_controlnet_*` | 沒深度圖、有家具配置，用 2D 平面圖投影 | Union-Pro（`union`） | 42 |

局部修改與擴圖另有一個部署 `designbridge-edit`（FLUX.1 Fill dev，`scripts/modal_flux/edit_app.py`），跟上面的主渲染分開，部署互不覆蓋：

1. 下載權重（一次，約 34 GB；HF token 的帳號要先在 FLUX.1-Fill-dev 模型頁同意授權）：`modal run scripts/modal_flux/edit_app.py::download`
2. 部署：`python scripts/modal_flux/deploy.py --app edit`
3. 用的人 `.env` 加 `DESIGNBRIDGE_MODAL_EDIT=true`（另外 `DESIGNBRIDGE_MODAL_MODE` 要是 dev／demo），重啟後端；log 出現 `Modal GPU（designbridge-edit）FLUX Fill dev` 就是走自架

局部修改預設模型已改為 Fill dev（`fal-ai/flux-lora-fill`），Modal 失敗時退回 fal 也是同一個模型。擴圖改用 Fill dev 後沒有 negative prompt，浮水印壓制比 fal 的 flux-general 弱，**品質尚未驗收**。

仍不走 Modal：純文字生圖（schnell）、Kontext 系列（兩者都只是前面失敗時的備援）、商品 3D 模型；用了 8 個 v5 以外的 LoRA 或自訂 ControlNet 也會退回 fal。

## 4. 實測數據

條件：真實案例、1024×576、有風格 LoRA，樣本很小，當量級參考。

**GPU 對照**（Union 路徑，6 案例、42 步，熱容器）

| GPU | 每秒價格 | 純算圖 | 整段 Modal | 冷啟動 |
|---|---|---|---|---|
| H100 | $0.001097 | 8～9 秒 | 約 14 秒 | 約 40 秒 |
| L40S | $0.000542 | 18～21 秒 | 20～24 秒 | 約 54 秒 |
| A100-80GB | $0.000694 | 19～21.5 秒 | 21～24 秒 | 約 45 秒 |

- **A100 不選**：跟 L40S 一樣慢、貴約 28%。
- **H100 對 L40S**：每張圖 GPU 費差不多（約 $0.009 對 $0.010）；L40S 只省冷啟動與閒置那段（單次測試約 $0.07 對 $0.12），但每張多等約 10 秒、顯存 43.4/48 GB 幾乎滿載。**模型段要 20 秒內只有 H100。**
- 路徑 ① 20 步：H100 算圖 3.7 秒、L40S 7.8 秒。

**時間：Modal 與 fal**（Modal 不含冷啟動）

| | 每張圖 |
|---|---|
| Modal H100 暖機，整段 | 約 14 秒（Union）／約 9～11 秒（路徑 ①） |
| fal 真實紀錄（含排隊，開發期間，資料庫 20 筆） | 中位數 106 秒，第 90 百分位 205 秒 |

**ControlNet 有作用**：邊緣貼合度（越高越貼合）Modal 照 fal 數值時與 fal 相同或更高，關閉時幾乎為 0；強度加倍會變呆板方塊，維持 fal 的數值。

**與 fal 的圖不同**：同權重同參數，兩邊各自可重現，但彼此平均像素差約 45（0～255），不是同一張圖，原因不明。

## 5. 品質

- 已知：權重、LoRA、ControlNet、參數、seed 與 fal 相同，貼合度不低於 fal。
- 我的目視（2 案例）：fal 家具較自然豐富，Modal 較照字面（例如高方塊 fal 畫成書櫃、Modal 畫成一整面白板）。這是主觀看法。
- **未驗證**：沒做 LLM 評分或人工盲測，案例只有 6 個（4 個同風格），照片來源只測 1 個。
- 建議驗收：20 個以上不同風格與房型，fal 與 Modal 各一張，用 LLM 檢查清單（家具齊全、位置貼合、無多餘物件、風格正確）加人工抽樣盲測，定好門檻再決定預設開啟。

## 6. 費用

- 按**秒**計費，只有容器在跑才收；每次呼叫後容器多活「閒置等待」那段（我推論有計費，官方沒明說）。
- 一個工作階段約 = (冷啟動 + 閒置等待) × 每秒價 + 張數 × 算圖秒數 × 每秒價。生 2～3 張以上 Modal 比 fal（約 $0.044／張）便宜，零星單張 fal 便宜。
- 省錢順序：**先關暖機**（`dev`），再縮短閒置（改 `profiles.py`），最後才換便宜 GPU。每次刷新 /studio 都暖機，一次多花約 $0.1～0.3 卻可能一張圖都沒生。
- Starter 每月 $30 免費額度，全隊共用；多人同時各開一張 GPU（並行上限 10）。到 Modal 的 `/settings/usage` 設預算上限（Starter 是否支援請自己確認）。
- 不要指定區域（價格乘 1.15～1.75）、不要用非可中斷選項（乘 3）。

## 7. 常用指令

| 目的 | 指令 |
|---|---|
| 部署 | `python scripts/modal_flux/deploy.py` |
| 看／停應用 | `python -m modal app list`／`python -m modal app stop <ID> --yes` |
| 跑測試存圖到 `artifacts/modal_flux/` | `python -m modal run scripts/modal_flux/modal_app.py::bench --cases cases_all.json --steps 20` |
| 測 Union | `... ::bench --cases cases_union.json --mode union` |
| 換 GPU 測（臨時，不影響已部署） | 先設環境變數 `DESIGNBRIDGE_MODAL_GPU=L40S` 再跑上一行 |

`modal run` 是臨時應用，後端呼叫不到，後端用的是 `modal deploy` 的 `designbridge-flux`。只關掉本機程序不會停遠端容器，要 `modal app stop`。

## 8. 一次性設定（管理者，已完成）

1. 註冊 Modal 並綁付款方式；Hugging Face 建**只讀** token，存成 Modal Secret `huggingface-secret`（鍵 `HF_TOKEN`）。
2. `python -m modal volume create designbridge-weights`
3. `python -m modal run scripts/modal_flux/modal_app.py::download`（CPU，約 49 GB，約 $0.03）；完成後可撤銷 HF token。
4. `.env` 設 `DESIGNBRIDGE_MODAL_MODE=dev`（或 `demo`），再 `python scripts/modal_flux/deploy.py`。
5. 其他成員：Owner 到 Modal 的 Members 頁邀請（Starter 3 席），各用自己的帳號；共用同一個 Google 帳號也行，但每人都是最高權限。

## 9. 限制與疑難排解

| 現象 | 處理 |
|---|---|
| 閒置後第一張多等 35～60 秒 | 冷啟動；用暖機或 `demo` 模式 |
| 每次都 `退回 fal` | 看括號裡的原因；可能是不支援的 LoRA／ControlNet 組合 |
| `No module named 'modal'` | `pip install modal` 後重啟後端 |
| `Token missing` | `python -m modal setup` |
| `App ... not found` | 還沒部署，或 `DESIGNBRIDGE_MODAL_APP_NAME` 寫錯 |
| 改了設定沒生效 | 模式沒重啟後端，或 GPU／閒置沒重新部署 |
| 用量異常 | `modal app list` 看有沒有忘了關的容器 |

授權：FLUX.1-dev 是非商用授權，自架後授權責任在你們，對外服務前要確認。版本：torch 2.15.0（CUDA 13.2）、diffusers 0.42.1、transformers 5.22.0。未查證：閒置等待是否計費、Starter 能否設預算、多個冷啟動同時讀 Volume 是否變慢。

## 10. 相關檔案

| 檔案 | 用途 |
|---|---|
| `scripts/modal_flux/modal_app.py` | Modal 應用（下載、推論類別、bench） |
| `scripts/modal_flux/inference.py` | 推論（平台無關），啟動預載 8 個 LoRA |
| `scripts/modal_flux/profiles.py`／`deploy.py` | 模式對應的 GPU／閒置設定、部署指令 |
| `designbridge/render/render_backends.py` | 後端呼叫 Modal、暖機、耗時說明 |
| `designbridge/layout/condition_prefetch.py` | 條件圖預先計算與快取 |
| `designbridge/core/nodes/renderer.py` | Modal 優先、失敗退回 fal |
| `scripts/modal_flux/cases*.json` | 測試案例 |
