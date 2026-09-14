"""Requirement Analyzer graph node."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from designbridge.core.prompts import REQUIREMENT_ANALYZER_PROMPT
from designbridge.core.state import DesignBridgeState


# Openings are modelled as a thin band on the wall they belong to, in the top-down
# normalized frame the layout agent uses (x: 0=left→1=right, y: 0=far wall→1=viewer).
_WALL_BAND = 0.06

_WALL_ALIASES: dict[str, str] = {
    "far": "far", "back": "far", "north": "far", "top": "far", "rear": "far",
    "near": "near", "front": "near", "south": "near", "bottom": "near",
    "left": "left", "west": "left",
    "right": "right", "east": "right",
}


def _opening_to_box(opening: Any) -> dict[str, Any] | None:
    """`{wall, start, end}` → top-down `{x, y, w, h, wall}`.

    The requirement analyzer is asked for wall + span because an LLM gets that right far
    more often than four raw coordinates, but every downstream enforcer
    (`_enforce_bed_not_near_window`, the special-constraint verifiers) reads x/y/w/h — so
    the conversion happens here, once. Entries that already carry x/y/w/h are passed
    through with only the `wall` label inferred, keeping older payloads working.
    """
    if not isinstance(opening, dict):
        return None

    wall = _WALL_ALIASES.get(str(opening.get("wall", "")).strip().lower(), "")

    if "x" in opening or "y" in opening:
        try:
            box = {
                "x": float(opening.get("x", 0.0)),
                "y": float(opening.get("y", 0.0)),
                "w": float(opening.get("w", 0.15)),
                "h": float(opening.get("h", 0.15)),
            }
        except (TypeError, ValueError):
            return None
        if not wall:
            # Infer from which edge the box hugs; ties go to the horizontal walls.
            edges = {"far": box["y"], "near": 1.0 - box["y"] - box["h"],
                     "left": box["x"], "right": 1.0 - box["x"] - box["w"]}
            wall = min(edges, key=lambda k: edges[k])
        box["wall"] = wall
        return box

    try:
        start = float(opening.get("start", 0.0))
        end = float(opening.get("end", 0.0))
    except (TypeError, ValueError):
        return None
    start, end = max(0.0, min(1.0, min(start, end))), max(0.0, min(1.0, max(start, end)))
    if end - start < 0.01 or not wall:
        return None

    span = end - start
    if wall == "far":
        return {"x": start, "y": 0.0, "w": span, "h": _WALL_BAND, "wall": wall}
    if wall == "near":
        return {"x": start, "y": 1.0 - _WALL_BAND, "w": span, "h": _WALL_BAND, "wall": wall}
    if wall == "left":
        return {"x": 0.0, "y": start, "w": _WALL_BAND, "h": span, "wall": wall}
    return {"x": 1.0 - _WALL_BAND, "y": start, "w": _WALL_BAND, "h": span, "wall": wall}


def _normalize_space_info(req: dict[str, Any]) -> None:
    """Guarantee `structured_requirement["space_info"]` exists and is in top-down boxes.

    Without this the key is simply absent on the LLM path (the analyzer prompt only
    started emitting it alongside this change), so the layout agent was planning every
    room as a 5.0×4.0 box with no windows and no doors — which makes any "move it to the
    window" instruction unresolvable.
    """
    def _positive(value: Any, default: float) -> float:
        try:
            f = float(value)
        except (TypeError, ValueError):
            return default
        return f if f > 0 else default

    space_info = req.get("space_info")
    if not isinstance(space_info, dict):
        space_info = {}

    size = space_info.get("estimated_size")
    size = size if isinstance(size, dict) else {}
    space_info["estimated_size"] = {
        "width": _positive(size.get("width"), 5.0),
        "height": _positive(size.get("height"), 2.8),
        "depth": _positive(size.get("depth"), 4.0),
    }

    for key in ("windows", "doors"):
        raw = space_info.get(key)
        boxes = [b for b in (_opening_to_box(o) for o in raw) if b] if isinstance(raw, list) else []
        space_info[key] = boxes

    req["space_info"] = space_info


def requirement_analyzer(state: DesignBridgeState) -> dict[str, Any]:
    """
    Parse user_input into structured_requirement (JSON) using Gemini API.
    Falls back to rule-based if API key not set or API fails.
    """
    user = state.get("user_input") or {}
    text_prompt = (user.get("text_prompt") or "").strip()
    edit_scope = float(user.get("edit_scope", 0.5))
    initial_image = user.get("initial_image", "無")
    style_reference_image = user.get("style_reference_image", "")

    task_id = state.get("task_id") or str(uuid.uuid4())
    iteration = state.get("iteration", 0)

    # Try LLM (Gemini) first, fall back to passing prompt directly on failure
    try:
        structured_requirement = _call_llm_requirement_analyzer(
            text_prompt, edit_scope, initial_image,
            style_reference_image=style_reference_image,
        )
    except Exception as e:
        print(f"⚠️  LLM call failed ({e}), passing prompt directly to renderer")
        structured_requirement = {
            "user_description_raw": text_prompt,
            "design_description": text_prompt,
            "meta": {"room_type": "living_room", "design_goal": "renovation", "user_experience_level": "general"},
            "space_info": {"estimated_size": {"width": 5.0, "height": 3.0, "depth": 4.0}, "windows": [], "doors": []},
            "style_preferences": {"primary_style": "", "secondary_style": None, "color_palette": [], "material_preferences": [], "style_strength": 0.7, "reference_images": []},
            "layout_constraints": {"must_keep": [], "must_add": [], "must_remove": [], "immutable_regions": [], "functional_zones": []},
            "edit_scope": {"scope_value": edit_scope, "allowed_operations": ["layout", "style"]},
            "priority_weights": {"layout_rationality": 0.4, "style_consistency": 0.4, "user_preference": 0.2},
        }

    # Merge family needs and feng shui rules into structured_requirement
    # Must run before the layout agent reads windows/doors, and before the special
    # constraints (wheelchair clearance, child safety) look for door positions.
    _normalize_space_info(structured_requirement)
    _si = structured_requirement["space_info"]
    print(
        f"[requirement_analyzer] space_info: "
        f"{_si['estimated_size']['width']}×{_si['estimated_size']['depth']}m, "
        f"windows={len(_si['windows'])}, doors={len(_si['doors'])}"
    )

    family_needs   = user.get("family_needs")   or []
    fengshui_rules = user.get("fengshui_rules") or []
    if family_needs or fengshui_rules:
        from designbridge.layout.special_constraints import enrich_requirement
        structured_requirement = enrich_requirement(structured_requirement, family_needs, fengshui_rules)

    # If the user explicitly selected a style from the dropdown, override whatever
    # Gemini / rule-based inferred from the text so the whole pipeline stays consistent.
    explicit_style_id = (user.get("style_profile_id") or "").strip()
    if explicit_style_id and explicit_style_id != "auto":
        style_prefs = structured_requirement.setdefault("style_preferences", {})
        style_prefs["primary_style"] = explicit_style_id

    # Extract routing decision embedded by _call_llm_requirement_analyzer, then remove it
    # from the requirement so it doesn't pollute structured data.
    routing_decision = structured_requirement.pop("_routing_decision", None)

    result: dict[str, Any] = {
        "task_id": task_id,
        "iteration": iteration,
        "structured_requirement": structured_requirement,
    }
    if routing_decision:
        result["routing_decision"] = routing_decision
        print(f"[requirement_analyzer] routing_decision from LLM: {routing_decision}")

    return result


def _is_valid_image_path(image_path: str) -> bool:
    """Return True if image_path is a non-empty, valid file path (not placeholder)."""
    if not image_path or not isinstance(image_path, str):
        return False
    s = image_path.strip()
    if s in ("", "無"):
        return False
    return Path(s).is_file()


_VALID_ROUTING_DECISIONS = {"design_adjuster", "design"}


def _call_llm_requirement_analyzer(
    text_prompt: str, edit_scope: float, initial_image: str,
    style_reference_image: str = "",
) -> dict[str, Any]:
    """Call LLM to analyze requirements and return {structured_requirement, routing_decision}.
    The new prompt asks for a single JSON with both fields. Falls back to legacy NL parsing.
    """
    import json as _json
    from designbridge.render.llm import call_llm

    prompt = REQUIREMENT_ANALYZER_PROMPT.format(
        text_prompt=text_prompt,
        edit_scope=edit_scope,
        initial_image=initial_image,
    )

    images: list[str] = []
    if _is_valid_image_path(initial_image):
        images.append(initial_image)
    if style_reference_image and _is_valid_image_path(style_reference_image):
        images.append(style_reference_image)

    text = call_llm(prompt, images=images or None)
    text = text.strip()

    # Strip markdown code fences
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # Tolerate leading/trailing noise around the JSON object
    if not text.startswith("{"):
        start = text.find("{")
        if start != -1:
            text = text[start:]
    if not text.endswith("}"):
        end = text.rfind("}")
        if end != -1:
            text = text[: end + 1]

    try:
        parsed = _json.loads(text)
    except Exception as exc:
        raise ValueError(f"Requirement analyzer LLM returned unparseable JSON: {text[:200]!r}") from exc

    # New format: {"routing_decision": "...", "structured_requirement": {...}}
    if "structured_requirement" in parsed and "routing_decision" in parsed:
        req = parsed["structured_requirement"]
        routing = parsed["routing_decision"]
        if routing not in _VALID_ROUTING_DECISIONS:
            routing = "design"
        req["_routing_decision"] = routing
        return _normalize_requirement(req)

    # Fallback: LLM returned the old flat structure directly
    return _normalize_requirement(parsed)


def _normalize_str_list(items: Any) -> list[str]:
    """Coerce a value that should be list[str] but may contain stray dicts (Gemini's
    JSON output isn't schema-enforced, so it occasionally nests an object where a
    plain string was asked for) back into plain strings."""
    if not isinstance(items, list):
        return []
    result: list[str] = []
    for item in items:
        if isinstance(item, str):
            if item.strip():
                result.append(item.strip())
        elif isinstance(item, dict):
            name = item.get("item") or item.get("name") or item.get("type") or item.get("label")
            if name:
                result.append(str(name).strip())
        elif item is not None:
            result.append(str(item).strip())
    return result


def _normalize_requirement(req: dict[str, Any]) -> dict[str, Any]:
    """Sanitize the LLM's raw JSON once, at the single place it becomes
    ``structured_requirement`` — every downstream consumer (layout_agent's
    ``", ".join(...)``/``.lower()`` calls, adjuster.py, inpaint.py) assumes
    ``layout_constraints.{must_keep,must_add,must_remove}`` are ``list[str]``
    and crashes on a stray dict item otherwise."""
    if not isinstance(req, dict):
        return req
    constraints = req.get("layout_constraints")
    if isinstance(constraints, dict):
        for key in ("must_keep", "must_add", "must_remove"):
            if key in constraints:
                constraints[key] = _normalize_str_list(constraints[key])
    return req
