# designbridge/schemas.py
"""Complete JSON schema definitions for DesignBridge agents per specification."""

from typing import Any, Literal
from typing_extensions import NotRequired, TypedDict


# ========== Requirement JSON ==========
class RequirementMeta(TypedDict):
    """Meta information about the design task."""

    room_type: str  # e.g. "living_room", "bedroom", "kitchen"
    design_goal: Literal["new_design", "renovation"]
    user_experience_level: NotRequired[str]  # "professional" | "general"


class SpaceInfo(TypedDict):
    """Spatial information from user or Vision."""

    estimated_size: NotRequired[dict[str, float]]  # {"width": ..., "height": ..., "depth": ...}
    windows: NotRequired[list[dict[str, Any]]]  # [{"position": ..., "size": ...}, ...]
    doors: NotRequired[list[dict[str, Any]]]


class StylePreferences(TypedDict):
    """Style-related preferences."""

    primary_style: str  # e.g. "北歐", "現代", "工業"
    secondary_style: NotRequired[str]  # For mixed styles
    color_palette: NotRequired[list[str]]  # ["#FFFFFF", "white", ...]
    material_preferences: NotRequired[list[str]]  # ["wood", "marble", ...]
    style_strength: float  # 0.0 (subtle) ~ 1.0 (strong)
    reference_images: NotRequired[list[str]]  # For IP-Adapter / CLIP


class LayoutConstraints(TypedDict):
    """Layout constraints from user."""

    must_keep: NotRequired[list[str]]  # Furniture to keep
    must_add: NotRequired[list[str]]  # Furniture to add
    must_remove: NotRequired[list[str]]  # Furniture to remove
    # Furniture to relocate. Each entry: {"target": type, "qualifier": which one
    # ("left" / "by the window" / ""), "to": where it should end up}.
    # Anything not named in add/remove/move keeps its original photo depth verbatim,
    # so this list is what decides which pixels are allowed to change.
    must_move: NotRequired[list[dict[str, str]]]
    immutable_regions: NotRequired[list[dict[str, Any]]]  # No-change regions
    functional_zones: NotRequired[list[dict[str, Any]]]  # Work/rest zones


class EditScope(TypedDict):
    """Edit scope parameters."""

    scope_value: float  # 0.0 ~ 1.0
    allowed_operations: NotRequired[list[str]]  # ["inpaint", "layout", "style"]


class PriorityWeights(TypedDict):
    """Priority weights for evaluation."""

    layout_rationality: float
    style_consistency: float
    novelty: float


class RequirementJSON(TypedDict):
    """Complete requirement specification (output of Requirement Analyzer)."""

    meta: RequirementMeta
    space_info: NotRequired[SpaceInfo]
    style_preferences: StylePreferences
    layout_constraints: NotRequired[LayoutConstraints]
    edit_scope: EditScope
    priority_weights: PriorityWeights
    # Routing hints (for Design Director)
    hint_layout: NotRequired[bool]
    hint_style: NotRequired[bool]
    hint_adjuster: NotRequired[bool]
    user_description_raw: str               # 使用者原始輸入，verbatim
    user_description_normalized: NotRequired[str]  # 語意清理後版本
    ambiguity_flags: NotRequired[list[str]] # 推斷或不確定的部分
    explicit_tasks: NotRequired[list[str]]  # 解析出的原子操作清單
    language: NotRequired[str]              # "zh-TW" / "en" 等
    source_image_id: NotRequired[str]       # 對應 Vision JSON 的 image ref
    has_vision_input: NotRequired[bool]     # 是否有圖片輸入
    success_conditions: NotRequired[list[str]]
    depth_conditioning_scale: NotRequired[float]  # 0.0 (ignore depth) ~ 1.0 (fully preserve structure)

# ========== Vision JSON ==========
class VisionJSON(TypedDict):
    """Output of Visual Preprocessor."""

    segmentation: NotRequired[str | Any]  # path or tensor
    segmentation_meta: NotRequired[str | dict[str, Any]]  # class labels, present objects
    depth: NotRequired[str | Any]  # path or tensor
    geometry_constraints: NotRequired[dict[str, Any]]  # Immutable regions, spatial relations
    scene_objects: NotRequired[list[dict[str, Any]]]  # Detected objects for cross-validation


# ========== Task/Plan JSON ==========
class TaskPlanJSON(TypedDict):
    """Output of Design Director: task assignment and plan."""

    assigned_agents: list[str]  # ["layout", "style"] or ["adjuster"]
    generation_mode: Literal["layout_and_style", "style_only", "layout_only", "inpaint"]
    constraints_summary: dict[str, Any]
    priority_order: NotRequired[list[str]]


# ========== Style Params JSON ==========
class StyleParamsJSON(TypedDict):
    """Output of Style Designer: style control parameters for Renderer."""

    style_prompt: str
    negative_prompt: NotRequired[str]
    style_strength: float
    style_profile_id: NotRequired[str]
    style_profile_name: NotRequired[str]
    style_summary: NotRequired[str]
    controlnet_type: NotRequired[str]
    material_recommendations: NotRequired[list[str]]
    lora_weights: NotRequired[dict[str, float]]  # {"lora_name": weight}
    ip_adapter_images: NotRequired[list[str]]
    color_guidance: NotRequired[dict[str, Any]]


# ========== Scene Graph JSON ==========
class SceneGraphJSON(TypedDict):
    """Output of Space Planner: layout solution for Renderer."""

    furniture_placements: list[dict[str, Any]]  # [{"id": ..., "type": ..., "position": ..., "rotation": ...}]
    spatial_relations: NotRequired[list[dict[str, Any]]]
    layout_prompt: str  # Text description for ControlNet guidance
    layout_constraints_met: dict[str, bool]


# ========== Adjust Plan JSON ==========
class AdjustPlanJSON(TypedDict):
    """Output of Design Adjuster: inpainting plan."""

    inpaint_regions: list[dict[str, Any]]  # [{"mask": ..., "prompt": ..., "strength": ...}]
    protected_regions: NotRequired[list[dict[str, Any]]]
    consistency_guidance: str


# ========== Render Result JSON ==========
class RenderResultJSON(TypedDict):
    """Output of Renderer: generated image + metadata."""

    generated_image_path: str
    generation_params: dict[str, Any]  # Model, seed, steps, etc.
    controlnet_inputs: NotRequired[dict[str, str]]  # {"depth": ..., "segmentation": ...}
    timestamp: str

# ========== Eval/Feedback JSON ==========
class EvalFeedbackJSON(TypedDict):
    """Output of Evaluator: scores and decision."""

    scores: dict[str, float]  # {"layout_rationality": ..., "style_consistency": ..., "novelty": ...}
    weighted_score: float
    decision: Literal["continue", "stop"]
    feedback: str
    issues_found: NotRequired[list[str]]
    suggestions: NotRequired[list[str]]


# ========== Quotation JSON ==========
class FurnitureCandidate(TypedDict):
    """A single IKEA candidate match for a detected furniture item."""

    id: str                     # IKEA 商品 ID
    name: str                   # IKEA 商品名稱
    price: int                  # 售價（TWD）
    purchase_url: str           # IKEA 商品頁連結
    product_image_url: str      # IKEA 商品圖片 URL
    similarity: float           # cosine similarity 0~1（向量比對得分）


class FurnitureItem(TypedDict):
    """A furniture item detected in the generated image, with top-3 IKEA candidates."""

    detected_name: str                      # Gemini 偵測到的名稱（中文）
    category: str                           # sofa / table / chair / lamp / rug / storage / bed / other
    candidates: list[FurnitureCandidate]    # top-3 IKEA 候選（向量搜尋結果）
    selected_index: int                     # 預設選中第 0 筆


class QuotationResultJSON(TypedDict):
    """Output of Quotation Agent: furniture list + budget breakdown."""

    furniture_list: list[FurnitureItem]
    total_low: int          # 以每件第 0 候選 × 0.8 計算
    total_mid: int          # 以每件第 0 候選計算
    total_high: int         # 以每件第 0 候選 × 1.3 計算
    currency: str           # "TWD"
    kb_match_count: int     # 有幾件成功從 IKEA KB 向量比對到
    notes: NotRequired[str]
