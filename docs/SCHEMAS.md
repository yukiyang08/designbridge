# DesignBridge Agent Input/Output Specification

根據 DesignBridge 多代理系統規格，各 Agent 的輸入、輸出與依賴關係整理如下。

---

## Agent Input/Output Dependencies

| Agent | 輸入 | 輸出 | 生成依賴 |
|-------|------|------|----------|
| **Requirement Analyzer (RA)** | 使用者 Raw Input（text_prompt, edit_scope, initial_image）；（可選）Vision JSON | **Requirement JSON** | 使用者 Raw Input；若要防錯可依賴 Vision JSON 交叉驗證門窗/家具 |
| **Vision Preprocessor (VP)** | 原始影像（非 JSON） | **Vision JSON** | 原始影像（非 JSON） |
| **Space Planner (SP)** | Requirement JSON + Vision JSON | **Layout Problem JSON**（中間產物）+ **Scene Graph JSON**（佈局解） | Vision JSON（空間/不可動/可用區）+ Requirement JSON（must_keep/must_add/edit_scope） |
| **Style Designer (SD)** | Requirement JSON + Vision JSON | **Style Params JSON**（風格控制參數） | Requirement JSON（style_preferences + priority_weights + edit_scope）+ Vision JSON（結構保留/不可改區） |
| **Design Adjuster (DA)** | Requirement JSON + Vision JSON + Render Result JSON | **Adjust Plan JSON**（inpaint 計畫/遮罩/強度） | Vision JSON（mask/區域/不可改區）+ Requirement（scope 限制） |
| **Renderer (R)** | Style Params JSON +（Scene Graph JSON 或 Adjust Plan JSON）+（可選）Vision JSON | **Render Result JSON**（結果索引 + 參數紀錄） | Style Params（生成條件）+ Scene Graph/Adjust Plan（結構或局部控制） |
| **Evaluator (E)** | Requirement JSON + Render Result JSON +（可選）Scene Graph JSON + Vision JSON | **Eval/Feedback JSON** | Requirement JSON（評估標準）+ Render Result（被評結果）+ priority_weights（加權） |

---

## 1. Requirement JSON（需求規格）

**產出者**：Requirement Analyzer  
**消費者**：Space Planner, Style Designer, Design Adjuster, Evaluator

### 欄位表

| 欄位 | 子欄位 | 型別 | 必填 | 來源 | 說明 / 用途 |
|------|--------|------|------|------|-------------|
| `meta` | `room_type` | string | ✓ | 使用者/澄清 | 空間用途（living_room, bedroom…），影響佈局與風格預設 |
| | `design_goal` | string | ✓ | 使用者 | new_design / renovation，用於決定是否保留既有配置 |
| | `user_experience_level` | string | ✕ | 預設 | 區分 professional/general 使用者，影響澄清策略 |
| `space_info` | `estimated_size` | object | ✕ | 使用者/Vision | 空間長寬高，用於比例與可行性判斷 |
| | `windows` | array | ✕ | 使用者/Vision | 門窗位置與大小，影響動線與不可改動區 |
| | `doors` | array | ✕ | 使用者/Vision | 出入口位置，動線約束依據 |
| `style_preferences` | `primary_style` | string | ✓ | 使用者/澄清 | 主要風格，Style Agent 的核心條件 |
| | `secondary_style` | string | ✕ | 使用者 | 混搭風格用，若無則為 null |
| | `color_palette` | array | ✕ | 使用者 | 限制生成配色 |
| | `material_preferences` | array | ✕ | 使用者 | 材質偏好，避免不喜歡材質 |
| | `style_strength` | float (0–1) | ✓ | 使用者/預設 | 控制風格影響強度（prompt/LoRA 權重） |
| | `reference_images` | array | ✕ | 使用者 | IP-Adapter / CLIP 參考 |
| `layout_constraints` | `must_keep` | array | ✕ | 使用者/澄清 | 必須保留的家具 |
| | `must_add` | array | ✕ | 使用者 | 必須新增的功能或家具 |
| | `must_remove` | array | ✕ | 使用者 | 一定要移除的物件 |
| | `immutable_regions` | array | ✕ | Vision/使用者 | 不可改動區域（門窗、樑柱） |
| | `functional_zones` | array | ✕ | 使用者 | 功能分區（工作/休息） |
| `edit_scope` | `scope_value` | float (0–1) | ✓ | 使用者 | 改動強度，路由依據 |
| | `allowed_operations` | array | ✕ | 系統推導 | 可允許操作（inpaint / layout / style） |
| `priority_weights` | `layout_rationality` | float | ✓ | 使用者/預設 | 偏好空間合理性 |
| | `style_consistency` | float | ✓ | 使用者/預設 | 偏好風格一致性 |
| | `novelty` | float | ✓ | 使用者/預設 | 偏好創新程度 |
| _(top-level)_ | `hint_layout` | bool | ✕ | 系統推導 | 供路由用 |
| _(top-level)_ | `hint_style` | bool | ✕ | 系統推導 | 供路由用 |
| _(top-level)_ | `hint_adjuster` | bool | ✕ | 系統推導 | 供路由用 |

### 範例

```json
{
  "meta": {
    "room_type": "living_room",
    "design_goal": "renovation",
    "user_experience_level": "general"
  },
  "space_info": {
    "estimated_size": {"width": 5.0, "height": 3.0, "depth": 4.0},
    "windows": [{"position": "north_wall", "size": {"width": 1.5, "height": 2.0}}],
    "doors": [{"position": "south_wall"}]
  },
  "style_preferences": {
    "primary_style": "北歐",
    "secondary_style": null,
    "color_palette": ["white", "#F5F5DC", "灰色"],
    "material_preferences": ["wood", "布料"],
    "style_strength": 0.7,
    "reference_images": []
  },
  "layout_constraints": {
    "must_keep": ["沙發"],
    "must_add": ["書桌", "收納櫃"],
    "must_remove": [],
    "immutable_regions": [{"type": "window", "id": "window_1"}],
    "functional_zones": [{"zone": "work_area", "priority": "high"}]
  },
  "edit_scope": {
    "scope_value": 0.6,
    "allowed_operations": ["layout", "style"]
  },
  "priority_weights": {
    "layout_rationality": 0.5,
    "style_consistency": 0.3,
    "novelty": 0.2
  },
  "hint_layout": true,
  "hint_style": true,
  "hint_adjuster": false
}
```

---

## 2. Vision JSON

**產出者**：Vision Preprocessor  
**消費者**：Space Planner, Style Designer, Design Adjuster, Renderer, Evaluator

### 欄位

- `segmentation`: 語義分割 label map（路徑或 tensor）
- `segmentation_meta`: 類別標籤、出現物件清單
- `depth`: 深度圖（路徑或 tensor）
- `geometry_constraints`: 不可改區域、空間關係
- `scene_objects`: 偵測到的物件（供 Requirement Analyzer 交叉驗證）

### 範例

```json
{
  "segmentation": "artifacts/vision/task123/segmentation.png",
  "segmentation_meta": "artifacts/vision/task123/segmentation_meta.json",
  "depth": "artifacts/vision/task123/depth.png",
  "geometry_constraints": {
    "immutable_regions": [{"type": "window", "bbox": [100, 200, 150, 300]}]
  },
  "scene_objects": [
    {"type": "sofa", "bbox": [...]},
    {"type": "table", "bbox": [...]}
  ]
}
```

---

## 3. Style Params JSON

**產出者**：Style Designer  
**消費者**：Renderer

### 欄位

- `style_prompt`: 風格提示詞（含色彩、材質、氛圍）
- `negative_prompt`: 負向提示（可選）
- `style_strength`: 風格強度（0~1）
- `lora_weights`: LoRA 權重（{"lora_name": weight}）
- `ip_adapter_images`: IP-Adapter 參考圖片
- `color_guidance`: 色彩引導參數

### 範例

```json
{
  "style_prompt": "Scandinavian interior, bright, minimalist, natural wood, white walls",
  "negative_prompt": "cluttered, dark, baroque",
  "style_strength": 0.7,
  "lora_weights": {"scandinavian_v2": 0.8},
  "ip_adapter_images": [],
  "color_guidance": {"dominant": "white", "accent": "#F5F5DC"}
}
```

---

## 4. Scene Graph JSON

**產出者**：Space Planner  
**消費者**：Renderer

### 欄位

- `furniture_placements`: 家具擺放清單（id, type, position, rotation）
- `spatial_relations`: 空間關係（可選）
- `layout_prompt`: 佈局文字描述（供 ControlNet 引導）
- `layout_constraints_met`: 約束滿足狀態

### 範例

```json
{
  "furniture_placements": [
    {"id": "sofa_1", "type": "sofa", "position": {"x": 2.0, "y": 0.5}, "rotation": 90},
    {"id": "table_1", "type": "coffee_table", "position": {"x": 2.0, "y": 1.5}}
  ],
  "spatial_relations": [
    {"type": "in_front_of", "obj1": "table_1", "obj2": "sofa_1"}
  ],
  "layout_prompt": "L-shaped sofa facing coffee table, TV on the wall opposite",
  "layout_constraints_met": {"must_keep_sofa": true, "no_blocking_windows": true}
}
```

---

## 5. Adjust Plan JSON

**產出者**：Design Adjuster  
**消費者**：Renderer

### 欄位

- `inpaint_regions`: 要 inpaint 的區域清單（mask, prompt, strength）
- `protected_regions`: 保護區域（不可改動）
- `consistency_guidance`: 一致性引導文字

### 範例

```json
{
  "inpaint_regions": [
    {
      "mask": "artifacts/masks/sofa_region.png",
      "prompt": "modern gray fabric sofa",
      "strength": 0.8
    }
  ],
  "protected_regions": [
    {"mask": "artifacts/masks/window_wall.png"}
  ],
  "consistency_guidance": "Keep overall lighting and perspective consistent with original"
}
```

---

## 6. Render Result JSON

**產出者**：Renderer  
**消費者**：Evaluator

### 欄位

- `generated_image_path`: 生成圖路徑
- `generation_params`: 生成參數（model, seed, steps, guidance_scale 等）
- `controlnet_inputs`: 使用的 ControlNet 輸入（depth, segmentation 等）
- `timestamp`: 生成時間戳

### 範例

```json
{
  "generated_image_path": "artifacts/render/task123_iter0.png",
  "generation_params": {
    "model": "stabilityai/stable-diffusion-xl-base-1.0",
    "seed": 42,
    "steps": 30,
    "guidance_scale": 7.5,
    "controlnet": ["depth", "segmentation"]
  },
  "controlnet_inputs": {
    "depth": "artifacts/vision/task123/depth.png",
    "segmentation": "artifacts/vision/task123/segmentation.png"
  },
  "timestamp": "2026-01-28T19:30:00Z"
}
```

---

## 7. Eval/Feedback JSON

**產出者**：Evaluator  
**消費者**：歷史頁顯示

### 欄位

- `scores`: 各維度分數（layout_rationality, style_consistency, novelty 等）
- `weighted_score`: 加權總分
- `decision`: "continue"（繼續迭代）或 "stop"（結束）
- `feedback`: 文字回饋
- `issues_found`: 發現的問題清單（可選）
- `suggestions`: 改進建議（可選）

### 範例

```json
{
  "scores": {
    "layout_rationality": 0.8,
    "style_consistency": 0.7,
    "novelty": 0.6
  },
  "weighted_score": 0.73,
  "decision": "continue",
  "feedback": "佈局合理但風格一致性可改善，建議調整色彩搭配",
  "issues_found": ["Color palette too diverse", "Sofa blocking window light"],
  "suggestions": ["Unify color scheme", "Move sofa 0.5m to the left"]
}
```

---

## 使用方式

所有 JSON schema 的 TypedDict 定義在 `designbridge/schemas.py`。

### 在程式中使用

```python
from designbridge.schemas import RequirementJSON, VisionJSON, TaskPlanJSON

# Type checking
def my_agent(requirement: RequirementJSON, vision: VisionJSON) -> TaskPlanJSON:
    ...
```

### 在 LangGraph State 中使用

```python
from designbridge.state import DesignBridgeState

state: DesignBridgeState = {
    "structured_requirement": requirement_json,  # RequirementJSON
    "vision_features": vision_json,              # VisionJSON
    "task_plan": task_plan_json,                 # TaskPlanJSON
    ...
}
```

---

## 後續擴充

未來可加入：
- **Layout Problem JSON**（Space Planner 的約束優化中間產物）
- **VLM Semantic Report JSON**（GPT-4V / Gemini Vision 的場景分析）
- **Multi-modal Clarification JSON**（澄清機制的對話紀錄）
