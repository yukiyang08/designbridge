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
    VisionJSON,
)

# Routing decision: which agent(s) Design Director assigns
RoutingDecision = Literal["design_adjuster", "design"]


class UserInput(TypedDict):
    """User input: image (optional), text prompt."""

    initial_image: NotRequired[str]  # image_path_or_id, optional for empty layout
    text_prompt: str
    output_aspect: NotRequired[Literal["auto", "1:1", "4:3", "3:4", "16:9", "9:16"]]
    style_profile_id: NotRequired[str]  # optional style profile id to apply directly
    style_reference_image: NotRequired[str]  # optional style reference image path
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
    routing_decision: NotRequired[RoutingDecision]
    # Agent outputs
    style_params: NotRequired[StyleParamsJSON]
    scene_graph: NotRequired[SceneGraphJSON]
    # Composer output: design_description + style_params.style_prompt + layout furniture
    # facts reconciled into one coherent render prompt (see designbridge/core/nodes/composer.py).
    # Absent when there was nothing to reconcile (no style, no furniture), or the composer
    # LLM call failed — renderer falls back to its own naive concatenation either way.
    composed_prompt: NotRequired[str]
    # True when composed_prompt already wove in the layout's furniture/placement facts —
    # tells renderer to skip its own separate furniture-prefix injection (it would otherwise
    # duplicate what composer already said, using a coarser, non-projection-corrected
    # description). See composer.py's `_layout_facts_text`.
    composed_includes_furniture: NotRequired[bool]
    # Renderer output
    render_result: NotRequired[RenderResultJSON]
    generated_image: NotRequired[str]
    # Depth layout extraction output
    layout_from_depth: NotRequired[dict[str, Any]]
    # Evaluator output
    evaluation_result: NotRequired[EvalFeedbackJSON]
    # Quotation Agent output
    quotation_result: NotRequired[QuotationResultJSON]
    # Legacy / intermediate outputs (can be refactored later)
    intermediate_outputs: NotRequired[dict[str, Any]]