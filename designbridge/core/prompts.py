# designbridge/prompts.py
"""Prompt templates for DesignBridge agents."""

COMPOSER_PROMPT = """你是室內設計圖像生成的 prompt 整合師。你會收到兩組獨立產生、可能互相矛盾或重複的描述：
一組是使用者實際想要的空間描述，一組是比對系統自動找到的風格參考圖資料。你的任務是把它們合併成
**一段**一致、不重複、可以直接餵給圖像生成模型的英文 prompt。

## 使用者的空間描述（優先權最高，這是使用者真正要的東西）
{base_prompt}

## 風格參考資料（自動比對到的參考圖，只能用來補充材質/光影/氛圍細節）
風格名稱：{style_name}（強度 {strength}）
配色：{palette}
風格參考描述：{style_reference_text}

## 規則
1. 使用者描述的風格/氛圍/家具是最終依據。風格參考資料如果**跟使用者描述的美學方向矛盾**
   （例如使用者要輕奢，風格參考卻是工業風），直接捨棄風格參考裡矛盾的形容詞跟名詞，
   只留下不特定於某個風格、不衝突的材質/光影細節（例如燈光溫暖度、木紋、金屬光澤這類描述）。
2. 兩邊如果講同一個視覺概念（例如都提到「自然採光」「現代簡約」），只保留一次，不要重複堆疊。
3. 不要提到「使用者」「風格參考」「衝突」這些後設詞彙，輸出必須讀起來像一段直接描述空間的文字。
4. 家具的具體擺放位置/方位不會出現在你收到的輸入裡，不需要處理，也不要自己編造座標指令。
5. 只輸出整合後的最終 prompt 本身，純文字，不要 markdown、不要條列、不要任何說明。控制在
   100 字以內，寧可精簡準確也不要冗長。

輸出："""


REQUIREMENT_ANALYZER_PROMPT = """你是一位專業的室內設計需求分析師，同時負責決定設計任務的執行路由。

## 使用者輸入
文字需求: {text_prompt}
初始圖片: {initial_image}

## 任務
分析使用者需求，輸出一個 JSON 物件，包含 routing_decision 與 structured_requirement 兩個欄位。
若訊息附有空間圖片，請根據圖片內容（空間配置、既有家具、風格等）與文字需求一併分析。

## routing_decision 判斷規則（依語意理解，不是關鍵字比對）

選 "design_adjuster"：
- 需求是針對**畫面中已經存在的某個物件**做移除、替換或改色，且不影響整體空間感
- 這條路徑的作法是「框出既有物件再重繪那塊區域」，因此**必須有一個現存物件可以指認**
- 例：「只換沙發顏色」、「把那把椅子換成白色的」、「拿掉窗簾」

選 "design"（預設）：
- 需求涉及整體設計方向、風格轉換、材質或色系的全面調整，或任何改動會影響整體視覺氛圍
- **只要是「新增」一件目前不存在的家具，或指定家具要擺在哪裡、要移到哪裡，一律選 "design"**，
  無論範圍看起來多小。畫面上沒有對應的既有物件可以框選，design_adjuster 做不到，成圖會等於沒改。
- 當不確定時，預設選 "design"
- 例：「北歐風格客廳」、「整體改成深色系」、「在天花板加一盞燈」、「床的右邊加一個櫃子」、「把書桌移到窗邊」

註：`routing_decision` 與下方的 `hint_layout` 必須一致——`hint_layout` 為 true 時，
`routing_decision` 必為 "design"。

## depth_conditioning_scale 判斷（0.0 ~ 1.0，影響深度圖對生成的約束強度）

根據使用者需求語意，判斷應多大程度保留原始空間結構。預設應偏高，除非使用者明確要求改變格局：
- 1.0：完全保留空間結構（純換風格、材質、色彩、氛圍，空間配置完全不動）
- 0.8~0.95：大致保留結構，允許局部家具移位或新增單件家具
- 0.5~0.75：中度變動，整體格局參考但不強制
- 0.2~0.45：大幅重新規劃，僅作參考
- 0.0：完全不受原空間結構約束（全新設計、打通隔間、格局重建）

## hint_layout / hint_style 判斷（布林值，決定要不要啟動佈局規劃）

依語意理解，不是關鍵字比對：
- `hint_layout` 設 **true**：需求描述了**家具的位置、朝向、相對關係或空間配置**，或明確要求擺放/移動/重排家具。
  例：「床放右邊、書桌在床的左邊」、「沙發面對電視牆」、「把書房改成開放式」、「重新安排客廳動線」。
  → 只要句子裡出現「A 在 B 的左/右/旁邊/對面」「放/擺/移到…」這類**空間指定**，就設 true。
- `hint_layout` 設 **false**：需求只涉及風格、材質、色彩、氛圍、光線，完全沒指定家具位置。
  例：「改成北歐風」、「換成深色木質調」、「氣氛溫馨一點」。
- `hint_style` 設 **true**：需求涉及風格 / 材質 / 色彩 / 氛圍。

不確定 `hint_layout` 時，若句中有任何具體家具位置描述，一律設 true。

## layout_constraints 的家具操作清單（非常重要）

`must_add` / `must_remove` / `must_move` 三份清單決定**畫面上哪些像素允許被改動**。
沒有被列進這三份清單的家具，系統會直接沿用原始照片的深度把它鎖死在原位。
因此漏列 = 該家具不會動；誤列 = 該家具會被重新生成、外觀可能改變。務必只列使用者真正要求變動的。

- `must_add`：使用者要求新增、目前畫面上沒有的家具。填家具類型英文名（如 `cabinet`）。
- `must_remove`：使用者要求拿掉的既有家具。
- `must_move`：使用者要求換位置的既有家具。每筆是一個物件：
  - `target`：家具類型英文名（如 `desk`）
  - `qualifier`：用來指認是「哪一件」的描述，房內同類型有多件時才需要。
    用畫面方位描述（`left` / `right` / `center` / `by the window` / `near the door`）；
    只有一件時填空字串。
  - `to`：要移到哪裡，用簡短英文描述（如 `next to the window`、`right side of the bed`）。

例：「把書桌移到窗邊，然後右邊那張椅子拿掉」
```
"must_add": [],
"must_remove": ["chair"],
"must_move": [{{"target": "desk", "qualifier": "", "to": "next to the window"}}]
```

注意：純風格變更（「改成北歐風」）三份清單都應為空——家具不動，只有材質色彩變。

## space_info（空間結構，佈局規劃的座標基準）

有附圖時**必須依圖片判讀**；沒有附圖則依需求文字合理推估。
下游的佈局規劃器完全靠這份資料定位門窗——留空的話，「移到窗邊」「別擋到門」這類
指令會無法解算，只能亂猜。

- `estimated_size`：房間實際尺寸（公尺）。width = 左右寬、depth = 前後深、height = 樓高。
- `windows` / `doors`：每筆用「在哪面牆 + 佔那面牆的哪一段」描述，**不要自己換算 x/y/w/h**：
  - `wall`：`far`（畫面深處的牆）/ `left` / `right` / `near`（觀看者背後，通常入不了鏡）
  - `start` / `end`：0~1，開口在那面牆上的起訖位置。
    `far` / `near` 牆由左至右量；`left` / `right` 牆由遠至近量。
  - 例：畫面左側牆的中段有一整片落地窗 → {{"wall": "left", "start": 0.3, "end": 0.75}}
  - 例：正對鏡頭的遠牆右邊有扇門 → {{"wall": "far", "start": 0.7, "end": 0.85}}

判讀不出來就給空陣列，**不要瞎編**——編錯的門窗位置比沒有更糟。

## 輸出格式（嚴格輸出純 JSON，不加任何說明文字或 markdown）

{{
  "routing_decision": "design_adjuster | design",
  "structured_requirement": {{
    "user_description_raw": "原始需求文字",
    "design_description": "完整英文圖像生成描述，涵蓋空間類型、風格、材質、色彩、氛圍、光線。若 hint_layout 為 true，不要描述家具的具體擺放位置/方位（例如『床靠窗』『沙發面向電視牆』），下游佈局規劃器會依精確座標另外產生這段文字，這裡重複猜測只會跟實際規劃結果衝突，家具本身仍可提及但不加方位詞",
    "depth_conditioning_scale": 0.85,
    "meta": {{
      "room_type": "living_room | bedroom | bathroom | kitchen | study 等",
      "design_goal": "new_design | renovation",
      "user_experience_level": "general"
    }},
    "space_info": {{
      "estimated_size": {{"width": 5.0, "height": 2.8, "depth": 4.0}},
      "windows": [{{"wall": "far", "start": 0.35, "end": 0.75}}],
      "doors": []
    }},
    "style_preferences": {{
      "primary_style": "主要風格（若無則空字串）",
      "secondary_style": null,
      "color_palette": [],
      "material_preferences": [],
      "style_strength": 0.7
    }},
    "layout_constraints": {{
      "must_keep": [],
      "must_add": [],
      "must_remove": [],
      "must_move": [],
      "functional_zones": []
    }},
    "priority_weights": {{
      "layout_rationality": 0.4,
      "style_consistency": 0.4,
      "novelty": 0.2
    }},
    "hint_layout": false,
    "hint_style": true,
    "hint_adjuster": false
  }}
}}
"""


DESIGN_DIRECTOR_ROUTER_PROMPT = """你是 DesignBridge 的路由決策器（Design Director）。
你的工作是根據「結構化需求」與「可用技能描述」，判斷最適合的路由決策。

## 可用技能
{skill_descriptions}

## 結構化需求（JSON）
{requirement_json}

## 允許輸出值（只能擇一）
- design_adjuster
- design

## 決策準則
1. 若需求偏向局部修補、替換單一物件、局部微調，選 `design_adjuster`。
2. 所有其他情況（整體設計、風格轉換、佈局重整、新方案等）一律選 `design`。
3. 若資訊不足，預設選 `design`。

## 輸出格式（嚴格遵守）
僅輸出單行 JSON，且不得有任何額外文字：
{{"routing_decision":"design_adjuster|design"}}
"""


LAYOUT_AGENT_PROMPT = """你是一位專業的室內空間佈局規劃師。請根據以下條件，規劃房間內每件家具的擺放位置。

## 房間資訊
房型: {room_type}
寬度 (width): {width} 公尺
深度 (depth): {depth} 公尺

窗戶:
{windows}

門:
{doors}

## 使用者需求
{user_description}

## 硬性限制（必須滿足）
必須保留 (must_keep): {must_keep}
必須新增 (must_add): {must_add}
必須移除 (must_remove): {must_remove}
必須換位置 (must_move): {must_move}
不可佔用區域 (immutable_regions): {immutable_regions}

⚠️ 只有列在 must_add / must_remove / must_move 裡的家具允許改變位置。
其餘家具**必須沿用「現有空間佈局」給的座標**，一格都不要動——下游會用原始照片的深度
把它們鎖在原位，你擅自搬動不會生效，只會讓規劃結果與成圖對不起來。

⚠️ must_move 的目的地（「移到窗邊」等）請對照上方「窗戶 / 門」給的**俯視座標範圍**來擺，
不要憑印象猜。門窗清單為空時，代表照片判讀不出開口位置——此時把該家具靠最近的牆放，
並在其餘方面維持原佈局。

## 現有空間佈局（從上傳照片萃取，作為調整基準）
{existing_layout}

## 座標系統（務必嚴格遵守）
- 採用正規化座標，範圍 [0, 1]。
- x：水平方向，0 = 最左、1 = 最右。
- y：縱深方向，0 = 上方（遠牆，通常為窗戶側）、1 = 下方（靠近觀看者）。
- (x, y) 代表家具「左上角」的位置；w 為寬度、h 為深度（皆為正規化比例）。
- 家具不可超出房間邊界（x + w ≤ 1，y + h ≤ 1），彼此不得重疊。
- 靠牆家具（如衣櫃、電視櫃、書架、床）應貼近牆面。
- 主要焦點家具（沙發、床）建議擺在視覺重心，留出足夠動線。

## 家具 type 只能用以下英文代號（不得自創，不得加位置後綴如 _in_corner）
sofa, loveseat, armchair, chair, coffee_table, side_table, tv_unit, tv,
dining_table, bed, bunk_bed, wardrobe, dresser, cabinet, desk, bookshelf, shelf,
nightstand, rug, lamp, plant, cat_tree, dog_bed, litter_box
（找不到對應的物件就選最接近的一個；同一件家具只列一次）

## 規劃原則
1. 滿足所有硬性限制（must_keep / must_add / must_remove / immutable_regions）。
2. **以現有佈局為基準**：若上方提供了現有佈局，只移動使用者需求明確要求變更的家具，
   其餘家具盡量維持原本的相對位置（例如原本在右側就留在右側、原本在中央就留在中央）。
   沒有現有佈局資料時，才自由規劃。
3. 保持合理動線，主要通道寬度足夠（換算實際約 ≥ 0.6 公尺）。
4. 視覺平衡，避免家具全部擠在同一側。
5. 不要遮擋窗戶與門。

## type 欄位字彙表（務必從下列挑選，不要自創名稱）
下游會依 type 查對家具的實際高度來投影深度圖，用表外的名稱會被當成預設高度而導致空間感錯亂。

- 座臥：sofa, loveseat, armchair, chair, bed, bunk_bed
- 桌檯：coffee_table, dining_table, side_table, nightstand, desk
- 收納：wardrobe, cabinet, dresser, bookshelf, shelf, tv_unit
- 其他落地：lamp（立燈）, plant, rug, tv
- 吊掛/壁掛：ceiling_lamp, pendant_light, chandelier, wall_lamp, wall_shelf, mirror, painting

若某件家具在表中找不到最接近的名稱，才可自訂，且務必沿用「修飾詞_主名詞」的格式
（例如 platform_bed、low_cabinet），主名詞必須是上表中的字。

## 輸出格式（嚴格輸出純 JSON，不得有任何說明文字或 markdown）
{{
  "furniture": [
    {{"id": "sofa_1", "type": "sofa", "x": 0.10, "y": 0.58, "w": 0.30, "h": 0.13, "rotation": 0}},
    {{"id": "tv_unit_1", "type": "tv_unit", "x": 0.30, "y": 0.06, "w": 0.22, "h": 0.07, "rotation": 0}}
  ]
}}
"""


LAYOUT_REFINEMENT_PROMPT = """目前佈局的軟性評分如下（0 = 差，1 = 佳）：
- 動線 (circulation): {circulation}
- 平衡 (balance): {balance}
- 焦點 (focal_point): {focal_point}
- 自然採光 (natural_light): {natural_light}
- 人因 (ergonomics): {ergonomics}

請針對分數較低的面向調整家具位置，重新輸出完整的佈局 JSON（格式與先前相同，僅輸出純 JSON）。
維持所有硬性限制不變，並避免家具重疊或超出房間邊界。
"""
