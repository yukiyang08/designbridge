# 生成 2D 平面配置圖 — 技術說明

> 對應流程 Step 1：使用者輸入坪數／房型／家具清單 → 產出可編輯的 2D 俯視平面配置圖。
> 主要程式：`designbridge/layout/layout_agent.py`、`designbridge/layout/layout_constraints.py`、
> `designbridge/layout/special_constraints.py`、`api.py`、`frontend/src/components/LayoutEditor.vue`。

---

## 1. 整體管線

```
使用者輸入（坪數 / 房型 / 家具清單 / 文字需求 / 家庭需求 / 風水規則）
        │  api.py:364  POST /api/generate-layout
        ▼
structured_requirement（房間尺寸換算、硬性限制、權重）
        │  special_constraints.enrich_requirement()
        ▼
① LLM 語意規劃      Gemini → 家具型別 + 粗略座標 (JSON)
        ▼
② 硬約束修正        must_add/remove/move、immutable、貼牆、AABB 分離
        ▼
③ 幾何最佳化        Hill-climbing（2000 步）對五項軟性指標搜尋
        ▼
④ 再次硬約束修正 + 取兩者較佳者
        ▼
⑤ 製圖             pycairo 向量繪製 → floor_plan.png（PIL 為 fallback）
        ▼
前端 LayoutEditor（SVG 拖拉編輯）→ POST /api/render-floor-plan 重繪
```

另有一條**上傳既有平面圖**的支線：`parse_floor_plan_image()`（`layout_agent.py:956`）
用 Gemini 視覺讀圖，把圖上的家具還原成同一套正規化座標，接回同一條管線。

---

## 2. 座標系統與資料模型

`FurnitureItem`（`layout_agent.py:79`）是整條管線唯一的資料單位：

| 欄位 | 意義 |
|---|---|
| `x, y` | 家具**左上角**，正規化 [0,1]；`x` 左→右、`y` 上（遠牆／窗側）→下（近觀看者） |
| `w, h` | 寬度與縱深，同樣正規化 |
| `rotation` | 旋轉角 |
| `pinned` | run 內部標記：`_enforce_move_ops` 已把它擺到使用者指名的位置，最佳化器與計分器都要放過它（不序列化） |

全程用**正規化座標**而非公尺，好處是同一份佈局可以直接套到任何房間尺寸；
需要物理量時（走道寬度、間距）才乘上 `room_w` / `room_d` 換算回公尺。

`FURNITURE_SIZES`（`layout_agent.py:16`）給 23 種家具的預設 footprint，
LLM 沒給尺寸或給了離譜值時用它兜底，同時也是 `must_add` 新增家具的尺寸來源。

坪數→房間尺寸的換算在 `api.py:373`：`總坪數 × 3.306 m²`，再依 **5:4 長寬比**開根號拆成 width/depth。

---

## 3. 技術逐項說明

### 3.1 LLM 語意規劃（Gemini）

- 模型：`Config.GEMINI_MODEL`（預設 `gemini-3.6-flash`），`temperature=0.3`，
  透過 `designbridge/render/llm.py:184` 的 `call_llm()`，支援多把 API key 依序 failover。
- Prompt：`core/prompts.py` 的 `LAYOUT_AGENT_PROMPT`（中文版，第 204 行起）。
  內含房型、公尺尺寸、窗／門的俯視座標、四類硬性限制、既有佈局、以及座標系統定義。
- 輸出：嚴格 JSON `{"furniture":[{id,type,x,y,w,h}]}`。
- 容錯：`_parse_llm_layout()`（`:900`）剝除 markdown code fence、擷取首尾大括號再 `json.loads`；
  完全失敗時退回 `_default_layout(room_type)`（`:1046`）的手寫樣板佈局。

**設計取捨**：LLM 只負責「要哪些家具、大致在哪」這種語意問題，**不負責精算幾何**。
原因寫在 `run_layout_agent` 的註解裡：舊版的 `LAYOUT_REFINEMENT_PROMPT` 每輪只丟五個
純量分數回去讓 LLM 重猜，一輪一次 round trip 卻沒有任何可據以行動的資訊；
改成數值最佳化後同樣時間可以評估數千個候選，而且結果可重現。
該回退路徑仍保留，但預設關閉（`Config.LAYOUT_LLM_REFINE=false`）。

### 3.2 硬約束層（`_settle`）

一次 `_settle()` 依固定順序跑完下列處理，順序本身是設計過的（後面的不能破壞前面的成果）：

| 順序 | 函式 | 作用 |
|---|---|---|
| 1 | `_apply_hard_constraints` | must_remove 過濾、must_add 補齊。型別比對走 `normalize_furniture_type` 正規化（`low_cabinet` → `cabinet`），且**計數感知**：`must_add:["chair"]×3` 是三張椅子，但既有已有一張就只補兩張 |
| 2 | `_enforce_move_ops` | 解析「把書桌移到窗邊」這類指令：`_resolve_destination` 把方位詞（left/right/center/far…）與門窗開口換算成錨點座標，擺好後標記 `pinned` |
| 3 | `_enforce_immutable` | 避開不可佔用區域 |
| 4 | `_clip_to_room` | 夾回房間邊界（留 `pad=0.02`） |
| 5 | `_inject_bunk_bed_ladder` | 上下舖自動補一個梯子佔位 |
| 6 | `_push_apart` | AABB 碰撞分離，最多 60 輪，沿**重疊較短的軸**推開；夾邊界放在迴圈內部（先分離後夾會把家具推回鄰居身上，造成「回報成功但留著碰撞」） |
| 7 | 約束卡片 | 由 registry 動態載入（見 3.3） |
| 8 | `apply_special_layout_constraints` | 家庭需求／風水規則 |
| 9 | `_push_apart` + `_clip_to_room` | 第二次分離：7、8 的貼牆與推離門口會製造新的重疊 |

**地毯特例**：`_UNDERLAY_TYPES`（rug/carpet/mat…）完全不參與碰撞判定。
沙發壓在地毯上是正確擺法，把地毯當實體會讓 `_push_apart` 把沙發推下地毯，
還讓 `collision_free` 對一個完全正常的佈局回報 False。

### 3.3 約束知識庫（Skill Card Registry）

硬約束不寫死在程式裡，而是以 **Skill Card 格式的 Markdown**外部化：
`skills/layout-constraints/*/SKILL.md`，YAML frontmatter 宣告 `enforce`（對應的
Python 函式名）、`order`（執行順序）、`parameters`（可調參數）。
`LayoutConstraintRegistry`（`layout_constraints.py`）以 regex + PyYAML 解析並快取，
`_LAYOUT_ENFORCERS`（`layout_agent.py:888`）做名稱→函式的 dispatch。

目前 6 張卡片：

| 卡片 | 規則 | 關鍵參數 |
|---|---|---|
| `wall-anchor` | 衣櫃／電視櫃／書架／床貼牆 | `snap_threshold=0.12` |
| `semantic-gaps` | 特定家具配對之間的語意間距 | 型別配對 → 間距表 |
| `desk-bed-separation` | 書桌與床 ≥ 0.10（約 50 cm，椅子可拉出） | `min_gap=0.10` |
| `bed-clearance` | 床至少一側留通道 | `side_clearance=0.06`（約 30 cm） |
| `bunk-bed-ladder-clearance` | 上下舖四側至少一側留梯子空間 | `ladder_clearance=0.08` |
| `bed-not-near-window` | 床不緊貼窗戶 | `window_clearance=0.08` |

好處是加一條新規則＝加一個資料夾，不必動 `run_layout_agent`。

### 3.4 軟性指標評分（`_score_soft_constraints`）

五項純幾何指標，加權（`SOFT_WEIGHTS`）成單一分數，門檻 `SCORE_THRESHOLD=0.65`：

| 指標 | 權重 | 計算方式 |
|---|---|---|
| `circulation` 動線 | 0.35 | 兩兩家具**實體公尺**間距 ≥ 0.60 m 的比例 |
| `balance` 重心平衡 | 0.25 | 面積加權質心與房間中心 (0.5, 0.5) 的曼哈頓距離 |
| `focal_point` 視覺焦點 | 0.20 | 最大件家具是否靠近焦點牆（y≈0.72）且水平置中 |
| `natural_light` 採光 | 0.10 | 大件家具擋住上牆窗戶（y<0.15）的數量。**排除** `pinned`（使用者自己要求擺那的，罰它等於罰服從）與地毯（`h` 是俯視縱深不是高度，0.24 深的地毯會誤觸尺寸判定） |
| `ergonomics` 人體工學 | 0.10 | 兩兩間距 ≥ 0.40 m 的比例 |

注意間距一律換算成**公尺**再比較，因為 0.12 正規化在 3 m 房間和 6 m 房間是完全不同的走道。

### 3.5 幾何最佳化（Hill Climbing）

`_optimize_positions`（`:311`）— 隨機爬山法，`Config.LAYOUT_OPTIMIZER_STEPS` 預設 2000 步：

- **目標函式** `_layout_objective`：加權軟分數 − `_OVERLAP_PENALTY(4.0)` × 違規量。
  違規量＝出界距離 + 重疊**面積**。權重 4.0 校準成「1% 房間面積的重疊 ≈ 0.04 分」，
  確保最佳化器不會拿真實碰撞去換邊際的動線改善。
- **提議分佈**：每步隨機挑一件可動家具，對 (x, y) 加高斯擾動，
  `sigma = 0.18 × (1 − step/steps) + 0.01` — 由粗到細退火，早期能跳出壞的初始佈局，後期收斂。
- **接受準則**：只接受改善（純爬山，非模擬退火），並保留全域最佳位置。
- **可重現**：`random.Random(seed=0)`，同一份規劃每次跑出同樣結果。

**可動集合** `_movable_indices`（`:287`）：有上傳照片且走 photo-anchored 路徑時，
使用者沒指名要動的家具會被**凍結**——它們在最終渲染中會沿用原照片的深度像素，
在平面圖上移動它們不會反映到成圖，只會擾動分數並把真正該動的家具拖到更差的位置。

**單調性保證**：最佳化後還要再跑一次 `_settle`（重新貼牆、重新 pin），
這可能吃掉一部分增益。所以程式碼會把「最佳化前 settle 過的 baseline」與
「最佳化後 settle 過的結果」在**相同條件下**比分，取較佳者——
最佳化永遠不可能交回比輸入更差的佈局。

### 3.6 製圖：pycairo 向量繪製

`_generate_floor_plan`（`:1247`）用 **pycairo**（`ANTIALIAS_BEST`）畫 900×980 的 PNG，
走的是建築製圖慣例而非示意色塊：

- **圖框與標題列**：黑底標題 `FLOOR PLAN — <房型>`，右上角房間尺寸與面積。
- **牆體**：實心黑（`WT=20px` 牆厚），內部白色地板。
- **格線**：每 1 公尺一條淺灰格線（依 `room_w` / `room_d` 分別換算步距）。
- **門**：下牆中央挖空 + 鉸鏈直線 + **虛線開門弧**（`ctx.arc`），標註 `D`。
- **窗**：上牆中央挖空 + **三線窗符號**（標準製圖表示法），標註 `W`。
- **尺寸標註**：外側標註線 + 端點 tick，深度標註用 `ctx.rotate(-π/2)` 轉 90°。
- **比例尺**：1 公尺長的 scale bar，以 `px_per_m_w` 換算。
- **家具語意符號**（不是一律畫方框）：
  - 椅／扶手椅 → 圓形（扶手椅多一道背弧）
  - 植栽／燈 → 圓形 + 十字
  - 地毯 → 虛線雙框，且**先畫**（floor layer，其他家具疊在上面）
  - 沙發 → 分隔坐墊線 + 椅背線
  - 床／上下舖 → 深色床頭板 + 枕頭矩形（寬度足夠時畫兩顆）
  - 衣櫃 → 中線 + 兩個把手圓點
  - 書架／櫃 → 層板橫線
  - 電視櫃 → 深色螢幕塊
  - 五斗櫃 → 抽屜分隔線 + 把手
- **標籤**：家具名 + **真實公尺尺寸**（`item.w × room_w`），字級隨框大小自適應，
  空間不足時退成縮寫。

**Fallback**：pycairo 不可用（Windows 上常見）時，`except` 落到 **PIL** 版本——
640×640 灰階方框 + 文字標籤，功能等價但沒有製圖符號。字型會依序找
`C:/Windows/Fonts/arial.ttf` 與 DejaVuSans，都沒有就用 PIL 預設點陣字型。

> `_build_floor_plan_svg`（`:1101`）是另一條 SVG 輸出實作，目前全專案沒有呼叫點。

### 3.7 前端互動編輯

`frontend/src/components/LayoutEditor.vue`（Vue 3 Composition API）：

- 以 **SVG** 重繪同一份 `furniture_placements`，家具可**拖曳／縮放／旋轉**。
- 座標換算：滑鼠位移 `/ size` 直接得到正規化增量，
  拖曳與縮放都用 `clamp(..., 0, 1 - w)` 夾在房間內，與後端同一套約束。
- 編輯結果 `emit('update:placements')` 上拋，再呼叫 `POST /api/render-floor-plan`
  （`api.py:522`）用**同一支** `_generate_floor_plan` 重繪 PNG，保證前端預覽與後端出圖一致。

### 3.8 與後續步驟的銜接

`run_layout_agent` 回傳的 `scene_graph` 除了平面圖之外，同時帶出：

```python
{
  "furniture_placements": [...],       # 精確座標，Step 2 投影與報價都吃這份
  "floor_plan_path": "...png",         # 給人看的 2D 平面圖
  "room_w", "room_d",                  # 真實公尺尺寸（Step 2 靠這個算對比例）
  "projected_depth_path": "...",       # 投影透視深度圖 → FLUX ControlNet
  "layout_constraints_met": {...},     # 硬約束滿足報告
  "soft_constraint_scores": {...},     # 五項軟分數
  "weighted_score": 0.xx,
  "feasible": bool, "infeasible_constraints": [...],
}
```

`layout_and_style_agent_stub`（`core/nodes/layout_and_style.py`）在 Step 2 會偵測
`floor_plan_path` 已存在就**直接沿用**，不重跑規劃——否則使用者剛審核通過的佈局
會被換成另一份不同的結果。座標如何轉成透視深度圖見
`docs/LAYOUT_HYBRID_ARCHITECTURE.md`。

---

## 4. 技術棧總表

| 層次 | 技術 | 用途 |
|---|---|---|
| 語意規劃 | Google Gemini（`google-genai`） | 家具選擇與粗略擺位、上傳平面圖的視覺解析 |
| 資料模型 | Python `dataclass` + 正規化座標 | `FurnitureItem` |
| 幾何 | AABB 碰撞偵測／分離、邊界夾取 | `_overlaps` / `_push_apart` / `_clip_to_room` |
| 最佳化 | 隨機爬山 + 高斯提議 + 退火步長（`random`，seeded） | `_optimize_positions` |
| 評分 | 五項加權啟發式指標 | `_score_soft_constraints` |
| 規則引擎 | Skill Card（Markdown + YAML frontmatter）+ registry dispatch | `layout_constraints.py` |
| 製圖 | **pycairo**（向量，建築製圖符號）／**PIL** fallback | `_generate_floor_plan` |
| API | FastAPI + Pydantic | `/api/generate-layout`、`/api/parse-floor-plan`、`/api/render-floor-plan` |
| 前端 | Vue 3 Composition API + SVG 直接操作 | `LayoutEditor.vue` |
| 編排 | LangGraph 節點 | `core/nodes/layout_and_style.py` |

## 5. 關鍵可調參數

```
DESIGNBRIDGE_LAYOUT_OPTIMIZER_STEPS  = 2000     # 爬山步數
DESIGNBRIDGE_LAYOUT_LLM_REFINE       = false    # 是否啟用舊版 LLM 迭代精修
DESIGNBRIDGE_LAYOUT_MAX_ITER         = 3        # LLM 精修上限輪數
DESIGNBRIDGE_GEMINI_MODEL            = gemini-3.6-flash
```

程式內常數：`SCORE_THRESHOLD=0.65`、`_OVERLAP_PENALTY=4.0`、
`AISLE_MIN_M=0.60`、`ERGO_MIN_M=0.40`、`SOFT_WEIGHTS`。
