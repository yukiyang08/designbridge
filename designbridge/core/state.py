# designbridge/state.py
"""DesignBridge LangGraph state schema per DesignBridge.md."""

from typing import Any, Literal
from typing_extensions import NotRequired, TypedDict

from designbridge.core.schemas import (
    EvalFeedbackJSON,
    QuotationResultJSON,
    RequirementJSON,
    RenderResultJSON,
    SceneGraphJSON,
    StyleParamsJSON,
    TaskPlanJSON,
    VisionJSON,
)

# Routing decision: which agent(s) Design Director assigns
RoutingDecision = Literal["design_adjuster", "design"]


class UserInput(TypedDict):
    """User input: image (optional), text prompt, edit scope (0~1)."""

    initial_image: NotRequired[str]  # image_path_or_id, optional for empty layout
    text_prompt: str
    edit_scope: float  # 0~1
    output_aspect: NotRequired[Literal["auto", "1:1", "4:3", "3:4", "16:9", "9:16"]]
    style_profile_id: NotRequired[str]  # optional style profile id to apply directly
    style_reference_image: NotRequired[str]  # optional style reference image path
    family_needs: NotRequired[list[str]]   # e.g. ["children", "wheelchair", "pets"]
    fengshui_rules: NotRequired[list[str]] # e.g. ["bed_not_facing_door", ...]


class DesignBridgeState(TypedDict):
    """Global state shared across all DesignBridge agents."""

    task_id: NotRequired[str]
    iteration: NotRequired[int]
    # User input
    user_input: NotRequired[UserInput]
    # Requirement Analyzer output (RequirementJSON)
    structured_requirement: NotRequired[RequirementJSON]
    # Vision Preprocessor output (VisionJSON)
    vision_features: NotRequired[VisionJSON]
    # Design Director output (TaskPlanJSON)
    task_plan: NotRequired[TaskPlanJSON]
    routing_decision: NotRequired[RoutingDecision]
    # Agent outputs
    style_params: NotRequired[StyleParamsJSON]
    scene_graph: NotRequired[SceneGraphJSON]
    # Renderer output
    render_result: NotRequired[RenderResultJSON]
    generated_image: NotRequired[str]
    # Depth layout extraction output
    layout_from_depth: NotRequired[dict[str, Any]]
    # Evaluator output
    evaluation_result: NotRequired[EvalFeedbackJSON]
    # Quotation Agent output
    quotation_result: NotRequired[QuotationResultJSON]
    # 3D 場景重建輸出
    depth_cloud_path: NotRequired[str]      # point_cloud.ply（舊版點雲）
    room_glb_path: NotRequired[str]         # room_mesh.glb（帶 UV 貼圖）
    room_panorama_path: NotRequired[str]    # panorama.png（Text2Room 環景圖）
    # Legacy / intermediate outputs (can be refactored later)
    intermediate_outputs: NotRequired[dict[str, Any]]