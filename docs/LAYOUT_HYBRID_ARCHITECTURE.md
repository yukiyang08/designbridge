# Layout 混合架構（Scene Graph → 投影深度圖 → FLUX ControlNet）

> Layout Agent 採用的混合架構、完整資料流，以及相較於 session 起始版本（commit `d97b3f90`）的改動。

---

## 1. 所解決的問題

精準布局控制需要 Scene Graph 輸出**座標**；但 Renderer（FLUX.1）只能吃自然語言或影像條件，
**無法直接解析座標數值**。原先是 Layout Agent 算出來的精確座標對最終生成沒有控制力——
座標和成圖之間缺一座橋。

更具體的斷點（在程式碼層面）：

- Renderer 其實**早就能吃深度圖**（`_render_hf_kontext` / `_render_flux_kontext_fal` 接受 depth PNG）。
- 但那張深度來自 Depth-Anything 對**輸入照片**的估計（`vision.get("depth")`）。
- Layout Agent 的座標只被畫成**俯視平面圖**（`_generate_floor_plan`），從未進到 Renderer。
- 只要家具被重新擺放，輸入照片的深度就跟新佈局對不上 → 座標失去控制力。

## 2. 混合架構（前移建議）

> **不做完整 3D。** 不用 Blender / TripoSR（風險高、家具生成品質不穩）。
> 每件家具用一個**長方體**代表，由 Scene Graph 座標直接在 3D 房間中擺位，
> 投影成 2D **透視深度圖**，當作 FLUX ControlNet 的精確空間條件。
> **NumPy** 即可，先只做深度圖，需要時再加 segmentation。

```
Scene Graph 座標 (俯視 bbox)
        │  每件家具 → 長方體（footprint + 高度）
        ▼
3D 房間立方體擺位（world coords）
        │  固定針孔相機 + z-buffer
        ▼
2D 透視深度圖（near=亮 / far=暗，對齊 Depth-Anything 慣例）
        │  ＋ 可選 segmentation mask（同一 pass 順手輸出）
        ▼
FLUX ControlNet / Kontext 風格化渲染
```

理念：座標**不再翻譯成自然語言讓 FLUX 猜**，而是直接在幾何上產生深度條件。

## 3. 完整資料流（接進 LangGraph 後）

```
requirement_analyzer
   └─ visual_preprocessing          Depth-Anything 跑輸入照片 → depth.png
   └─ design_director               路由
   └─ layout_and_style_agent        ★ 現在會真的規劃佈局（原本是 stub）
          run_layout_agent()
            ├─ LLM 產生家具座標 → 硬/軟約束迭代 → best_items
            ├─ _generate_floor_plan()        俯視平面圖（給人看）
            ├─ _generate_projected_depth()   ★ 投影成透視深度圖 + segmentation
            │      └─ scene_graph_to_depth.project_scene_graph_to_depth()  [純 NumPy]
            └─ scene_graph = {
                   furniture_placements,        精確座標
                   projected_depth_path,  ★     餵 ControlNet 的深度圖
                   projected_seg_path,    ★     segmentation mask
                   floor_plan_path, ...
               }
   └─ renderer
          ├─ depth_path = vision.get("depth")           預設：輸入照片深度
          ├─ if hint_layout: depth_path = projected_depth_path   ★ 覆蓋成投影深度
          └─ 依 LAYOUT_DEPTH_CONTROL_BACKEND 選後端：
                 "kontext"    → Kontext depth-fusion LoRA（鬆散參考，預設）
                 "controlnet" → 真正的 FLUX depth ControlNet（強約束，需 FAL_KEY）★
   └─ clip_evaluator
```

## 4. 新增元件詳解

### 4.1 `designbridge/scene_graph_to_depth.py`（新檔）

核心投影模組，純 NumPy。主要函式：

```python
project_scene_graph_to_depth(
    furniture_placements, space_info, out_path,
    image_size=(1024,1024), seg_out_path=None, camera_overrides=None,
) -> dict
```

實作步驟：

1. **長方體化** — `FURNITURE_HEIGHTS` 給每類家具一個高度（footprint 沿用 `layout_agent.FURNITURE_SIZES`）。
2. **擺進房間** — floor-plan 正規化座標映射到 world：
   - `x ∈ [0,1]` 左→右 → `X = (x-0.5) * room_w`
   - `y ∈ [0,1]` 上(遠牆)→下(近相機) → `Y = (1-y) * room_d`
   - `Z ∈ [0, height]` 地板→天花板
3. **針孔相機** — `_build_camera()`：站在近牆後方 `setback` 公尺、眼高 `eye_height`，朝 +Y 看，
   含俯角 `pitch`、水平視角 `hfov`。
4. **光柵化 + z-buffer** — `_raster_triangle` / `_raster_quad` 把房間外殼（地板/牆/天花板）
   與每個家具長方體的可見面投影、做 z-buffer。
5. **深度極性** — near=255（亮）、far=0（暗），對齊 `vision.run_depth_estimation` 的輸出慣例。
6. **segmentation** — 同一個 z-buffer pass 記錄每像素的物件 ID，上色輸出 mask。

另含 CLI：`python -m designbridge.scene_graph_to_depth placements.json --vis`

### 4.2 `scripts/calibrate_layout_depth.py`（新檔）

相機校準工具：固定佈局、掃描相機參數（HFOV / pitch / setback），可選 `--render` 實際呼叫
FLUX，輸出「深度圖 vs 成圖」並排 montage，肉眼挑出最貼合 FLUX 視角的相機設定。純 PIL 拼圖。

```bash
# 只看框景（不花 API）
python -m scripts.calibrate_layout_depth --hfov=55,65,75 --pitch=-6,-12
# 連 FLUX 算圖一起比
python -m scripts.calibrate_layout_depth --render --hfov=65,80 --pitch=-16
```

> 注意：argparse 對負數要用 `=`，例如 `--pitch=-16`。

## 5. 相較起始版本（`d97b3f90`）的逐檔改動

| 檔案 | 類型 | 改動 |
|---|---|---|
| `designbridge/scene_graph_to_depth.py` | **新檔** | 投影模組（座標→透視深度圖+seg），純 NumPy |
| `scripts/calibrate_layout_depth.py` | **新檔** | 相機校準工具 |
| `designbridge/layout_agent.py` | 修改 | 新增 `_generate_projected_depth()`，並在 `run_layout_agent` 的 `scene_graph` 加入 `projected_depth_path` / `projected_seg_path` |
| `designbridge/prompts.py` | 修改 | **補上 `LAYOUT_AGENT_PROMPT` 與 `LAYOUT_REFINEMENT_PROMPT`**（原本 `run_layout_agent` import 這兩個根本不存在的名稱 → 證明它從未在 production 跑過） |
| `designbridge/nodes.py` | 修改 | (a) `layout_and_style_agent_stub` 由純 stub 改為 `hint_layout=True` 時真的呼叫 `run_layout_agent`、回傳 `scene_graph`；(b) renderer 在 `hint_layout` 時用投影深度覆蓋輸入照片深度；(c) 接入新的 ControlNet 後端 |
| `designbridge/render_backends.py` | 修改 | 新增 `_render_flux_controlnet_depth_fal()`（fal.ai flux-general + 真正 depth ControlNet） |
| `designbridge/config.py` | 修改 | 新增投影/ControlNet 相關設定（見下） |

### 重點：被修掉的潛藏 bug

`run_layout_agent` 一直 `from designbridge.prompts import LAYOUT_AGENT_PROMPT, LAYOUT_REFINEMENT_PROMPT`，
但這兩個名稱在 `prompts.py` 從未定義。同時 graph 接的是**不呼叫 `run_layout_agent` 的 stub**，
所以這個 broken import 一直沒被觸發。這次把佈局接進 live graph 才讓它浮現，並補上 prompt 修好。

## 6. 新增設定（`config.py`）

```python
# 投影開關與相機（校準後預設）
ENABLE_LAYOUT_DEPTH_PROJECTION  = true     # DESIGNBRIDGE_ENABLE_LAYOUT_DEPTH_PROJECTION
LAYOUT_PROJECTION_HFOV          = 65.0      # DESIGNBRIDGE_LAYOUT_PROJECTION_HFOV
LAYOUT_PROJECTION_PITCH         = -16.0     # DESIGNBRIDGE_LAYOUT_PROJECTION_PITCH（校準結果）
LAYOUT_PROJECTION_SETBACK       = 0.8       # DESIGNBRIDGE_LAYOUT_PROJECTION_SETBACK

# 深度條件後端
LAYOUT_DEPTH_CONTROL_BACKEND    = "kontext" # 或 "controlnet"（需 FAL_KEY）
DEPTH_CONTROLNET_MODEL          = "Shakker-Labs/FLUX.1-dev-ControlNet-Depth"
```

`pitch=-16` 是用 `calibrate_layout_depth.py --render` 校準出來的：俯角大、看到較多地板，
成圖構圖最完整、家具分佈最貼合深度圖（對照 `pitch=-8` 偏平視、家具貼牆）。

---

# 第二輪：照片錨定（成圖與原始照片空間配置對不上的修正）

## 8. 上面那版為什麼還是對不上原始照片

使用者回報「render 生出來的圖跟原始照片的空間配置差很多」。根因不是深度圖沒接上，
而是**那張深度圖本身跟原始照片毫無關係**：

| # | 問題 | 位置 |
|---|---|---|
| 1 | 相機是憑空捏造的固定值（hfov=65 / pitch=−16 / setback=0.8），從沒看過使用者的照片 | `scene_graph_to_depth._build_camera` |
| 2 | 房間是個空長方體盒子，尺寸取自 LLM 猜測（fallback 直接寫死 5×4×3）；原照片的窗、門、牆角、樑柱全部消失 | `_add_room_shell` + `_room_dims` |
| 3 | 投影圖固定 1024×1024，但 renderer 的 `output_size` 依原圖比例決定 → ControlNet 收到的條件圖被**拉伸變形** | `nodes.renderer` |
| 4 | 深度極性反了：`load_depth` 註解寫 0=近，但 Depth-Anything 存的是 255=近，於是 `layout_from_depth` 的 foreground/background 整組顛倒，餵給 LLM 的「現有佈局」是錯的 | `depth_to_layout.load_depth` |
| 5 | 光柵化在螢幕空間**仿射內插距離**，不是透視正確的；且輸出編碼成線性距離而非 disparity，與 Depth-Anything／ControlNet 的訓練慣例不符 | `_raster_triangle` / `project_scene_graph_to_depth` |
| 6 | 預設後端 `kontext` 只是「鬆散參考深度」，不做逐格對齊 | `Config.LAYOUT_DEPTH_CONTROL_BACKEND` |

## 9. 修法：把家具投影回**原始照片自己的地板**

不要合成假房間。地板是一個平面 → **俯視平面圖到影像是一個 homography**，
由地板在影像中的四個角完全決定，不需要 metric 3D 重建、不需要估焦距。

```
原始照片 depth.png + segmentation.png
        │  擬合地板：牆腳線 → 四角 → homography；消失線 → 家具高度
        ▼
俯視 (x,y) ─ H ─▶ 影像 (u,v)      家具 footprint 落在照片裡真實的地板位置
        │  舊家具清空（保留窗/門/牆），新家具長方體 z-buffer 疊上
        ▼
與原照片同視角、同比例的深度圖 → FLUX depth ControlNet
```

相機視角、房間比例、建築結構全部自動與原圖一致 —— 因為底圖就是原圖的深度。

### 9.1 三段式求解（`photo_geometry.resolve_floor_geometry`）

| 層級 | `projection_mode` | 條件 | 作法 |
|---|---|---|---|
| A | `photo_anchored` | 牆腳線（floor/wall 交線）看得到 | 對每列/欄取地板邊界像素擬合左/右/遠三條牆腳線 → 四角 → homography。**只採用外側緊鄰牆面的樣本**；被家具擋出來的假邊界會把線拉歪，必須剔除。單側缺失時用消失線把已知那條側牆線平移出去 |
| B | `photo_camera` | 牆腳線看不到（真實照片的常態） | 消失線由**地板/天花板兩片平行平面**的 disparity 解出封閉解；看不見的遠牆腳線用**遠牆的 disparity 代回地板平面**反求。無 roll/yaw 時往深處的平行線交會於主消失點 `(cx, v_h)`，梯形即完全確定 |
| C | `synthetic` | 沒上傳照片、或連地板都看不到 | 退回原本的合成相機 + 空盒子 |

實測 `artifacts/vision/` 既有的 11 組真實照片：6 組走 B（A 幾乎不會成立 —— 居家照片
的地板總是被家具團團圍住），4 組是完全沒有地板的特寫（正確退回 C）。
合成 ground-truth 測試中 A 的四角與消失線誤差 < 0.5 px。

### 9.2 關鍵細節

- **消失線**是家具高度換算的樞紐（`v' = v_h + (v − v_h)(1 − h/eye_height)`）。
  三個估計器依可信度排序：兩側牆腳線都在 → `H⁻¹` 第三列（直線變換是 `l' = H^{-T} l`，
  無窮遠線對應 **H 的反矩陣**第三列，不是 H 第三列）；否則地板+天花板平面法；
  再不行假設相機水平。估出來若落在可見地板下方就夾回合理區間。
- **量遠牆距離不能含 `windowpane` / `door`**：窗外門外是室外，深度遠超本房間，
  會把遠牆估到天邊（實測 disparity 從 93 掉到 16，遠牆腳線整整跑掉 160 px）。
- **俯視矩形要取「能完整入鏡的最大矩形」**：俯視看去，可見範圍是離相機越遠越寬的
  扇形，所以矩形寬度由**最近**那一邊決定。若改用遠邊的畫面寬度，近處家具會被推出畫面。
- **舊家具清空**：分割標成地板的像素換成解析地板平面（抹掉深度凹凸），其餘被清掉的
  像素用最近的建築表面補值。曾試過以消失線當地板/牆分界，會把整片中景誤判成地板、
  外插出比整張照片最遠處還遠的黑洞 —— 因此 disparity 一律夾在照片實際出現的範圍內。

## 10. 第二輪的逐檔改動

| 檔案 | 類型 | 改動 |
|---|---|---|
| `designbridge/photo_geometry.py` | **新檔** | 地板 homography / 消失線 / 清空舊家具，純 NumPy（scipy 選用） |
| `designbridge/scene_graph_to_depth.py` | 修改 | 新增 `project_layout_onto_photo()`；z-buffer 改為 **inverse-depth 語意**（平面的 1/深度在螢幕空間才是仿射的 → 透視正確），輸出改為 disparity 編碼以對齊 Depth-Anything |
| `designbridge/layout_agent.py` | 修改 | `run_layout_agent` 收 `vision_features` / `output_size`；`_generate_projected_depth` 改為三段式並回傳 `projection_mode` |
| `designbridge/nodes.py` | 修改 | 佈局節點傳入 vision + 輸出尺寸；新增 `_fit_condition_image()` 把條件圖**置中裁切**到輸出尺寸（原本會被後端拉伸剪切幾何）；深度後端支援 `auto` |
| `designbridge/depth_to_layout.py` | 修改 | 修正深度極性（`load_depth` 反相），foreground/background 不再顛倒 |
| `designbridge/config.py` | 修改 | 新增 `LAYOUT_PHOTO_ANCHORED_DEPTH` / `LAYOUT_CAMERA_EYE_HEIGHT`；`LAYOUT_DEPTH_CONTROL_BACKEND` 預設改 `auto` |

新增設定：

```python
LAYOUT_PHOTO_ANCHORED_DEPTH  = true   # DESIGNBRIDGE_LAYOUT_PHOTO_ANCHORED_DEPTH
LAYOUT_CAMERA_EYE_HEIGHT     = 1.5    # DESIGNBRIDGE_LAYOUT_CAMERA_EYE_HEIGHT（只影響家具高度）
LAYOUT_DEPTH_CONTROL_BACKEND = "auto" # 有 FAL_KEY → controlnet，否則 kontext
```

## 11. 現況與後續

| 元件 | 狀態 |
|---|---|
| 照片錨定投影（A/B/C 三段） | ✅ 合成 ground-truth 誤差 < 0.5 px；11 組真實照片 7 組可錨定 |
| 條件圖尺寸對齊 | ✅ 置中裁切到 `output_size`，不再拉伸 |
| 深度極性 / 透視正確性 | ✅ 已修 |
| live graph 端到端 | ✅ 佈局節點會傳 vision_features，renderer 會覆蓋深度並記錄 `layout_projection_mode` |
| 真正 FLUX depth ControlNet 後端 | ⚠️ 程式碼已備、`auto` 下有 `FAL_KEY` 就會走；仍未實際出圖驗證（本機 HF/fal 額度已用罄，402/410） |

**建議下一步：**

1. 設 `FAL_KEY` 實際出圖，比對成圖與原照片的構圖；微調 `depth_conditioning_scale`（0.5〜0.8）。
2. 家具高度目前靠 `LAYOUT_CAMERA_EYE_HEIGHT` 假設，若成圖家具偏高/偏矮就調這個值。
3. 舊家具清空目前是最近鄰補值，邊界會有 Voronoi 塊狀感；若 ControlNet 對此敏感可改成
   沿牆面/地板平面外插。
4. segmentation mask 已產出但尚未接成第二條 ControlNet 條件。
