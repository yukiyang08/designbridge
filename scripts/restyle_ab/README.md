# 換風格實驗腳本

對應 [`docs/experiments/PHOTO_RESTYLE_EXPERIMENT_PLAN.md`](../../docs/experiments/PHOTO_RESTYLE_EXPERIMENT_PLAN.md)。在專案根目錄執行。

| 腳本 | 做什麼 | 花費 |
|---|---|---|
| `baseline.py` | 對一張照片跑一次完整的換風格流程（目前的 FLUX 做法），log 存下描述、seed、條件圖 | Gemini 需求分析＋FLUX 兩段，約 0.12 美元 |
| `gemini_edit.py` | Gemini 圖片編輯（Vertex AI），沿用 baseline 的風格描述與房間內容 | flash 約 0.067 美元／張（估算） |
| `hybrid.py` | Gemini 結果再過 FLUX＋自家風格 LoRA 低強度 img2img | 約 0.06 美元／張 |
| `run_cases.sh` | 一次跑多題：baseline → Gemini → 接力 | 每題約 0.25 美元 |
| `compare_sheet.py` | 拼對照表 | 免費 |

## 一次跑多題

1. 照片放到 `artifacts/uploads/`（只收 artifacts 底下的路徑），寫一份 `cases.txt`，每行：

   ```
   c1 artifacts/uploads/rs9_c1.jpg industrial 現代工業
   ```

   style_id 見 `style_kb/styles.py`：modern、country、classic、nordic、industrial、japanese、american、luxury。

2. 執行：

   ```bash
   scripts/restyle_ab/run_cases.sh cases.txt ablation_tests/restyle_run1
   PYTHONUTF8=1 python scripts/restyle_ab/compare_sheet.py cases.txt ablation_tests/restyle_run1 ablation_tests/restyle_run1/compare.jpg
   ```

   輸出放 `ablation_tests/`（git 不追蹤）。要留紀錄的圖縮到長邊 900 像素再放 `docs/experiments/images/restyle_results/`。
