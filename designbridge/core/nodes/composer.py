"""Composer graph node — reconciles design_description + style_kb prompt + layout
furniture facts into one coherent, conflict-free render prompt.

The pieces feeding the renderer's final prompt come from independent sources that
never see each other: RA's own room description (design_description), the
style_kb-matched reference image's positive_prompt, and the layout system's exact
furniture placements. Naively concatenating them (the old
`_build_imagen_prompt_from_requirement` behavior plus renderer's own string
prefixing, still used as the fallback when this node is skipped or fails) produces
contradictions when the matched style disagrees with what the user actually asked
for (e.g. user says "light luxury", the KB match is "industrial loft"), when the
style text names furniture that clashes with the layout's own furniture list (e.g.
"round coffee tables" vs. layout's single rectangular one), or just repeats the
same visual concept twice when sources happen to agree. This node asks Gemini to
merge them into one paragraph instead: the user's own description sets the
aesthetic direction, the layout's furniture facts are treated as ground truth to
preserve verbatim, and the style reference contributes only material/light/mood
words that don't collide with either.
"""

from __future__ import annotations

from typing import Any

from designbridge.core.prompts import COMPOSER_PROMPT
from designbridge.core.state import DesignBridgeState
from designbridge.render.render_prompt import _build_imagen_prompt_from_requirement, _describe_color


def _layout_facts_text(state: DesignBridgeState, req: dict[str, Any]) -> str:
    """Assemble whatever layout/furniture facts are already known at this point in the
    graph (composer runs before renderer, so the depth-projection-corrected furniture
    description — only computable once renderer picks a ControlNet condition image —
    isn't available here; renderer still injects that narrower, more precise variant
    separately when it applies, see renderer.py's `using_projected_depth` branch)."""
    scene_graph = state.get("scene_graph") or {}
    parts: list[str] = []

    furniture_placements = scene_graph.get("furniture_placements") or []
    if furniture_placements:
        from designbridge.core.nodes.renderer import _furniture_to_spatial_text
        parts.append(_furniture_to_spatial_text(furniture_placements))

    layout_prompt = (scene_graph.get("layout_prompt") or "").strip()
    if not layout_prompt and req.get("hint_layout"):
        layout_from_depth = state.get("layout_from_depth") or {}
        if layout_from_depth:
            from designbridge.render.render_prompt import _layout_json_to_prompt_text
            layout_prompt = _layout_json_to_prompt_text(layout_from_depth)
    if layout_prompt:
        parts.append(layout_prompt)

    return " ".join(parts)


def composer_node(state: DesignBridgeState) -> dict[str, Any]:
    """Merge design_description + style_params + layout furniture facts into one
    `composed_prompt`.

    No-op (returns {}) when there's neither a style_prompt nor any furniture/layout
    facts to weave in — the renderer's own base-prompt builder is already
    single-source and coherent then, and there is nothing for this node to add. Also
    degrades to {} (renderer falls back to the naive concatenation) on any LLM
    failure, same graceful-degradation pattern as every other Gemini call in this
    pipeline.
    """
    req = state.get("structured_requirement") or {}
    style_params = state.get("style_params") or {}
    style_prompt = (style_params.get("style_prompt") or "").strip()
    furniture_facts = _layout_facts_text(state, req)
    if not style_prompt and not furniture_facts:
        return {}

    user_text_prompt = ((state.get("user_input") or {}).get("text_prompt") or "").strip()
    # style_params=None here on purpose: reuse the existing base-prompt logic
    # (design_description, or the room+style fallback when it's empty) without
    # its own naive style concatenation — that's exactly the part this node replaces.
    base_prompt = _build_imagen_prompt_from_requirement(
        req, style_params=None, user_text_prompt=user_text_prompt,
    )

    style_name = (style_params.get("style_profile_id") or "unspecified").strip()
    strength = style_params.get("style_strength", 0.7)

    color_guidance = style_params.get("color_guidance") or {}
    palette_bits = [
        f"{label} {_describe_color(color_guidance[key])}"
        for label, key in (("primary", "primary_color"), ("secondary", "secondary_color"), ("accent", "accent_color"))
        if color_guidance.get(key)
    ]
    palette = ", ".join(palette_bits) if palette_bits else "無特定色碼"

    prompt_text = COMPOSER_PROMPT.format(
        base_prompt=base_prompt,
        style_name=style_name,
        strength=strength,
        palette=palette,
        style_reference_text=style_prompt or "無",
        furniture_facts=furniture_facts or "無指定家具佈局",
    )

    try:
        from designbridge.render.llm import call_llm
        composed = call_llm(prompt_text, temperature=0.3, max_tokens=280).strip()
        if not composed:
            raise ValueError("empty composer output")
        print(f"[composer] merged prompt: {composed[:120]}")
        return {
            "composed_prompt": composed,
            "composed_includes_furniture": bool(furniture_facts),
        }
    except Exception as e:
        print(f"⚠️ [composer] failed ({e}), renderer will fall back to naive concatenation")
        return {}
