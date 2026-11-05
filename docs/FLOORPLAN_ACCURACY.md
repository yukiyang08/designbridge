# 提升平面圖辨識精準度

> 更新：2026-11-05

房間切割本身已經做得很細，錯誤主要出在三個地方：Gemini 呼叫的設定、家具框的座標與比例尺、下游只認矩形。建議先建好評估集，再依序修呼叫設定、加 few-shot、讓下游支援不規則空間；微調模型列為未來計畫，等前面都做完、分數仍不夠時再評估。

## 1. 現況與錯誤來源

目前的流程：

1. **品質檢查**（`layout/floorplan_quality.py`）：短邊小於 300px、對比小於 30、銳利度小於 50 直接擋下；Gemini 同時判斷是不是平面圖。
2. **找房間中心點**（`_room_seeds`）：Gemini 回傳每間房的中心點、圖上寫的房名、房間類型，結果依圖片內容快取。
3. **牆線切割**（`layout/floorplan_segment.py`）：從牆線算出每間房的 polygon，Gemini 漏掉的房間會自動補種子點。
4. **逐區確認**（`_relabel_rooms`）：在圖上用字母標出每個區域，請 Gemini 平行回答 3 次取多數；只改圖上沒寫房名的區域，並合併被切開的同一間房（小塊面積小於大塊的 35%）。
5. **備援**（`_detect_rooms_by_boxes`）：切割失敗時，改請 Gemini 直接框出每間房的矩形。
6. **家具辨識**（`parse_floor_plan_image`）：裁出單間房（房外塗白、外加 3% 留白），Gemini 回傳家具框 `box_2d`，尺寸超出標準 0.4 到 2 倍的當誤判丟掉。
7. **下游**：佈局引擎、碰撞檢查、深度投影都只用矩形的 `room_w × room_d`。

| 錯誤來源 | 影響 | 位置 |
| --- | --- | --- |
| Gemini 呼叫忽略 `json_mode` | 整戶圖偶爾回傳壞掉的 JSON，只能用正規表示式撈回部分資料（`_salvage_boxes`） | `render/llm.py` |
| 思考被關掉（`GEMINI_THINKING_BUDGET=0`） | 空間推理任務少了推理步驟 | `core/config.py` |
| 沒設圖片解析度 | CAD 圖上的小字和家具符號容易糊掉 | `render/llm.py` |
| 家具框座標基準不一致 | 提示詞要求以房間內部為基準，送進去的卻是含牆和留白的裁切圖，造成系統性偏移 | `floorplan_parse.py` |
| 比例尺靠坪數推估 | 比例一錯，尺寸檢查會把真的家具也丟掉 | `routers/floorplan.py` |
| 沒問旋轉角度 | 斜放的家具一律畫成正的 | `floorplan_parse.py` |
| 下游只認矩形 | L 型房的缺角被當成地板，家具可能擺進去 | 佈局、深度投影 |

## 2. Gemini + Python 的優化

分工原則：**Gemini 負責「看懂」**（房名、類型、這是什麼家具），**Python 負責「量準」**（牆線、邊界、座標換算、合理性檢查）。讓 LLM 直接吐精確座標是最不穩的一環，能交給幾何運算的就不要交給它。

| 項目 | 做法 | 解決什麼 |
| --- | --- | --- |
| 結構化輸出 | Gemini config 加 `response_mime_type="application/json"` 和 `response_schema` | 不再回傳壞 JSON，可以拿掉正規表示式的撈回邏輯 |
| 開啟思考 | `call_llm` 加單次呼叫的 `thinking` 參數，只在平面圖的四個呼叫開 low 或 medium | 空間推理更準；其他呼叫維持快速 |
| 提高圖片解析度 | 設 `media_resolution=MEDIA_RESOLUTION_HIGH`，或先放大到長邊約 1600px | 小字、小家具符號讀得清楚 |
| 修正座標基準 | 請 Gemini 多回傳房間內部的 `room_box_2d`，或用牆線遮罩算出內部範圍，再把家具框換算進去 | 消除裁切留白造成的偏移與縮放 |
| 讀尺寸標註當比例尺 | 請 Gemini 讀圖上的尺寸數字（如 3600、4200）和它對應的牆段，Python 求出每公尺幾個像素；讀不到才退回坪數 | 尺寸檢查不再誤丟真的家具 |
| 問旋轉角度 | 提示詞要求 `rotation`（0、90、180、270），框改成家具本身的尺寸 | 斜放或直放的床、沙發方向正確 |
| 家具也投票 | 同一題問 3 次，用框的 IoU 配對，取多數與平均位置（同 `_vote_regions` 的做法） | 減少單次回答的搖擺與幻覺 |

結構化輸出的寫法示意（`google-genai`）：

```python
from google.genai import types

schema = {
    "type": "object",
    "properties": {
        "is_floor_plan": {"type": "boolean"},
        "rooms": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "room_type": {"type": "string", "enum": ["living_room", "bedroom", "kitchen", "dining_room",
                                                         "study", "bathroom", "balcony", "circulation", "other"]},
                "point": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["label", "room_type", "point"],
        }},
    },
    "required": ["is_floor_plan", "rooms"],
}
cfg = types.GenerateContentConfig(
    response_mime_type="application/json",
    response_schema=schema,
    media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH,
    temperature=0.3,
)
```

圖片品質檢查已經上線，無效輸入不會進到辨識流程。門檻是用 `artifacts/uploads` 裡 71 張真實平面圖量出來的（最小短邊 369px、對比 64、銳利度 113），刻意定得比它們低很多。

## 3. Few-shot 提示

Few-shot 是把「範例圖 + 正確答案」放進提示詞，讓模型照著學。它能拿到微調的大部分好處，而且換模型版本時可以直接沿用。

**適合用在錯誤集中在特定情境時**，例如：

- 凸窗被判成陽台
- 門弧、尺寸標註被當成家具
- 沒寫房名的廚房、走道判斷錯誤

**怎麼挑範例**

- 從評估集的錯誤案例挑 2 到 3 張，每張涵蓋一種常錯的情境。
- 每張配一份人工確認過的正確答案 JSON，格式跟正式回答完全一樣。
- 範例**不可以**同時放在評估集裡，不然分數會虛高。

**放法**：用多輪對話，範例圖和答案在前，要辨識的圖在最後。

```python
from pathlib import Path
from google.genai import types

def img(path):
    return types.Part.from_bytes(data=Path(path).read_bytes(), mime_type="image/png")

contents = [
    types.Content(role="user", parts=[img("fewshot/bay_window.png"), types.Part.from_text(text=prompt)]),
    types.Content(role="model", parts=[types.Part.from_text(text=Path("fewshot/bay_window.json").read_text())]),
    types.Content(role="user", parts=[img("fewshot/door_arcs.png"), types.Part.from_text(text=prompt)]),
    types.Content(role="model", parts=[types.Part.from_text(text=Path("fewshot/door_arcs.json").read_text())]),
    types.Content(role="user", parts=[img(target_path), types.Part.from_text(text=prompt)]),
]
```

**注意事項**

- 每多一張範例圖就多一份圖片 token，延遲和費用都會增加；範例不變時可用 Gemini 的 context caching。
- 範例跟提示詞是一組的：換範例就要換 `_SEED_PROMPT_VERSION` 或 `_LABEL_PROMPT_VERSION`，讓舊快取失效。
- 一定要在評估集上比較「有 few-shot」和「沒有 few-shot」的分數，確認真的有幫助才保留。

## 4. 不規則空間（目前只認成方框）

**辨識端其實已經做到了**：`segment_rooms` 會輸出 L 型、斜牆等形狀的 `polygon`。問題是從裁切開始，下游全部只認矩形：

| 環節 | 現在的行為 | 位置 |
| --- | --- | --- |
| 裁切 | 用 polygon 把房外塗白，但輸出的還是矩形圖 | `routers/floorplan.py` `crop_floor_plan` |
| 家具解析 | 房間尺寸只有 `room_w × room_d` | `floorplan_parse.py` |
| 佈局與碰撞 | `_clip_to_room` 只把家具夾在矩形內 | `layout/layout_enforce.py` |
| 整層圖 | `_snap_rects` 把每間房對齊成矩形 | `layout/floorplan_upload_plan.py` |
| 深度投影 | 房殼是矩形盒子 | `layout/scene_graph_to_depth.py` |

結果是 L 型房缺掉的那一角被當成地板，家具可能擺進去，出圖的房間也是方的。建議分兩階段做。

**階段一：佈局層支援（優先）**

1. 修正家具框的座標基準（見第 2 節），讓家具位置對準房間內部。
2. 把房間 polygon（正規化座標）放進 `scene_graph`，一路傳到佈局引擎。
3. bbox 裡不屬於房間的部分當成**禁區**：硬約束和最佳化都檢查家具 footprint 不能碰到禁區，可以沿用 `_pretrim_boxes` 用 PIL 畫遮罩的做法。
4. 2D 平面圖（`floorplan_render.py`）和前端編輯器照實際形狀畫出 L 型。

**階段二：出圖也照形狀（之後）**

1. `scene_graph_to_depth` 依 polygon 生成牆面，深度圖才會有真的轉角。
2. 相機擺位避開缺角，避免從牆裡往外拍。

階段二風險較大，而且出圖通常只從一個角度拍，L 型房從多數角度看起來接近矩形，所以優先度較低。

**驗收**：準備 L 型、斜牆、凸窗各至少 2 張測試圖，確認家具不會擺進缺角、2D 平面圖形狀正確。改到 state 欄位時要同步更新 `docs/AGENTSTATE.md`。

## 5. 評估集與驗證

沒有評估集，改提示詞、調參數都只能靠感覺。目前準備了兩份資料：

| 資料集 | 內容 | 狀態 |
| --- | --- | --- |
| CubiCasa5K 子集 | 官方 test split 隨機抽 50 張單層平面圖，每張附人工標註的房間 polygon、類型、牆、門窗、衛浴設備 | 已下載 |
| 台灣自有集 | 從 `artifacts/uploads` 挑 20 到 30 張（CAD 圖、建商銷售圖、手繪圖、單房圖），人工標註 | 待建立 |

**CubiCasa5K 子集**

- 下載：`python scripts/fetch_cubicasa_subset.py --n 50`。用 HTTP Range 只抓選中的檔案（約 18 MB），不用下載整包 5.5 GB。
- 存放：`test/data/cubicasa/<樣本>/F1_scaled.png` + `model.svg`，已加入 `.gitignore`。
- 授權：[CC BY-NC-SA 4.0](https://zenodo.org/records/2613548)，只限非商業用途（本專題可用），引用時需註明出處：Kalervo et al., *CubiCasa5K: A Dataset and an Improved Multi-Task Model for Floorplan Image Analysis*, 2019。
- 限制：芬蘭的平面圖，畫法跟台灣不同，適合驗證房間切割與類型判斷的基本能力，不能取代台灣的圖。
- 待辦：寫轉換程式，把 `model.svg` 裡的 `Space *` 房間轉成評估用的 JSON。已知兩個要處理的地方：
    - SVG 的尺寸跟圖片不同（例如 1211×1177 對 1309×1226），座標要先對齊。
    - CubiCasa 的房間類別要對照到我們的類型，對照表在轉換程式完成時確認。

**評估指標**

| 指標 | 算法 | 看什麼 |
| --- | --- | --- |
| 房間召回率 | 正確答案的房間裡，有被偵測到（IoU ≥ 0.5）的比例 | 有沒有漏房間 |
| 房間精確率 | 偵測到的房間裡，對得上正確答案的比例 | 有沒有多切、亂切 |
| 平均 IoU | 配對成功的房間，polygon 重疊程度的平均 | 邊界準不準 |
| 類型準確率 | 配對成功的房間中，類型判斷正確的比例 | 客廳、臥室、陽台有沒有判錯 |
| 家具召回率／精確率 | 家具框以 IoU ≥ 0.5 配對 | 只用台灣自有集（CubiCasa 幾乎沒畫活動家具） |
| 比例尺誤差 | 推算的房間面積 ÷ 實際面積 − 1 | 尺寸換算準不準 |

**流程**：每做一項改動就跑一次評估，把分數記在同一份表裡比較。辨識結果有快取，重跑同一組設定不會重複付費；改了提示詞就要換版本號，才會真的重新辨識。

## 6. 微調模型（未來計畫）

**現階段不建議微調**，原因：

- 第 1 節列的錯誤大多是流程問題（座標基準、比例尺、JSON、思考設定），模型再強也修不好。
- 微調通常要數百到上千張標註圖，評估集的量差一個數量級。
- Gemini 每幾個月就出新版，微調過的模型會卡在舊版，新版的能力常常直接超過微調成果。
- 除了訓練費，推論可能還要部署專屬端點。

**什麼時候值得做**：流程修好、加了 few-shot 之後，評估集上某一項分數仍明顯不夠（例如家具召回率低於 60%）。

| 選項 | 適合解決 | 資料需求 | 優點 | 缺點 |
| --- | --- | --- | --- | --- |
| Gemini 監督式微調（Vertex AI） | 房間類型、房名判斷 | 數百組圖 + 答案 | 沿用現有流程 | 支援微調的版本通常落後最新版；有部署成本 |
| 專用家具符號偵測（如 YOLO） | 家具框的位置與類型 | 數百到上千張框標註 | 小、快、便宜，座標準 | 要自己訓練、部署、維護 |
| 專用房間分割模型 | 房間邊界 | 數千張 polygon 標註 | 不依賴牆線門檻 | 現有牆線切割已經不錯，效益可能有限 |

**建議的路線**：如果要做，優先做「專用家具符號偵測」，讓 Gemini 繼續負責讀房名和判斷類型，偵測模型負責框座標，兩邊互補。可以先用 CubiCasa5K 預訓練（僅限研究用途），再用數百張台灣的圖微調。

## 7. 建議順序

1. **建評估集**：完成 CubiCasa 標註轉換與評估腳本，跑出目前的基準分數；同時開始標註台灣自有集。
2. **修呼叫設定**：結構化輸出、開啟思考、提高圖片解析度。每項分開跑評估，確認效果。
3. **修家具座標**：座標基準、尺寸標註比例尺、旋轉角度。
4. **不規則空間階段一**：polygon 傳進佈局引擎、缺角當禁區、2D 平面圖畫出實際形狀。
5. **加 few-shot**：針對評估集裡最常錯的情境挑範例，比較有無 few-shot 的分數。
6. **檢視分數，決定下一步**：還不夠再評估微調，或進行不規則空間階段二（出圖照形狀）。
