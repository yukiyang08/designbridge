# 視覺預處理與佈局規劃最佳化

> 針對三個問題的診斷與改動：Layout Agent 迭代成效不佳、分割/深度精度、預處理耗時。
> 每一項都先量測再動手；其中一項量測後的結論是**不該做**，記錄在第 4 節。

---

## 1. 量測環境

```
Windows 11 ARM64 · Qualcomm Snapdragon
torch 2.10.0+cpu   ← 沒有 CUDA，兩個視覺模型都跑在 8 執行緒 CPU 上
測試照片：test/室內.jpg (1500×1001)、test/室內2.jpg (1200×901)
```

**改動前的基準**（`artifacts/vision` 清空後量測）：

| | 冷啟動（含模型載入） | 熱（模型已在記憶體） |
|---|---|---|
| 深度 Depth-Anything-V2-**Large** | 144.5s | 22.3s |
| 分割 UPerNet-ConvNeXt-small | 12.8s | 8.5s |
| **合計** | **157.3s** | **30.8s** |

> 重要：**深度才是瓶頸，不是分割**。深度的熱推論是分割的 2.6 倍，冷啟動是 11 倍。
> 直覺上「分割套件跑很久」的感受，實際來源是深度模型。

---

## 2. 問題一：Layout Agent 迭代三次成效不佳且耗時

### 2.1 成因

`run_layout_agent` 原本的迴圈是「評分 → 把分數丟回 LLM → 要一份新佈局」，最多三輪。
問題不在次數，在**回饋內容**：

```python
# core/prompts.py — LAYOUT_REFINEMENT_PROMPT 送給 LLM 的全部內容
目前佈局的軟性評分如下（0 = 差，1 = 佳）：
- 動線 (circulation): 0.42
- 平衡 (balance): 0.61
...
```

五個純量，**沒有指出是哪一件家具造成的**。LLM 無從針對性修正，只能整盤重排，
每輪卻要付一次完整的 LLM 往返。副作用是結果不可重現——同樣輸入每次跑出不同佈局。

### 2.2 解法：語意交給 LLM，幾何交給程式

五個軟性分數都是家具方框的廉價純函數（`_score_soft_constraints`），
所以幾何最佳化不需要 LLM：

```
LLM 一次呼叫  →  哪些家具、大致在哪個區域（語意，LLM 擅長）
        ↓
_settle()      →  硬約束 + enforcer
        ↓
_optimize_positions()  →  精確座標（幾何，程式擅長）
        ↓
_settle()      →  重新釘住 must_move、重跑 enforcer
        ↓
兩版取較好者   →  「絕不比原本差」保證
```

`_optimize_positions` 是帶衰減步長的 hill-climbing：隨機挑一件可動家具、
高斯擾動位置、目標函數變好才接受。目標函數 = 加權軟性分數 − 重疊面積與越界的懲罰。

```python
# layout/layout_agent.py
sigma = 0.18 * (1.0 - step / steps) + 0.01   # 由粗到細
```

固定 seed，因此同樣的初稿永遠優化成同樣的佈局。

### 2.3 關鍵設計：未指名的家具凍結

```python
def _movable_indices(items, constraints, photo_anchored):
    if not photo_anchored:
        return [i for i, it in enumerate(items) if not it.pinned]
    touched = _touched_types(constraints)
    return [i for i, it in enumerate(items)
            if not it.pinned and normalize_furniture_type(it.type) in touched]
```

有照片時，使用者沒要求變動的家具在深度圖裡本來就**保留原始像素**
（見 `_classify_preserved` 與 `build_empty_room_disparity`），
所以規劃時移動它們對成圖毫無影響——只會擾動分數，把真正該動的家具拖到更差的位置。
凍結它們讓搜尋更快，也更符合「我只叫你動一件」。

`must_move` 已解算落點的家具標記 `pinned`，同樣排除在可動集合外，避免優化器把它推離目的地。

### 2.4 成效

| 情境 | 優化前 | 優化後 | 耗時 | 約束檢查 |
|---|---|---|---|---|
| 全部可動（無照片） | 0.537 | **0.998** | 151ms | — |
| 凍結未指名 | 0.537 | **0.879** | 184ms | 未指名家具座標零位移 |
| 客廳 move + add | 0.695 | **0.855** | — | 全過 |
| 客廳 純風格 | 0.715 | **0.812** | — | 全過 |
| 臥室 move + add | 0.635 | **0.756** | — | 全過 |

對照：舊做法要多付最多兩次 LLM 往返，才**可能**越過 0.65 門檻。

---

## 3. 問題三：預處理耗時（先講，因為問題二的結論依賴它）

五項改動。冷啟動與熱的貢獻不同：

| 改動 | 冷啟動 | 熱 |
|---|---|---|
| 深度 Large → Small | ✔ 載入與推論都變小 | ✔ 22.3s → 6.4s |
| warmup 預載視覺模型 | ✔ 把載入移出請求 | — 本來就不含載入 |
| 深度 ∥ 分割並行 | ✔ | ✔ 18.95s → 12.21s |
| 工作解析度上限 1280 | ✔ 略 | ✔ 12.21s → 9.4s |
| 內容定址快取 | ✔ 第二次起 0.03s | ✔ 同左 |

### 3.1 換小模型（7.1×）

純推論時間，輸入 518×770：

| 模型 | 推論 |
|---|---|
| Large (335M) | 16.65s |
| Large @392 解析度 | 10.10s |
| Large + 動態 int8 量化 | **25.34s** ← 在 ARM 上反而更慢，已排除 |
| Base (97.5M) | 5.45s |
| **Small (24.8M)** | **2.33s** |

精度驗證見第 4.2 節。

### 3.2 warmup 預載（−144s）

`core/warmup.py` 原本只預載 CLIP 與 embedder，**完全沒碰視覺模型**，
所以那 144 秒全部記在第一個上傳照片的使用者頭上。

```python
def _warm_vision() -> None:
    from designbridge.layout.vision import _load_depth_model, _load_upernet
    if Config.ENABLE_DEPTH:
        _load_depth_model(Config.DEPTH_MODEL)
    if Config.ENABLE_SEGMENTATION:
        _load_upernet(Config.SEGMENTATION_MODEL)
```

靠的是兩個 loader 上原有的 `@lru_cache(maxsize=1)`：啟動時呼叫一次，管線內的呼叫直接命中。
**加上 warmup 後，第一次請求就退化成「熱」的數字。**

### 3.3 並行（−35%）

深度與分割互相獨立。torch 在 op 內部釋放 GIL，所以即使共用同一個 8 執行緒池仍有增益
（單一模型本來就吃不滿）。

```python
with ThreadPoolExecutor(max_workers=2) as pool:
    depth_future = pool.submit(_depth)
    seg_future = pool.submit(_seg)
    depth_path = depth_future.result()
    seg_path, seg_meta_path = seg_future.result()
```

### 3.4 工作解析度上限（`VISION_MAX_EDGE = 1280`）

省的不只是推論——**下游全部是 O(像素)**：地板/天花板平面擬合、
`_harmonic_fill` 的七輪高斯、邊界抽取、ControlNet 條件圖。手機照常是 4000px，
而兩個模型內部本來就降到 ~512（深度 518、UPerNet 512），超過的解析度買不到細節。

### 3.5 內容定址快取

輸出目錄由 `artifacts/vision/{task_id}/` 改成 `artifacts/vision/{內容雜湊}/`：

```python
h.update(照片位元組)
h.update(f"{depth_model}|{segmentation_model}|{max_edge}")
```

換模型或改解析度會自動失效。反覆調 prompt 重跑同一張照片時直接命中。
`layout_from_depth` 是 dict 不是檔案，額外存成 `layout_from_depth.json` 一起快取。

### 3.6 結果

```
冷啟動  157.3s → 24.7s      （再加 warmup，使用者感受到的 ≈ 9.4s）
熱       30.8s →  9.4s
重跑同一張照片      0.03s
```

---

## 4. 問題二：分割圖／深度圖更準確

### 4.1 分割保比例推論 —— 量測後決定**不做**

分割的 processor 把 1500×1001 壓成 **512×512 方形**，比例被破壞。看起來該修。實測：

| 照片 | 方形 512 | 保比例 | 地板遮罩 IoU |
|---|---|---|---|
| 室內.jpg | 4.80s，地板 12.5% | (768,512) 6.71s，地板 12.9% | 0.956 |
| 室內2.jpg | 4.68s，地板 6.0% | (672,512) 6.19s，地板 5.9% | 0.956 |

**IoU 0.956、慢 40%。** UPerNet 本來就是用這種方形縮放訓練的，壓縮沒有造成實質傷害。

> **結論：分割模型不是精度瓶頸，這項不改。**
> 沒有為了「看起來有做」而付出 40% 的時間成本。

### 4.2 深度換小模型的精度驗證

下游怎麼用深度圖，決定了什麼樣的精度才重要：

- `_fit_plane_disparity` 把地板/天花板擬合成**平面**（全域穩健擬合，不看細節）
- 遠牆距離取 disparity 的**第 10 百分位**（穩健統計）
- `depth_to_layout` 只做分層與梯度統計

都不讀細節。用**相同的分割**、只換深度模型，比較解出來的房間幾何：

| 深度模型 | 室內1 消失線 | 室內1 遠牆腳 | 室內2 消失線 | 室內2 遠牆腳 |
|---|---|---|---|---|
| Large | 315.0 | 740.6 | 343.3 | 689.0 |
| Base | 342.5 | 740.6 | 339.3 | 693.1 |
| Small | 350.6 | 736.7 | 343.1 | 686.2 |

- **遠牆腳線最多只差 4px**——這是決定家具落點的量，也就是最該準的數字。
- 室內1 的消失線 Large 給 315、Base 342、Small 351：**Large 才是離群值**，不是 Small 比較差。
  成因是天花板常常沒有紋理，`_horizon_from_parallel_planes` 的平面擬合不穩定
  ——這是程式的穩健性問題，不是模型解析度問題。

### 4.3 解析度上限的精度驗證

1280 上限對幾何無損：

| | 全解析度 (1500×1001) | 上限 1280 (1280×854) |
|---|---|---|
| 消失線 v/H | 0.350 | 0.352 |
| 遠牆腳 v/H | 0.736 | 0.736 |

---

## 5. 順帶修掉的四個既有 bug

都不是這次改動造成的，是原本就在跑的錯誤。

### 5.1 碰撞解完之後又被裁切製造出來

`_push_apart` 把重疊的家具分開，接著 `_clip_to_room` 把超出牆面的推回室內，
**正好推回鄰居身上**。所以 `collision_free` 一直回報 False，而且加迭代次數毫無用處——
裁切每次都撤銷分離的成果。

```
push(60)+clip  : [('sofa', 'coffee_table')]
push(200)+clip : [('sofa', 'coffee_table')]   ← 加到 600 也一樣
```

修法：把裁切移進迴圈內，讓它與分離一起收斂。

### 5.2 地毯被當成實體障礙物

沙發本來就該踩在地毯上。原本的 `_overlaps` 把地毯視為實體，
導致 `_push_apart` 一直想把座位推離地毯，並在完全正常的佈局上回報碰撞。

```python
_UNDERLAY_TYPES = frozenset({"rug", "carpet", "mat", "floor_mat", "runner"})
```

### 5.3 地毯被算成擋住窗戶

採光評分的判定是 `y < 0.15 and h > 0.08`，但 **`h` 在俯視圖是「縱深」不是「高度」**。
0.24 深的地毯因此觸發尺寸判定，被當成擋窗的高大家具，害採光分數歸零。

### 5.4 採光評分懲罰「服從指令」

使用者說「把書桌移到窗邊」，系統照做，然後採光評分因為窗戶被擋而扣分，
優化器於是傾向把書桌搬離窗邊。被 `must_move` 釘住（`pinned`）的家具現在豁免於這條懲罰。

---

## 6. 逐檔改動

| 檔案 | 改動 |
|---|---|
| `designbridge/layout/vision.py` | 新增 `_load_image()`（解析度上限）、`_cache_key()`；`run_depth_estimation` / `run_segmentation` 加 `max_edge` 參數；`run_visual_preprocessing` 改寫為內容定址快取 + `ThreadPoolExecutor` 並行 |
| `designbridge/core/warmup.py` | 新增 `_warm_vision()` 步驟，預載深度與分割模型 |
| `designbridge/core/nodes/visual_preprocessing.py` | `visual_preprocessing_local` 傳入 `max_edge` / `parallel` / `use_cache` |
| `designbridge/core/nodes/requirement.py` | `space_info` 門窗正規化（`_opening_to_box` / `_normalize_space_info`） |
| `designbridge/core/nodes/renderer.py` | 條件圖尺寸對齊（`_fit_condition_image`）、分割邊界條件（`_seg_to_edge_condition`）、多 ControlNet 疊加 |
| `designbridge/render/render_backends.py` | `_render_flux_controlnet_depth_fal` 支援 `extra_controls` 多條件堆疊 |
| `designbridge/layout/layout_agent.py` | 新增 `_layout_objective()` / `_movable_indices()` / `_optimize_positions()`；`run_layout_agent` 的迭代迴圈改為 `_settle` + 優化器 + 「絕不比原本差」；`FurnitureItem` 加 `pinned` 欄位；`_overlaps` 與採光評分排除 underlay；`_push_apart` 迴圈內裁切 |
| `designbridge/core/config.py` | 深度/分割模型改為可由環境變數覆寫；新增視覺與優化器相關設定（見第 7 節） |

> **關於路徑**：本文路徑已對齊上游的目錄重構（`designbridge/` 拆成
> `core/` `layout/` `render/` `style/` `pricing/` 子套件，舊的 `nodes.py`
> 拆成 `core/nodes/` 底下 8 個節點檔）。照片錨定投影用到的兩個模組也一併歸位：
>
> ```
> designbridge/photo_geometry.py   → designbridge/layout/photo_geometry.py
> designbridge/instance_select.py  → designbridge/layout/instance_select.py
> ```

---

## 7. 新增設定（`designbridge/core/config.py`）

```python
# 視覺預處理
DEPTH_MODEL         = "depth-anything/Depth-Anything-V2-Small-hf"
                                     # DESIGNBRIDGE_DEPTH_MODEL（有 GPU 可改回 Base / Large）
SEGMENTATION_MODEL  = "openmmlab/upernet-convnext-small"
                                     # DESIGNBRIDGE_SEGMENTATION_MODEL
VISION_MAX_EDGE     = 1280           # DESIGNBRIDGE_VISION_MAX_EDGE（0 = 不限制）
VISION_PARALLEL     = True           # DESIGNBRIDGE_VISION_PARALLEL
VISION_CACHE        = True           # DESIGNBRIDGE_VISION_CACHE

# 佈局優化器
LAYOUT_OPTIMIZER_STEPS = 2000        # DESIGNBRIDGE_LAYOUT_OPTIMIZER_STEPS
LAYOUT_LLM_REFINE      = False       # DESIGNBRIDGE_LAYOUT_LLM_REFINE
                                     #   true = 把舊的 LLM 迭代疊回優化器之上
```

搬到有 GPU 的機器時，主要調整的是 `DEPTH_MODEL`（可回到 Large）與 `VISION_MAX_EDGE`。

---

## 8. 尚未處理

| 項目 | 影響 |
|---|---|
| **既有佈局的基準是深度 blob** | 餵給規劃器的「現有空間佈局」來自 `depth_to_layout` 的連通區域猜測，type 是 `sofa_or_bed` / `unknown_furniture`，且**完全沒有座標**；但 prompt 要求「其餘家具沿用現有佈局的座標」。這是「只叫你動一件、結果整間都變了」的根源。優化器的凍結機制緩解了它，但沒有根治 |
| **生成沒有原照片當錨** | 送進 fal 的只有 prompt 加 ControlNet 條件，沒有 img2img。深度與邊界能鎖住幾何，但材質與光線不會延續原照片 |
| **調和填補抹平牆角** | `_harmonic_fill` 填補牆與天花板破洞時，順手把牆角的深度不連續也抹掉。邊界 ControlNet 補回一部分，深度圖本身仍缺那道階躍 |

---

## 9. 重現量測

```bash
# 基準：深度 vs 分割，冷/熱
python -u -c "
import time, torch; from pathlib import Path
torch.set_num_threads(8)
from designbridge.layout.vision import run_depth_estimation, run_segmentation
img='test/室內.jpg'; out=Path('artifacts/_bench'); out.mkdir(parents=True, exist_ok=True)
for tag, fn, kw in [('depth', run_depth_estimation, dict(model_name='depth-anything/Depth-Anything-V2-Large-hf')),
                    ('seg',   run_segmentation,     dict(model_name='openmmlab/upernet-convnext-small'))]:
    for phase in ('cold','warm'):
        t=time.perf_counter(); fn(img, out_dir=out, **kw); print(f'{tag} {phase}: {time.perf_counter()-t:.1f}s')
"

# 幾何驗證：換深度模型，比較消失線與遠牆腳線
# （用相同 segmentation，只變動 depth）
python -u -c "
import numpy as np; from pathlib import Path
from designbridge.layout.vision import run_depth_estimation, run_segmentation
from designbridge.layout.photo_geometry import resolve_floor_geometry
img='test/室內.jpg'; out=Path('artifacts/_bench')
seg, meta, _ = run_segmentation(img, model_name='openmmlab/upernet-convnext-small', out_dir=out)
for tag, m in [('Large','depth-anything/Depth-Anything-V2-Large-hf'),
               ('Small','depth-anything/Depth-Anything-V2-Small-hf')]:
    d=out/tag; d.mkdir(exist_ok=True)
    dp,_=run_depth_estimation(img, model_name=m, out_dir=d)
    g=resolve_floor_geometry(dp, seg, meta, eye_height=1.5)
    print(tag, '消失線', float(np.mean(g.horizon_v(np.array([g.image_size[0]/2])))), '遠牆腳', g.floor_quad[0][1])
"

# 優化器
python -u -c "
import time
from designbridge.layout.layout_agent import FurnitureItem, _optimize_positions, _score_soft_constraints, _weighted_score
space={'estimated_size':{'width':5.0,'depth':4.0},'windows':[],'doors':[]}
items=[FurnitureItem('sofa_1','sofa',0.05,0.55,0.30,0.13),
       FurnitureItem('coffee_table_1','coffee_table',0.10,0.45,0.15,0.10),
       FurnitureItem('tv_unit_1','tv_unit',0.08,0.06,0.22,0.07)]
b=_weighted_score(_score_soft_constraints(items,space))
t=time.perf_counter(); items,obj,acc=_optimize_positions(items,space,list(range(len(items))),steps=2000)
print(f'{b:.3f} -> {_weighted_score(_score_soft_constraints(items,space)):.3f}  {(time.perf_counter()-t)*1000:.0f}ms')
"
```

> 注意量測變異：這台機器上分割的端到端在不同次可跑出 8.5s 到 12.6s。
> 本文數字均取自同一輪量測以便對照。
