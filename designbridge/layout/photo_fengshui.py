"""照片風水健檢：從一張現況照推估俯視平面（家具＋門窗），再交給 fengshui_audit 打分。

單張照片看不到鏡頭背後那面牆，那裡的門窗只能用猜的——猜的都標 `assumed`，
前端要讓使用者確認或改掉，不能當成事實。
"""

from __future__ import annotations

from typing import Any

from designbridge.layout.layout_items import FURNITURE_SIZES, _normalize_ftype, _parse_llm_layout

_KNOWN_TYPES = sorted(k for k in FURNITURE_SIZES if k != "default")
_ROOM_TYPES = ("living_room", "bedroom", "kitchen", "study", "bathroom", "dining_room", "kids_room")
_WALLS = ("far", "near", "left", "right")


def _prompt(room_type_hint: str | None) -> str:
    hint = f"The user says this room is a {room_type_hint}. " if room_type_hint else ""
    return (
        "You are an interior surveyor. From this single photo of a room, reconstruct an "
        "approximate TOP-DOWN floor plan.\n"
        f"{hint}"
        "Walls: the camera stands at the NEAR wall looking at the FAR wall; LEFT and RIGHT are as "
        "seen in the photo. The floor plan is NOT the photo — something at the bottom of the photo "
        "is close to the camera, something against the back of the room is at the FAR wall.\n"
        "List only FLOOR-STANDING furniture and appliances (plus mirrors). Skip pendant lamps, "
        "wall cabinets hung above counters, shelves/rails, small decor and countertop items. "
        "A run of base cabinets along one wall is ONE `cabinet` entry.\n"
        f"Furniture types — use ONLY: {', '.join(_KNOWN_TYPES)}.\n"
        "For each piece: `wall` = the wall it stands against (far|left|right|near), or `none` if it "
        "stands free in the room; `pos` = its centre along that wall in [0, 1] (far/near walls: "
        "measured left→right; left/right walls: measured far→near); `length_m` = size along the wall, "
        "`depth_m` = how far it sticks out from the wall. For `none` give `cx`, `cy` = its centre in "
        "[0, 1] (x left→right, y far→near) and `length_m` (x size), `depth_m` (y size).\n"
        "Doors and windows you can see: `wall`, `pos`, `width_m`.\n"
        "`image_box` = [x0, y0, x1, y1] of the object in the PHOTO, normalized to [0, 1] "
        "(origin top-left of the image).\n"
        f"room_type must be one of: {', '.join(_ROOM_TYPES)}.\n"
        "Return STRICT JSON only:\n"
        '{"room_type":"bedroom","room_w_m":3.6,"room_d_m":3.2,'
        '"furniture":[{"type":"bed","wall":"far","pos":0.4,"length_m":1.6,"depth_m":2.0,"image_box":[0.3,0.4,0.8,0.9]},'
        '{"type":"rug","wall":"none","cx":0.5,"cy":0.6,"length_m":2.0,"depth_m":1.4,"image_box":[0.2,0.7,0.8,0.95]}],'
        '"doors":[{"wall":"right","pos":0.8,"width_m":0.9,"image_box":[0.85,0.2,1.0,0.9]}],'
        '"windows":[{"wall":"far","pos":0.5,"width_m":1.5,"image_box":[0.35,0.15,0.65,0.5]}],'
        '"confidence":"medium"}'
    )


def _footprint(f: dict, room_w: float, room_d: float) -> tuple[float, float, float, float] | None:
    """靠牆的家具：從（牆, 沿牆位置, 長, 深）算出歸一化方框；獨立擺放的用中心點。"""
    length = _clamp(f.get("length_m"), 0.2, 8.0, 1.0)
    depth = _clamp(f.get("depth_m"), 0.1, 4.0, 0.6)
    wall = str(f.get("wall", "none")).lower()
    if wall in ("far", "near"):
        w, h = min(1.0, length / room_w), min(1.0, depth / room_d)
        x = _clamp(f.get("pos"), 0.0, 1.0, 0.5) - w / 2
        y = 0.0 if wall == "far" else 1.0 - h
    elif wall in ("left", "right"):
        w, h = min(1.0, depth / room_w), min(1.0, length / room_d)
        y = _clamp(f.get("pos"), 0.0, 1.0, 0.5) - h / 2
        x = 0.0 if wall == "left" else 1.0 - w
    else:
        w, h = min(1.0, length / room_w), min(1.0, depth / room_d)
        x = _clamp(f.get("cx"), 0.0, 1.0, 0.5) - w / 2
        y = _clamp(f.get("cy"), 0.0, 1.0, 0.5) - h / 2
    return max(0.0, min(1.0 - w, x)), max(0.0, min(1.0 - h, y)), w, h


def _clamp(v: Any, lo: float, hi: float, default: float) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def _unit(v: Any) -> float:
    """Gemini 偶爾漏掉小數點（6.72）或改用 0–1000 刻度，除以 10 直到落回 [0, 1]。"""
    v = abs(float(v))
    while v > 1.0:
        v /= 10.0
    return v


def _box(raw: Any) -> list[float] | None:
    if isinstance(raw, list) and len(raw) == 4:
        try:
            x0, y0, x1, y1 = (_unit(v) for v in raw)
        except (TypeError, ValueError):
            return None
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        if x1 - x0 < 0.01 or y1 - y0 < 0.01:
            return None
        return [x0, y0, x1, y1]
    return None


def opening_box(wall: str, pos: float, width_m: float, room_w: float, room_d: float) -> dict:
    """（牆, 沿牆位置, 寬度）→ special_constraints 用的歸一化開口方框。"""
    if wall in ("far", "near"):
        frac = min(0.9, width_m / room_w)
        x = max(0.0, min(1.0 - frac, pos - frac / 2))
        return {"x": round(x, 4), "y": 0.0 if wall == "far" else 0.98, "w": round(frac, 4), "h": 0.02, "wall": wall}
    frac = min(0.9, width_m / room_d)
    y = max(0.0, min(1.0 - frac, pos - frac / 2))
    return {"x": 0.0 if wall == "left" else 0.98, "y": round(y, 4), "w": 0.02, "h": round(frac, 4), "wall": wall}


def parse_room_photo(image_path: str, room_type_hint: str | None = None) -> dict[str, Any] | None:
    from designbridge.render.llm import call_llm

    try:
        text = call_llm(_prompt(room_type_hint), images=[image_path], json_mode=True, max_tokens=6000)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  photo fengshui parse failed: {e}")
        return None
    data = _parse_llm_layout(text) or {}

    room_w = _clamp(data.get("room_w_m"), 1.5, 15.0, 4.0)
    room_d = _clamp(data.get("room_d_m"), 1.5, 15.0, 3.5)
    room_type = data.get("room_type") if data.get("room_type") in _ROOM_TYPES else (room_type_hint or "living_room")

    placements: list[dict] = []
    for i, f in enumerate(data.get("furniture") or []):
        ftype = _normalize_ftype(str(f.get("type", "")))
        if ftype not in FURNITURE_SIZES or ftype == "default":
            continue
        x, y, w, h = _footprint(f, room_w, room_d)
        placements.append({
            "id": f"{ftype}_{i + 1}", "type": ftype, "rotation": 0,
            "x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4),
            "image_box": _box(f.get("image_box")),
        })

    def _openings(key: str, default_width: float) -> list[dict]:
        out = []
        for o in data.get(key) or []:
            wall = str(o.get("wall", "")).lower()
            if wall not in _WALLS:
                continue
            pos = _clamp(o.get("pos"), 0.0, 1.0, 0.5)
            width = _clamp(o.get("width_m"), 0.4, 6.0, default_width)
            out.append({**opening_box(wall, pos, width, room_w, room_d),
                        "pos": round(pos, 3), "width_m": round(width, 2),
                        "image_box": _box(o.get("image_box")), "assumed": False})
        return out

    doors = _openings("doors", 0.9)
    windows = _openings("windows", 1.2)
    if not doors:
        # 門多半在鏡頭背後：先假設在近牆中央，請使用者確認
        doors = [{**opening_box("near", 0.5, 0.9, room_w, room_d),
                  "pos": 0.5, "width_m": 0.9, "image_box": None, "assumed": True}]

    return {
        "room_type": room_type,
        "room_w": round(room_w, 2),
        "room_d": round(room_d, 2),
        "placements": placements,
        "doors": doors,
        "windows": windows,
        "confidence": str(data.get("confidence") or "medium"),
    }
