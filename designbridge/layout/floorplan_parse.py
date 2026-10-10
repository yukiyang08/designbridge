"""Parse an uploaded floor-plan image / detect rooms (Gemini vision)."""

from __future__ import annotations

from typing import Any

from designbridge.layout.layout_items import FURNITURE_SIZES, FurnitureItem, _parse_llm_layout
from designbridge.layout.layout_enforce import _clip_to_room
from designbridge.layout.floorplan_render import _generate_floor_plan


# ───────────────────── Parse an uploaded floor-plan image ─────────────────────

# Vocabulary we constrain Gemini to, so parsed types line up with FURNITURE_SIZES,
# heights, semantic shapes and floor-plan colors downstream.
_KNOWN_FURNITURE_TYPES = sorted(k for k in FURNITURE_SIZES if k != "default")


def parse_floor_plan_image(
    image_path: str,
    task_id: str,
    room_type: str = "living_room",
    room_w: float = 5.0,
    room_d: float = 4.0,
) -> dict[str, Any] | None:
    """Read furniture from a user-uploaded 2D floor-plan image via Gemini vision.

    Returns a scene_graph (furniture_placements + a re-rendered floor-plan PNG using
    the same coordinate system as the AI-generated layouts), so an uploaded plan can
    drive the SAME accurate layout-projection render path — and be edited in the 2D
    editor — instead of the weaker "raw image as Kontext guide" fallback.

    Returns ``None`` when parsing fails or finds nothing (caller then falls back).
    """
    from designbridge.render.llm import call_llm

    types_csv = ", ".join(_KNOWN_FURNITURE_TYPES)
    prompt = (
        "You are given a 2D top-down interior FLOOR PLAN image. Identify every piece "
        "of furniture drawn in it and return each one's position as a normalized "
        "bounding box.\n"
        "Coordinate system: origin at the TOP-LEFT of the room interior. "
        "x = 0 is the left wall → 1 is the right wall; y = 0 is the back/top wall → "
        "1 is the front/bottom wall. (x, y) is the TOP-LEFT corner of the footprint; "
        "(w, h) are its width and height. All four values are floats in [0, 1].\n"
        f"Use ONLY these furniture type keywords (map synonyms to the closest one): "
        f"{types_csv}. Skip any symbol you cannot confidently classify.\n"
        "Return STRICT JSON only, no prose, no markdown fences:\n"
        '{"furniture":[{"type":"sofa","x":0.05,"y":0.30,"w":0.30,"h":0.13}]}'
    )

    try:
        # ponytail: bounds worst-case latency/cost — observed avg is ~2.3-2.7k tokens
        # (ablation 4.4), a runaway repetition loop with no cap ran to the 32k platform
        # ceiling (308s, see ablation 4.3b). 4000 truncated dense plans (30+ items); 8000
        # still bounds the worst case while giving them room.
        text = call_llm(prompt, images=[image_path], json_mode=True, max_tokens=8000)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Gemini floor-plan parse failed: {e}")
        return None

    data = _parse_llm_layout(text)
    raw = (data or {}).get("furniture") or []
    if not raw:
        print("⚠️  Gemini floor-plan parse returned no furniture")
        return None

    items: list[FurnitureItem] = []
    for i, f in enumerate(raw):
        ftype = str(f.get("type", "default")).lower().replace(" ", "_")
        if ftype not in FURNITURE_SIZES:
            ftype = "default"
        dw, dh = FURNITURE_SIZES.get(ftype, FURNITURE_SIZES["default"])
        try:
            x = float(f.get("x", 0.1))
            y = float(f.get("y", 0.1))
            w = float(f.get("w", dw) or dw)
            h = float(f.get("h", dh) or dh)
        except (TypeError, ValueError):
            continue
        items.append(
            FurnitureItem(
                id=f"{ftype}_{i + 1}",
                type=ftype,
                x=max(0.0, min(0.98, x)),
                y=max(0.0, min(0.98, y)),
                w=max(0.02, min(1.0, w)),
                h=max(0.02, min(1.0, h)),
                rotation=float(f.get("rotation", 0) or 0),
            )
        )

    if not items:
        return None

    items = _clip_to_room(items)
    floor_plan_path = _generate_floor_plan(
        items, task_id, room_type=room_type, room_w=room_w, room_d=room_d
    )
    print(f"[parse_floor_plan] Gemini parsed {len(items)} items from uploaded plan")

    return {
        "furniture_placements": [it.to_dict() for it in items],
        "layout_prompt": "",
        "floor_plan_path": floor_plan_path,
        "room_w": room_w,
        "room_d": room_d,
        "source": "uploaded_plan_parsed",
    }


# Room types DesignBridge actually knows how to furnish/render (kept in sync with
# _ROOM_LABEL_MAP below and frontend/src/config/furniture.js ROOM_OPTIONS).
_KNOWN_ROOM_TYPES = ("living_room", "bedroom", "kitchen", "dining_room", "study")


def detect_rooms_in_floor_plan(image_path: str) -> list[dict] | None:
    """Find every distinct room/space in a (possibly whole-unit) floor-plan image via
    Gemini vision, so the caller can let the user pick one room before running it
    through :func:`parse_floor_plan_image`.

    Returns a list of ``{id, room_type, x, y, w, h}`` (same normalized, top-left-origin
    coordinate system as furniture bounding boxes). Rooms that don't match a type
    DesignBridge supports (bathroom, corridor, balcony, ...) come back as
    ``room_type: "other"``. Returns ``None`` on failure (caller should then treat the
    whole image as a single room, matching prior behavior).
    """
    from designbridge.render.llm import call_llm

    types_csv = ", ".join(_KNOWN_ROOM_TYPES)
    prompt = (
        "You are given a 2D top-down FLOOR PLAN image, which may show a single room or "
        "a whole multi-room unit (apartment/house). Identify every distinct enclosed "
        "room or space and return each one's bounding box.\n"
        "Coordinate system: origin at the TOP-LEFT of the whole image. x = 0 is the "
        "left edge → 1 is the right edge; y = 0 is the top edge → 1 is the bottom edge. "
        "(x, y) is the TOP-LEFT corner of the room's bounding box; (w, h) are its width "
        "and height. All four values are floats in [0, 1].\n"
        f"For `room_type`, use ONLY one of: {types_csv}. If a space clearly doesn't "
        "match any of these (e.g. bathroom, closet, corridor, balcony, entrance), use "
        '"other".\n'
        "Return STRICT JSON only, no prose, no markdown fences:\n"
        '{"rooms":[{"room_type":"bedroom","x":0.05,"y":0.05,"w":0.35,"h":0.4}]}'
    )

    try:
        text = call_llm(prompt, images=[image_path], json_mode=True, max_tokens=8000)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Gemini room detection failed: {e}")
        return None

    data = _parse_llm_layout(text)
    raw = (data or {}).get("rooms") or []
    if not raw:
        print("⚠️  Gemini room detection returned no rooms")
        return None

    rooms: list[dict] = []
    for i, r in enumerate(raw):
        try:
            x = float(r.get("x", 0.0))
            y = float(r.get("y", 0.0))
            w = float(r.get("w", 0.1))
            h = float(r.get("h", 0.1))
        except (TypeError, ValueError):
            continue
        room_type = str(r.get("room_type", "other")).lower().replace(" ", "_")
        if room_type not in _KNOWN_ROOM_TYPES:
            room_type = "other"
        rooms.append({
            "id": f"room_{i + 1}",
            "room_type": room_type,
            "x": max(0.0, min(0.98, x)),
            "y": max(0.0, min(0.98, y)),
            "w": max(0.02, min(1.0, w)),
            "h": max(0.02, min(1.0, h)),
        })

    return rooms or None
