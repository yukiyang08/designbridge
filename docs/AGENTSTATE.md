# AGENTSTATE：代理人現況與溝通

> 記錄**程式目前實際的樣子**，不是規劃。規劃與改善見 [agent_roadmap.md](agent_roadmap.md)。
> 改了節點讀寫的 state 欄位、graph 邊、節點內迴圈或相關旗標預設值，請同步更新本文件並改下方日期。
>
> 最後核對：2026-10-30（對照 commit `3efd3cf7`）

## 1. 溝通方式

- 節點之間只透過共享 state（`DesignBridgeState`，[core/state.py](../designbridge/core/state.py)）溝通：節點 `fn(state) -> dict`，回傳的 dict 合併回 state。
- 沒有節點直接呼叫另一個節點，也沒有訊息傳遞。
- 流程是單向的，沒有任何回饋邊：clip_evaluator 後面直接接 `END`。

```
requirement_analyzer → visual_preprocessing ─┬─ design → layout_and_style_agent → composer ─┐
                                              └─ adjust → adjuster_agent ───────────────────┤
                       clip_evaluator ← renderer ←────────────────────────────────────────┘
```

## 判準

採用 Willison (2025)：「An LLM agent runs tools in a loop to achieve a goal.」即 LLM、工具、迴圈、目標四項缺一不可。依 Anthropic (2024) 的區分，本系統流程由程式決定，整體是 workflow，含 agent 節點。完整說明與逐模組對照見 [agent_roadmap.md](agent_roadmap.md) 第 2 節。

依目前程式碼的旗標預設值，`LAYOUT_REVIEW_AGENT` 為 true，layout 的檢查迴圈會執行，是目前唯一符合的節點（效益與耗時尚未量測）。其餘節點都不符合。

## 2. 節點讀寫對照

| 節點 | 檔案 | 讀 | 寫 |
|---|---|---|---|
| requirement_analyzer | `core/nodes/requirement.py` | `user_input`、`task_id`、`iteration`、已有的 `structured_requirement` / `routing_decision` | `structured_requirement`、`routing_decision`、`iteration`（原值回傳） |
| visual_preprocessing | `core/nodes/visual_preprocessing.py` | 上傳照片 | `vision_features`、`layout_from_depth` |
| layout_and_style_agent | `core/nodes/layout_and_style.py` | `structured_requirement`、`user_input`、`style_params`（已有就不重查）、`scene_graph`、`layout_from_depth`、`vision_features`、`generated_image` | `style_params`、`scene_graph`、`intermediate_outputs` |
| composer | `core/nodes/composer.py` | `structured_requirement`、`style_params`、`scene_graph`、`layout_from_depth`、`user_input`、`generated_image` | `composed_prompt`、`composed_includes_furniture`；沒東西可合併或失敗回 `{}` |
| adjuster_agent | `core/nodes/adjuster.py` | `user_input`、`structured_requirement`、`vision_features`、`style_params` | `generated_image`、`render_result`、`intermediate_outputs["adjuster_agent"]` |
| renderer | `core/nodes/renderer.py` | `routing_decision`、`generated_image`、`structured_requirement`、`style_params`、`composed_prompt`、`composed_includes_furniture`、`scene_graph`、`layout_from_depth`、`vision_features`、`user_input` | `generated_image`、`render_result`；adjuster 已出圖時直接回 `{}` |
| clip_evaluator | `core/nodes/evaluator.py` | `generated_image`、`user_input`、`structured_requirement.design_description` | `evaluation_result` |

節點之間的隱含約定（改動時容易漏）：

- `composed_includes_furniture=True` → renderer 不再注入自己的家具描述（避免重複）。
- adjuster 已寫 `generated_image` 且 `routing_decision == "design_adjuster"` → renderer 跳過。
- state 已有 `generated_image`（風格切換重播）→ composer 不使用 `design_description`；風格代理人也不啟用。
- state 已有 `scene_graph`（Step 1 排版結果）→ layout_and_style 只重新投影，不重排。

## 3. 節點內部的迴圈

這些才是目前實際有「看結果再調整」的地方，都封在單一節點裡，節點外只看得到最終輸出。

| 位置 | 迴圈 | 開關 / 預設 | 外部可見的結果 |
|---|---|---|---|
| layout_agent `layout/layout_agent.py` | LLM 提案 → 硬約束 / 優化器 / 軟約束評分，優化器後算分數（0.65 僅用於 `acceptance_rate` 統計，不再觸發重排） | 啟動條件：`hint_layout`，或 `ENABLE_PRODUCT_MESHES` 且沒有照片 | `scene_graph`、`intermediate_outputs`；LLM 失敗退回 `_default_layout` |
| layout 檢查 `layout/layout_review.py` | 規則檢查風水／動線問題 → 有問題才把報告交回 LLM 重排一次 → 重新優化後比較「問題數、軟性分數」，更差就保留原佈局 | `DESIGNBRIDGE_LAYOUT_REVIEW_AGENT`，**預設 true**（2026-10-30 起） | `intermediate_outputs` 的 review_log（`decision`、`issues_before/after`、`accepted`） |
| composer `core/nodes/composer.py` | LLM 合併並回報 `ra_issue`（使用者原話與 RA 描述核心矛盾）→ 有矛盾就呼叫 `revise_requirement` 重寫 `design_description`，重合併一次；原話明確指定的家具與佈局不符（`layout_issue`）且本輪真的排過版時，帶提示呼叫 `replan_layout` 重排並覆寫 `scene_graph`（Step 1 使用者確認過的佈局不重排）。RA / layout 共用同一輪，只回頭一輪；風格切換重播不觸發→ `check_prompt`（程式檢查家具是否都提到、後設詞、字數）→ 帶問題修訂，最多 2 次 | 一律啟用 | `composed_prompt`、被修正時的 `structured_requirement` / `scene_graph`、`intermediate_outputs["composer"]`（`ra_issue`、`layout_issue`、`revisions`） |
| adjuster | 遮罩過小時改用 bbox（只看遮罩，不驗證結果圖） | 一律啟用 | 結果圖 |

## 4. 已知缺口

| 缺口 | 現況 | roadmap |
|---|---|---|
| 評估不回饋 | `evaluation_result` 只由 `routers/generate.py` 回傳前端，沒有任何節點讀取；低分不會重生 | 3.3 |
| `iteration` 無人遞增 | requirement_analyzer 讀取後原值回傳 | — |
| 降級靜默 | layout agent 失敗只印警告，`scene_graph` 不寫入；composer 失敗回 `{}`，renderer 退回簡單串接。降級原因只存在 `intermediate_outputs["layout_and_style_agent"]["layout"]`，下游與前端都不讀 | 3.1 第 4 點 |
| routing 只決定一次 | 由 requirement_analyzer 決定；adjuster 失敗不能退回 design 路徑 | — |
| 風格與佈局同節點串行 | `layout_and_style_agent_stub` 先風格後佈局，互不依賴卻不並行 | 3.5 |
| `intermediate_outputs` 無 reducer | 各節點用 `{**舊, 新}` 手動累加，並行化前需改 | 3.5 |
| 欄位型別鬆散 | `intermediate_outputs`、`layout_from_depth` 為 `dict[str, Any]`，下游靠 `.get()` 猜 key | — |
| 風格 / 佈局不互通 | 風格不影響佈局，佈局的房間資訊也不進風格檢索 | 3.4、5 |

## 5. 風格

- 風格是單次向量檢索（`style/style_apply.py` → `style_supabase.py`），不是代理人。`top_k=3`，結果依相似度排序，`blend_style_params_supabase` 只取第一名，等於自動選相似度最高的。
- 使用者從候選卡片選了某張（`style_reference_image` 為 URL）時，直接用那張，不重新搜尋。
- 風格代理人（檢索後 LLM 評審改寫）已於 2026-10-30 移除：風格由使用者選，系統只做相似度排序。

## 6. 更新紀錄

| 日期 | 內容 |
|---|---|
| 2026-10-30 | 建立；全部內容由讀程式碼得出，**未實際執行 pipeline** |
| 2026-10-30 | 移除風格代理人；補上漏記的 `LAYOUT_REVIEW_AGENT` 檢查迴圈 |
| 2026-10-30 | 採用 Willison 的 agent 定義作為判準 |
| 2026-10-30 | composer 加上「檢查 → 修訂」迴圈 |
| 2026-10-30 | composer 可回頭請 RA 修正 `design_description`（`ask_ra`）；尚未接 layout。實測 RA 20 筆無真實錯誤，未另做 RA 自身迴圈 |
| 2026-10-30 | composer 可請 layout agent 重排（`ask_layout`，`run_layout_agent(extra_hint=...)`）；未實測 |
| 2026-10-30 | `LAYOUT_REVIEW_AGENT` 預設改為 true；移除舊的 `LAYOUT_LLM_REFINE`（分數回饋給 LLM）與 `LAYOUT_MAX_ITER` |
