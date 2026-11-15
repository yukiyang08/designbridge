# 入口二（改造現有空間）換風格參數測試

測試腳本：[`scripts/ab_photo_restyle.py`](../../scripts/ab_photo_restyle.py)
原始數據：[`images/photo_restyle/results.json`](images/photo_restyle/results.json)

## 1. 要驗的問題

照片入口換風格時，生出來的圖有時跟使用者原本的房間毫無關係（整個換成另一個空間）。
要確認是不是**結構約束太弱**造成的，以及四個旋鈕裡哪一個真的有效。

## 2. 受測的那條路

前端 [`restylePhoto`](../../frontend/src/composables/design-flow/photoLayout.js#L172) 送出：

```json
{ "text_prompt": "現代工業風格的室內設計", "style_profile_id": "industrial",
  "initial_image_path": "<目前這一版的圖>", "restyle": true }
```

後端走法：`requirement_analyzer`（`restyle` → `hint_layout=False`、routing `design`）→
`visual_preprocessing`（對底圖跑 Depth Anything V2）→ renderer 的
[FLUX depth ControlNet 分支](../../designbridge/core/nodes/renderer.py#L610)。

沒有 `plan`、沒有 `scene_graph`，所以**畫面裡原本房間的資訊只剩深度圖與邊緣圖**，
prompt 裡一個字都沒提到它。

## 3. 四組參數

RA 依提示詞對「純換風格」會給 `depth_conditioning_scale≈1.0`，但 renderer 會砍到
`REAL_PHOTO_DEPTH_MAX_CONDITIONING_SCALE`。四組先各動一個旋鈕，最後一組全開：

| 組 | 深度上限 | 控制結束 | 邊緣強度 | 步數 | 動機 |
|---|---|---|---|---|---|
| P0 現狀 | 0.65 | 0.70 | 0.30 | 20 | 線上目前的值，當對照組 |
| P1 提高深度上限 | **0.78** | 0.70 | 0.30 | 20 | 0.65 是 2026-09-28 為修「遠牆雜訊」加的封頂，可能砍過頭 |
| P2 延長深度控制 | 0.65 | **0.85** | 0.30 | 20 | 後 30% 步數完全放開，結構可能在這段被改掉 |
| P3 四項全上 | **0.78** | **0.85** | **0.45** | **28** | 全部收緊的上界，看代價（遠牆雜訊、輪廓殘留）會不會出現 |

對應的環境變數：`DESIGNBRIDGE_REAL_PHOTO_DEPTH_MAX_CONDITIONING_SCALE`、
`DESIGNBRIDGE_REAL_PHOTO_DEPTH_CONTROL_END`、`DESIGNBRIDGE_EDGE_CONDITIONING_SCALE`、
`DESIGNBRIDGE_FAL_CONTROLNET_STEPS`。腳本直接改 `Config`，不用動 `.env`。

## 4. 怎麼跑

```bash
PYTHONUTF8=1 python scripts/ab_photo_restyle.py
PYTHONUTF8=1 python scripts/ab_photo_restyle.py --photo artifacts/uploads/xxx.png --style luxury
PYTHONUTF8=1 python scripts/ab_photo_restyle.py --report-only   # 只重建報告，不重跑
```

- 會呼叫 fal，**每組 1 次生成，共 4 次**，約 3–5 分鐘。
- 不帶 `--photo` 時用 `frontend/src/assets/rooms/living_room.jpg`，不在 `artifacts/` 底下會自動複製進去（`check_request_paths` 只收 artifacts 路徑）。
- 不寫入使用者的歷史紀錄（`_save_history` 被停用）。
- 結果會覆寫本檔 `<!--RESULTS-->` 以下的內容。

## 5. 判讀標準

1. **先看圖**：還是不是同一個房間（窗戶位置、牆面走向、家具數量與位置）。結構相關只是輔助數字，
   深度圖對得上但內容全換的情況它分數還是會高。
2. **P1 或 P2 單獨就有效** → 把那一個旋鈕寫進 `.env` 就好，不要四個一起動。
3. **四組都是別的房間** → 不是強度問題，是 prompt 問題：
   restyle 只送「某某風格的室內設計」，RA 生出的 `design_description` 完全沒有原房間的描述。
   那要修的是把房間描述帶進 restyle 的 prompt，或這條路改走 Kontext 編輯而不是從深度重生。
4. **P3 看起來最像但出現遠牆雜訊、地板輪廓線殘留** → 退回 P1 或 P2，那正是當初封頂與
   `FAL_EDGE_CONTROL_END` 要避免的副作用（見 [`CONTROLNET_PARAM_TEST.md`](CONTROLNET_PARAM_TEST.md)）。

<!--RESULTS-->

（尚未執行，跑完腳本後這裡會被結果覆寫。）
