# 四種前端入口情境：呼叫路徑 / Agent / 判斷邏輯

對應 `frontend/src/views/StartView.vue` 的 4 張卡片，`source` 值即
`useDesignFlow.js` 的 `STEP_FLOWS` key。所有情境最終都收斂到同一個
`/api/generate`（`submit3D()`），差別只在送出的欄位不同，後端再依欄位
決定 RA 要不要重跑、layout 要不要重算。

---

## 1. `generate` — 從繪製平面設計圖開始

**步驟**：空間設定 → 繪製平面圖 → 3D渲染圖 → 微調編輯 → 預算估計

- 使用者在「繪製平面圖」步驟直接畫出家具擺放 → `submitLayout()` 呼叫
  `/api/generate-layout`，後端跑 `run_layout_agent()` 產生 `scene_graph`
  （這一步已經是真正的 layout agent 呼叫，不是 hint）。
- 到「3D渲染圖」按下生成 → `submit3D()` 呼叫 `/api/generate`，把畫好的
  `scene_graph`（含使用者手動編輯過的 `editPlacements`）一起送出。
- **後端判斷**：`api.py` 的 `/api/generate` 看到 `request.scene_graph` 有值，
  直接塞進 `initial_state["scene_graph"]`。
- `requirement_analyzer` 照常跑（分析文字/風格，決定 `routing_decision`），
  但 `layout_and_style_agent_stub` 看到 `state["scene_graph"]` 已存在 →
  **不會**呼叫 `run_layout_agent()`，只呼叫便宜很多的
  `reproject_scene_graph()`（把使用者定的座標套上最新的空間尺寸/輸出尺寸重新投影）。
  `hint_layout` 這個 RA 判斷欄位在這條路徑上**完全不影響行為**——scene_graph
  已經確定了，不需要再問要不要規劃佈局。

## 2. `upload` — 上傳CAD平面配置圖

**步驟**：上傳平面圖 → 選擇房間 → 繪製平面圖 → 3D渲染圖 → 微調編輯 → 預算估計

- 上傳整戶平面圖 → 後端用 Gemini 視覺分割偵測房間數：
  - 偵測到多間 → 進入「選擇房間」步驟（`handleRoomSelected()` →
    `/api/detect-rooms`、`/api/crop-floor-plan`）。
  - 只有一間 → 自動跳過選房間，行為等同直接上傳單一房間圖。
- 選定房間後 `parseFloorPlanAndProceed()` 呼叫 `/api/parse-floor-plan`，
  取得 `floor_plan_path`（純幾何/牆線，尚未含家具）。
- 「繪製平面圖」步驟同 `generate` 情境，使用者手動擺家具 →
  `/api/generate-layout` 產生 `scene_graph`。
- 「3D渲染圖」同樣是 `submit3D()` → `/api/generate`，帶著 `scene_graph`。
- **後端判斷**：與情境 1 完全相同的路徑——`scene_graph` 已存在，
  `layout_and_style_agent_stub` 走 `reproject_scene_graph()`，不重跑
  layout agent。唯一差異只在 `scene_graph` 的來源（使用者上傳的 CAD 圖
  vs 空白畫布），對後端判斷邏輯沒有分別。

## 3. `photo` — 上傳現有空間照片

**步驟**：空間照片上傳 → 3D渲染圖 → 微調編輯 → 預算估計

- `submitPhoto()` 只做上傳，不解析佈局、不進 layout agent。
- 「3D渲染圖」按生成 → `submit3D()` 送出 `initial_image_path`（照片路徑），
  **沒有** `scene_graph`、**沒有** `floor_plan_path`。
- **後端判斷**：`request.scene_graph` 和 `request.floor_plan_path` 都是空的，
  所以 `initial_state` 不會預塞 `scene_graph`。
  - `requirement_analyzer` 跑文字分析，決定 `hint_layout`（使用者文字有沒有
    暗示要調整家具擺放，例如「把沙發换到窗邊」）。
  - `layout_and_style_agent_stub` 走 `elif hint_layout:` 分支：
    - `hint_layout=True` → 真的呼叫 `run_layout_agent()`（用照片的空間資訊
      規劃新擺放）。
    - `hint_layout=False` → 完全跳過 layout，空間結構直接從照片的深度圖
      （`vision_features` 的 depth）來，renderer 用 ControlNet depth 保留
      原始空間結構，只換風格/材質。
  - 這是唯一一條 `hint_layout` 真正會影響是否呼叫 layout agent 的路徑。

## 4. `skip` — 從零開始，直接描述你的理想空間

**步驟**：空間設定 → 3D渲染圖 → 微調編輯 → 預算估計

- 沒有平面圖、沒有照片，只有房型/坪數（空間設定）+ 自由文字描述。
- `submit3D()` 送出的 `text_prompt` 前面會自動補上房型+坪數描述
  （`spacePreamble`，因為 `DesignRequest` 沒有獨立的 room_type/space_size
  欄位，只能折進文字），`scene_graph`/`floor_plan_path`/`initial_image_path`
  全部是 `undefined`。
- **後端判斷**：`initial_state` 完全沒有 `scene_graph` 可用（也沒有照片深度
  圖可以當空間基準）。
  - `requirement_analyzer` 分析文字 → 決定 `hint_layout`（通常會是
    True，因為完全空白畫布，八成需要規劃佈局；但用詞真的只講風格時也可能是
    False）。
  - `hint_layout=True` → `run_layout_agent()`（用房型+坪數當空間資訊，
    沒有既有照片可參考，純靠文字描述生成佈局）。
  - `hint_layout=False` → 不規劃佈局，renderer 走沒有 depth 基準的生成路徑
    （純文字轉圖，waterfall 較後段的 backend）。

---

## 共通收斂點

四條路徑最終都在同一個 `/api/generate` graph 裡跑完
`requirement_analyzer → visual_preprocessing → (adjuster_agent |
layout_and_style_agent → composer) → renderer → depth_cloud →
clip_evaluator`。差異完全體現在 `layout_and_style_agent_stub` 這一個節點
怎麼決定 `scene_graph` 的來源：

| 情境 | scene_graph 從哪來 | hint_layout 有無作用 |
|---|---|---|
| generate | 使用者手繪（`/api/generate-layout`） | 無（scene_graph 已存在，走 reproject） |
| upload | 使用者手繪，基於上傳的 CAD 平面圖 | 無（同上） |
| photo | 有 hint_layout=True 才規劃；否則用照片 depth | 有，決定要不要呼叫 layout agent |
| skip | 有 hint_layout=True 才規劃；否則無空間基準直接生成 | 有，決定要不要呼叫 layout agent |
