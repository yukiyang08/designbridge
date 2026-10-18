# 進度報告：Layout 座標 → 深度圖 → FLUX 控制

> 日期：2026-07-10　範圍：Layout Agent 混合架構落地與驗證
> 詳細架構另見 [LAYOUT_HYBRID_ARCHITECTURE.md](design/LAYOUT_HYBRID_ARCHITECTURE.md)

---

## 摘要（一句話）

補上 Layout Agent「算出精確座標卻控制不了成圖」的斷點——用一條純 NumPy 的投影管線把家具座標
變成 FLUX 看得懂的深度圖，並以對照實驗證實：**布局座標現在真的驅動了成圖的家具擺位。**

## 1. 問題背景

- Layout Agent 會算出精確家具**座標**，但 FLUX 只吃自然語言 / 影像，**看不懂座標數字**。
- 原本座標只被畫成**俯視平面圖**，從未進到算圖端 → 精確座標對成圖**沒有控制力**。
- 採用方案（老師建議）：座標 → 家具長方體 → 投影成**透視深度圖** → 當 FLUX ControlNet 條件。
  **不做完整 3D**（不用 Blender / TripoSR），純 NumPy 即可。

## 2. 這次完成的更新

| # | 項目 | 檔案 | 狀態 |
|---|---|---|---|
| 1 | 投影模組：家具長方體 → 透視深度圖 (+segmentation)，純 NumPy | `designbridge/scene_graph_to_depth.py`（新） | ✅ |
| 2 | Layout Agent 產出投影深度，寫入 `scene_graph` | `designbridge/layout_agent.py` | ✅ |
| 3 | **把佈局接進 live graph**（原本是空殼 stub） | `designbridge/nodes.py` | ✅ |
| 4 | Renderer 在重排佈局時用投影深度覆蓋輸入照片深度 | `designbridge/nodes.py` | ✅ |
| 5 | 真正 FLUX depth ControlNet 後端（強約束，opt-in） | `designbridge/render_backends.py` | ✅（待實測） |
| 6 | 補上遺失的佈局 prompt（修 broken import） | `designbridge/prompts.py` | ✅ |
| 7 | 投影 / ControlNet 相關設定 | `designbridge/config.py` | ✅ |
| 8 | 相機校準工具（掃參數 + 成圖對照 montage） | `scripts/calibrate_layout_depth.py`（新） | ✅ |

### 過程中的關鍵發現

原本的 `run_layout_agent` **從未在 production 跑過**：它 import 了兩個不存在的 prompt
（`LAYOUT_AGENT_PROMPT` / `LAYOUT_REFINEMENT_PROMPT`），而且 graph 接的是不呼叫它的 stub。
這次是**第一次讓整個 Layout Agent 真正在系統裡執行**，並補上 prompt 修好。

## 3. 驗證結果（準確度對照實驗）

**方法**：同一句 prompt（modern bedroom），只把佈局**左右鏡像**，看成圖是否跟著鏡像。

| 佈局 | 投影深度圖 | FLUX 成圖 | 對應 |
|---|---|---|---|
| A：床在左 | 亮箱在左、高衣櫃在右 | 床在左、高衣櫃在右 | ✅ |
| B：床在右 | 亮箱在右、高衣櫃在左 | 高衣櫃在左、床在右 | ✅ |

**結論**：床與衣櫃的左右位置在兩張成圖裡精確對調，且與佈局座標一致。
→ 直接證明「座標 → 深度圖 → ControlNet」這條橋讓精確布局生效。

對照圖：`artifacts/accuracy_demo/accuracy_montage.png`

## 4. 相機校準結果

用 `calibrate_layout_depth.py --render` 實際算圖比對，掃描 HFOV / pitch：

- **`pitch = -16`**（俯角較大、看到較多地板）構圖最完整、家具分佈最貼合深度圖，
  優於 `pitch = -8`（偏平視、家具貼牆）。已設為預設。
- HFOV 取已驗證可用的 **65**。
- 對照圖：`artifacts/calibration_render/calibration_montage.png`

校準後預設值（`config.py`，可用環境變數覆蓋）：

```
LAYOUT_PROJECTION_HFOV   = 65
LAYOUT_PROJECTION_PITCH  = -16
LAYOUT_PROJECTION_SETBACK = 0.8
```

## 5. 現況與限制

| 面向 | 狀態 |
|---|---|
| 投影模組 + 校準工具 | ✅ 完成、測試過 |
| live graph 端到端 | ✅ 打通（真實 LLM + 離線 fallback 皆驗證） |
| 準確度 | ✅ 對照實驗確認座標驅動成圖 |
| 使用者畫面 (UI) | ⚪ 未變動（純後端；成圖只在「要求重排佈局」時改變） |
| Kontext depth LoRA | ✅ 可用，但屬「鬆散參考深度」，左右分區準、細節非逐格對齊 |
| 真正 depth ControlNet | ⚠️ 程式已備、預設關閉，尚未實測（需 `FAL_KEY`） |

## 6. 下一步

1. 設 `FAL_KEY` + `LAYOUT_DEPTH_CONTROL_BACKEND=controlnet`，實測真正 ControlNet 後端，
   微調 `conditioning_scale`（通常 0.5〜0.8）。預期家具形狀對齊會比 LoRA 更精準。
2. 需要更高辨識度時，把 segmentation mask 接成第二條 ControlNet 條件（已產出、尚未餵入）。
3. 補跑 HFOV 上限校準（65 vs 80）。
4.（可選）若要讓使用者看到投影深度 / floor plan，需擴充 API 回傳 + 前端顯示。

## 附錄：產出檔案位置

```
docs/design/LAYOUT_HYBRID_ARCHITECTURE.md         完整架構文件
docs/PROGRESS_layout_depth_bridge.md       本進度報告
designbridge/scene_graph_to_depth.py       投影模組（新）
scripts/calibrate_layout_depth.py          校準工具（新）
artifacts/accuracy_demo/accuracy_montage.png       準確度對照圖
artifacts/calibration_render/calibration_montage.png  相機校準對照圖
```
