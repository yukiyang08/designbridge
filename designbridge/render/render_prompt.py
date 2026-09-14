# designbridge/render_prompt.py
"""Prompt assembly utilities and output-size helpers for the Renderer node."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from designbridge.style.style_apply import STYLE_NAME_TO_ID

# ── Prompt builders ────────────────────────────────────────────────────────────

def _analyze_style_image_with_gemini(image_path: str) -> str:
    """Use Gemini vision to extract a concise style description from a reference image."""
    try:
        from designbridge.render.llm import call_llm

        analysis_prompt = (
            "Analyze this interior design style reference image. "
            "Describe concisely in English: color palette, materials and textures, "
            "furniture style, lighting mood, and overall atmosphere. "
            "Output only the description (no headers, no bullet points), "
            "suitable for appending to an image generation prompt. Under 60 words."
        )
        desc = call_llm(analysis_prompt, images=[image_path])
        return desc.strip()
    except Exception as e:
        print(f"⚠️  Gemini style image analysis failed: {e}")
        return ""


def _build_imagen_prompt_from_requirement(
    req: dict[str, Any],
    style_params: dict[str, Any] | None = None,
    user_text_prompt: str | None = None,
) -> str:
    """Build an English text prompt for image generation from structured_requirement and style params.

    ``user_text_prompt`` is the raw prompt the user typed. When it is empty, the LLM
    requirement analyzer tends to fill ``design_description`` with a meta-narrative of
    the *edit operation* ("a complete interior redesign allowing comprehensive
    changes…") rather than an actual room description — which starves the renderer of
    positive room content and lets the ControlNet structure dominate. In that case we
    ignore ``design_description`` and fall back to a concrete room/style prompt.
    """
    _STYLE_ID_TO_EN = {
        "modern": "modern contemporary",
        "country": "country rustic farmhouse",
        "classic": "classical traditional",
        "nordic": "Nordic Scandinavian minimalist",
        "industrial": "industrial loft",
        "japanese": "Japanese minimalist Japandi",
        "american": "American style",
        "luxury": "luxury high-end glamour",
    }
    design_description = (req.get("design_description") or "").strip()
    # Only trust design_description when the user actually described something. With an
    # empty user prompt it is an LLM meta-narrative, not a room — fall through to the
    # room_type + style fallback below instead.
    _user_described = user_text_prompt is None or bool(user_text_prompt.strip())
    if design_description and _user_described:
        base_prompt = design_description
    else:
        meta = req.get("meta") or {}
        style_prefs = req.get("style_preferences") or {}
        room_type = meta.get("room_type", "living_room").replace("_", " ")
        if style_params and style_params.get("style_profile_id"):
            style_id = style_params["style_profile_id"].lower()
        else:
            raw_style = style_prefs.get("primary_style") or ""
            style_id = STYLE_NAME_TO_ID.get(raw_style) or raw_style.lower()
        primary_style = _STYLE_ID_TO_EN.get(style_id, style_id) or "interior"
        color_palette = style_prefs.get("color_palette") or []
        colors = ", ".join(str(c) for c in color_palette[:3]) if color_palette else "neutral tones"
        base_prompt = (
            f"Interior design visualization: a {room_type}, {primary_style} style, "
            f"colors {colors}. Photorealistic, well-lit, high quality."
        )

    if not style_params:
        return base_prompt

    color_guidance = style_params.get("color_guidance") or {}
    style_prompt = style_params.get("style_prompt") or ""
    strength = style_params.get("style_strength", 0.7)

    # style_summary / visual_essence / material_recommendations come from the KB's
    # human-readable (often Chinese) fields — meant for UI display, not the
    # English image-gen prompt, so they're intentionally excluded here.
    extra_parts: list[str] = []
    style_id_for_prompt = (style_params.get("style_profile_id") or "").lower()
    style_name_en = _STYLE_ID_TO_EN.get(style_id_for_prompt, "")
    if style_name_en:
        extra_parts.append(f"Style profile: {style_name_en} (strength {strength}).")
    if color_guidance.get("primary_color"):
        extra_parts.append(
            f"Palette: primary {color_guidance.get('primary_color')}, "
            f"secondary {color_guidance.get('secondary_color')}, "
            f"accent {color_guidance.get('accent_color')}."
        )
    if style_prompt:
        extra_parts.append(style_prompt)

    return (base_prompt + " " + " ".join(extra_parts)).strip()


def _layout_json_to_prompt_text(layout_json: dict[str, Any]) -> str:
    """Convert depth_to_layout JSON into a concise English layout directive for the prompt."""
    analysis = layout_json.get("space_analysis") or {}
    space_type = analysis.get("space_type", "standard_room").replace("_", " ")
    perspective = analysis.get("camera_perspective", "eye_level").replace("_", " ")
    circulation = analysis.get("circulation_score", 0.5)

    parts: list[str] = [
        f"Spatial layout reference: {space_type} with {perspective} camera angle.",
    ]

    if circulation > 0.7:
        parts.append("Keep clear open floor space in the foreground for circulation.")
    elif circulation < 0.3:
        parts.append("Foreground area may include furniture pieces.")

    candidates = layout_json.get("furniture_candidates") or []
    if candidates:
        furniture_hints = [
            f"{c['type'].replace('_', ' ')} at {c['position']}"
            for c in candidates[:4]
            if c.get("confidence") == "high" or c.get("size_ratio", 0) > 0.04
        ]
        if furniture_hints:
            parts.append("Maintain similar furniture arrangement: " + ", ".join(furniture_hints) + ".")

    rec = layout_json.get("layout_recommendation") or {}
    anchor = rec.get("anchor_furniture") or []
    if anchor:
        keeps = [f"{a['furniture'].replace('_', ' ')} at {a['position']}" for a in anchor[:2]]
        if keeps:
            parts.append("Anchor pieces to preserve: " + ", ".join(keeps) + ".")

    metrics = (analysis.get("spatial_metrics") or {})
    if metrics.get("left_right_symmetry", 1.0) > 0.9:
        parts.append("Preserve left-right spatial symmetry.")

    return " ".join(parts)


# ── Output size helpers ────────────────────────────────────────────────────────

OutputAspect = Literal["auto", "1:1", "4:3", "3:4", "16:9", "9:16"]
_ASPECT_RATIO_MAP: dict[OutputAspect, float] = {
    "auto": 1.0,
    "1:1": 1.0,
    "4:3": 4.0 / 3.0,
    "3:4": 3.0 / 4.0,
    "16:9": 16.0 / 9.0,
    "9:16": 9.0 / 16.0,
}


def _round_to_multiple(value: int, multiple: int, min_value: int, max_value: int) -> int:
    return max(min_value, min(max_value, int(round(value / multiple) * multiple)))


def _resolve_output_size(
    output_aspect: str,
    initial_image_path: str | None,
    long_edge: int = 1024,
    min_edge: int = 512,
    max_edge: int = 1344,
) -> tuple[int, int]:
    aspect_key: OutputAspect = output_aspect if output_aspect in _ASPECT_RATIO_MAP else "auto"
    ratio = _ASPECT_RATIO_MAP[aspect_key]

    if aspect_key == "auto" and initial_image_path and Path(initial_image_path).is_file():
        try:
            from PIL import Image
            with Image.open(initial_image_path) as img:
                w, h = img.size
            if w > 0 and h > 0:
                ratio = w / h
        except Exception:
            ratio = 1.0

    if ratio >= 1.0:
        width = long_edge
        height = int(round(long_edge / ratio))
    else:
        height = long_edge
        width = int(round(long_edge * ratio))

    width = _round_to_multiple(width, multiple=64, min_value=min_edge, max_value=max_edge)
    height = _round_to_multiple(height, multiple=64, min_value=min_edge, max_value=max_edge)
    return width, height


def _renderer_placeholder_image(
    out_path: Path,
    task_id: str,
    prompt: str,
    output_size: tuple[int, int],
) -> None:
    """Save a placeholder image (PIL) when all generation backends are unavailable."""
    from PIL import Image, ImageDraw

    width, height = output_size
    img = Image.new("RGB", (width, height), color=(240, 240, 245))
    draw = ImageDraw.Draw(img)
    margin_x = max(30, int(width * 0.1))
    margin_y = max(30, int(height * 0.1))
    draw.rectangle(
        [margin_x, margin_y, width - margin_x, height - margin_y],
        fill=(255, 255, 255),
        outline=(180, 180, 190),
    )
    text = "DesignBridge\n(placeholder)"
    try:
        draw.text((width // 2, height // 2), text, fill=(100, 100, 110), anchor="mm")
    except Exception:
        draw.text((margin_x + 10, height // 2), "DesignBridge placeholder", fill=(100, 100, 110))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
