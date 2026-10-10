"""Prompt template for extracting style parameters (Style KB) from interior images using Gemini."""

STYLE_KB_PROMPT = """
你是一位專業的室內設計風格分析師。任務：從室內設計圖像中萃取風格參數，並輸出為 Style KB JSON。

【輸入】
- 一張室內設計圖片（模型會接收到 image input）
- 此圖的既有風格標籤：{style_name}（style_id: {style_id}）。請在輸出的 style_info 中，style_id 固定為「{style_id}」，name 固定為「{style_name}」；tags 可依圖像內容補充。
- (可選) 使用者的風格需求描述：
  {user_hint}

【請執行以下步驟】

1. 圖像分析：
   - 配色：識別主色 (primary)、輔色 (secondary)、點綴色 (accent)。
   - 材質：識別地板、牆面、家具的主要材質與質感（例如：淺色木地板、霧面石材、金屬腳椅）。
   - 光影：描述主要光源類型（自然光、吸頂燈、軌道燈等）、色溫 (K 值) 與明暗對比。
   - 家具形式：描述造型語彙（直線、圓角、極簡、復古等）與擺放密度（稀疏 / 一般 / 稍密）。
   - 典型物件：列出 2~5 個代表此風格的關鍵物件（例如：藤編單椅、造型吊燈、榻榻米）。
   - 空間類型：判斷這張圖實際是哪種空間，room_type 必須是以下其中一個（沒把握就選「其他」）：
     客廳、臥室、廚房、浴室、餐廳、書房、走道、玄關、陽台、辦公室、其他。
   - 坪數估算：依畫面比例、家具尺寸、天花板高度等線索，估算這個空間大約幾坪，
     輸出一個區間（estimated_ping_min / estimated_ping_max，整數）而非單一數字——
     單張照片沒有精確比例尺，估不準，用區間誠實反映不確定性即可，不用糾結精準度，
     抓一個合理範圍就好（例如客廳抓 15~20，臥室抓 5~7）。

2. 參數化特徵：
   - 顏色全部用 HEX 表示（例如 "#F5F5F5"）。
   - 材質 / 家具使用具體名稱（例如 "light oak wood", "concrete", "linen sofa"）。
   - 光影用色溫 (color_temp, 單位 K) 與文字描述的 type。

3. 生成提示詞：
   - positive：一段適合用於生成此風格圖像的正向提示詞（英文為佳，可混中文註解）。
     **重要限制：這段文字會被套用到任意房間類型（可能跟這張參考圖是不同房間），只能描述
     材質、造型、色調、光影、氛圍等「風格屬性」，絕對不要提到房間類型或具體家具類別
     名詞**（例如不要寫 "living room"、"sofa"、"dining table"、"TV console"、"bed"、
     "kitchen island" 等）。要表達家具風格時，用造型/材質形容詞代替具體家具，
     例如不要寫 "a leather sofa"，改寫 "leather upholstery, rounded arms, low-profile silhouette"。
   - negative：一段應避免的元素（例如 "no clutter, no bright saturated colors"），
     同樣不用提到房間類型或具體家具類別名詞。

4. 設定權重：
   - ip_adapter_weight：0.0 ~ 1.0，代表此參考圖對最終風格的影響強度（例如 0.7 或 0.85）。
   - controlnet：建議控制模組（例如 "depth", "canny", 或 "none"）。

5. 撰寫自然語言描述（description）：需同時提供中文與英文兩個版本（供之後英文版 UI 使用），
   內容語意要一致，不是逐字翻譯，而是各自用該語言最自然的講法。
   **這個欄位只給使用者閱讀、不會被拿去生成圖像，所以（跟步驟 3 的 positive/negative 不同）
   可以、也應該提到這張圖實際的空間類型/房間類型**（例如「客廳」「主臥室」），
   讓使用者知道這筆風格參考資料原本取自什麼空間。
   - zh：用 2~3 句繁體中文，總結此圖的**空間類型**、風格氛圍、配色特色與空間感受。語氣自然，適合直接顯示給使用者閱讀。
     空間類型放在句子裡當名詞（例如「...的客廳」），**不要用「這是一間...」「這是一個...」「這間客廳以...」
     這類開頭句式**——每張卡片都這樣寫，讀起來很像制式模板，直接從風格特色或配色開始描述即可。
     範例：「以白色與淺木色為主調的客廳，搭配大量自然光與線條簡潔的家具，整體氛圍寧靜舒適，帶有北歐極簡的清爽感。」
   - en：用 2~3 句英文，內容對應 zh 版本，語氣自然、適合直接顯示給使用者閱讀（不是給生圖模型用的
     prompt，跟步驟 3 的 positive/negative 是不同用途）。
     例：「A living room dominated by white and light wood tones, with abundant natural light and
     clean-lined furniture, feeling calm and airy with a fresh Nordic minimalist touch.」

6. 適用性判斷（quality_review）：判斷這張圖適不適合當風格參考圖，供人工審核使用。
   - is_closeup：是否為近景/局部特寫（例如只拍一張椅子、一個燈具細節），而非完整空間構圖。
     近景圖沒辦法代表整體空間風格，is_closeup=true。
   - style_match_confidence：0.0~1.0，你有多確定這張圖真的符合被指定的風格「{style_name}」
     （不是問這張圖好不好看，是問它是否真的符合這個風格分類）。不確定或明顯不符合就給低分。
   - style_mismatch_reason：如果 style_match_confidence < 0.5，用一句話說明為什麼不像
     「{style_name}」；如果沒有疑慮，設為 null。
   - suggested_styles：不管信心分數高低，都根據圖片實際內容，從下面這個固定清單裡選出
     最符合的風格，依符合程度排序，最多 3 個（如果第一名就是「{style_id}」本身也沒關係，
     照實判斷即可，不用刻意跟原標籤不同）：
     modern（現代）、nordic（北歐）、japanese（日式）、industrial（工業）、
     american（美式）、classic（古典）、luxury（奢華）、country（鄉村）、other（其他）。
     只能用上面這幾個 style_id 英文代碼，不要自創。

7. LoRA 訓練用 caption（lora_caption）：**這欄跟步驟 1~3 的目的完全相反，務必分開處理，不要
   互相污染**——前面的欄位是要描述「風格長什麼樣」（材質/色調/氛圍），這欄是要客觀描述
   「畫面裡有什麼」，之後會綁一個 trigger word 代表風格，所以這欄故意不能提風格/材質/色調，
   讓 trigger word 去學這些視覺特徵。
   - 純英文，20~45 字，純文字（不要 JSON、條列、引號）
   - 格式：[房間類型]，[家具項目與大致位置]，[窗戶/門/牆等結構元素，如果明顯的話]，[鏡位角度]
   - 只講家具類型跟大致位置（例如 "an L-shaped sofa facing a rectangular coffee table"）
   - **絕對不要**提材質/質感名稱（marble, oak wood, brick, concrete, velvet...）
   - **絕對不要**提顏色或色調
   - **絕對不要**提光線品質或氛圍（warm, cozy, dramatic, soft diffused...）
   - **絕對不要**提任何美感判斷（elegant, minimalist, luxurious, modern...）
   - **絕對不要**提風格名稱（nordic, industrial, modern, american...）
   - 不要加 "high quality render" 這類贅詞
   - 範例："a living room, an L-shaped sofa facing a rectangular coffee table, a wall-mounted
     cabinet unit along one side, floor-to-ceiling windows on the far wall, wide-angle interior photograph"

8. 輸出 JSON（只輸出 JSON，不要多餘文字或 markdown），結構嚴格符合下列格式：

```json
{{
  "description": {{
    "zh": "2~3 句繁體中文自然語言風格描述，供使用者閱讀。",
    "en": "2~3 sentences in English, same meaning as zh but naturally phrased, for future English UI."
  }},
  "style_info": {{
    "style_id": "風格唯一識別碼，例如：japandi_zen_01",
    "name": "風格中文名稱，例如：日式侘寂風",
    "tags": {{
      "zh": ["寧靜", "大地色", "極簡"],
      "en": ["serene", "earthy tones", "minimalist"]
    }}
  }},
  "space_info": {{
    "room_type": "客廳 | 臥室 | 廚房 | 浴室 | 餐廳 | 書房 | 走道 | 玄關 | 陽台 | 辦公室 | 其他",
    "estimated_ping_min": 15,
    "estimated_ping_max": 25
  }},
  "visual_elements": {{
    "colors": {{
      "primary": "主色 HEX",
      "secondary": "輔色 HEX",
      "accent": "點綴色 HEX"
    }},
    "materials": [
      {{ "target": "地板", "type": "材質名稱", "finish": "質感／表面處理" }},
      {{ "target": "牆面", "type": "材質名稱", "finish": "質感／表面處理" }}
    ],
    "lighting": {{
      "type": "主要光源描述，例如 'soft warm ceiling light'",
      "color_temp": 3000
    }}
  }},
  "ai_params": {{
    "prompts": {{
      "positive": "正向提示詞",
      "negative": "負向提示詞"
    }},
    "adapter_config": {{
      "ip_adapter_weight": 0.8,
      "controlnet": "depth"
    }}
  }},
  "quality_review": {{
    "is_closeup": false,
    "style_match_confidence": 0.9,
    "style_mismatch_reason": null,
    "suggested_styles": ["nordic", "japanese", "modern"]
  }},
  "lora_caption": "a living room, an L-shaped sofa facing a rectangular coffee table, a wall-mounted cabinet unit along one side, floor-to-ceiling windows on the far wall, wide-angle interior photograph"
}}
```

請務必：
- 嚴格輸出合法 JSON。
- 不要在 JSON 以外輸出任何說明、註解或 markdown。
"""

