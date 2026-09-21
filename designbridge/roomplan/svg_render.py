"""Render a multi-room floor plan as an SVG string.

Generalizes the technique from layout_agent.py's dead `_build_floor_plan_svg`: paint one
solid "wall body" rect covering the whole footprint, then paint each room's floor polygon
(inset by half its wall thickness per edge) on top — the leftover gaps between insets
*become* the interior/exterior walls, so no separate wall-polygon rendering is needed.
"""

from __future__ import annotations

from designbridge.roomplan.constants import EXTERIOR_WALL_THICKNESS_M, INTERIOR_WALL_THICKNESS_M, PING_TO_M2
from designbridge.roomplan.geometry import is_exterior_edge, room_edges
from designbridge.roomplan.schemas import DoorOpening, RoomInstance, WallSegment, WindowOpening

PX_PER_M = 50.0
MARGIN_PX = 90.0

_WALL_FILL = "#c8c8c8"
_WALL_STROKE = "#1a1a1a"
_FLOOR_FILL = "#f8f6f0"
_FLOOR_STROKE = "#333333"
_DOOR_STROKE = "#555555"
_WINDOW_FILL = "#c0daf8"
_WINDOW_STROKE = "#2e6ab5"
_DIM_STROKE = "#444444"
_TEXT_FILL = "#111111"
_FURNITURE_STROKE = "#2a2a2a"
_FURNITURE_FILL = "white"

# ───────────────────────── Default furniture symbols ─────────────────────────
# Default furniture per room — same normalized (fraction-of-room) layout as the
# frontend's CAD_DEFAULT_LAYOUT (useDesignFlow.js), so this whole-floor preview and the
# single-room editor agree once a room is picked. Drawn as simplified architectural
# top-down symbols (bed + pillow, chairs with a backrest facing the table, hatched
# wardrobe, tub/toilet outlines, ...) rather than plain boxes, under the room name/area
# text so the label always stays legible regardless of what furniture sits behind it.
_ROOM_TYPE_TO_FURNITURE_KEY = {
    "bedroom_master": "bedroom",
    "bedroom": "bedroom",
    "living_dining": "living_dining",
    "kitchen": "kitchen",
    "bathroom": "bathroom",
    "balcony": "balcony",
}

_DEFAULT_FURNITURE: dict[str, list[dict]] = {
    "bedroom": [
        {"type": "bed", "x": 0.30, "y": 0.28, "w": 0.22, "h": 0.28},
        {"type": "wardrobe", "x": 0.08, "y": 0.08, "w": 0.18, "h": 0.08},
        {"type": "nightstand", "x": 0.24, "y": 0.58, "w": 0.07, "h": 0.07},
    ],
    "living_dining": [
        {"type": "sofa", "x": 0.08, "y": 0.55, "w": 0.30, "h": 0.13},
        {"type": "coffee_table", "x": 0.16, "y": 0.42, "w": 0.15, "h": 0.10},
        {"type": "tv_unit", "x": 0.08, "y": 0.08, "w": 0.22, "h": 0.07},
        {"type": "dining_table", "x": 0.58, "y": 0.55, "w": 0.20, "h": 0.15},
        {"type": "chair", "x": 0.58, "y": 0.42, "w": 0.08, "h": 0.08, "facing": "down"},
        {"type": "chair", "x": 0.68, "y": 0.42, "w": 0.08, "h": 0.08, "facing": "down"},
        {"type": "chair", "x": 0.58, "y": 0.72, "w": 0.08, "h": 0.08, "facing": "up"},
        {"type": "chair", "x": 0.68, "y": 0.72, "w": 0.08, "h": 0.08, "facing": "up"},
    ],
    "kitchen": [
        {"type": "cabinet", "x": 0.05, "y": 0.05, "w": 0.30, "h": 0.08},
        {"type": "shelf", "x": 0.60, "y": 0.05, "w": 0.18, "h": 0.05},
    ],
    "bathroom": [
        {"type": "bathtub", "x": 0.05, "y": 0.05, "w": 0.30, "h": 0.14},
        {"type": "sink", "x": 0.60, "y": 0.10, "w": 0.10, "h": 0.08},
        {"type": "toilet", "x": 0.60, "y": 0.60, "w": 0.09, "h": 0.12},
    ],
    "balcony": [
        {"type": "washer", "x": 0.08, "y": 0.08, "w": 0.16, "h": 0.16},
        {"type": "drying_rack", "x": 0.40, "y": 0.10, "w": 0.20, "h": 0.06},
    ],
}


def _svg_rect(x: float, y: float, w: float, h: float, rx: float = 0,
              fill: str | None = None, stroke: str | None = None, sw: float = 1.2) -> str:
    fill = fill if fill is not None else _FURNITURE_FILL
    stroke = stroke or _FURNITURE_STROKE
    rx_attr = f' rx="{rx:.1f}"' if rx else ''
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}"{rx_attr} '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')


def _svg_ellipse(cx: float, cy: float, rx: float, ry: float,
                  fill: str | None = None, stroke: str | None = None, sw: float = 1.2) -> str:
    fill = fill if fill is not None else _FURNITURE_FILL
    stroke = stroke or _FURNITURE_STROKE
    return (f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')


def _svg_circle(cx: float, cy: float, r: float,
                 fill: str | None = None, stroke: str | None = None, sw: float = 1.0) -> str:
    fill = fill if fill is not None else _FURNITURE_FILL
    stroke = stroke or _FURNITURE_STROKE
    return f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'


def _svg_line(x1: float, y1: float, x2: float, y2: float, sw: float = 1.0) -> str:
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{_FURNITURE_STROKE}" stroke-width="{sw}"/>')


def _sym_bed(x: float, y: float, w: float, h: float) -> list[str]:
    out = [_svg_rect(x, y, w, h, rx=min(w, h) * 0.06)]
    pw, ph = w * 0.7, h * 0.16
    out.append(_svg_rect(x + (w - pw) / 2, y + h * 0.08, pw, ph, rx=ph * 0.3))
    fold_y = y + h * 0.62
    out.append(_svg_line(x + w * 0.06, fold_y, x + w * 0.94, fold_y))
    return out


def _sym_wardrobe(x: float, y: float, w: float, h: float) -> list[str]:
    out = [_svg_rect(x, y, w, h, fill="url(#roomplan-hatch)")]
    return out


def _sym_nightstand(x: float, y: float, w: float, h: float) -> list[str]:
    return [_svg_rect(x, y, w, h), _svg_circle(x + w * 0.5, y + h * 0.5, min(w, h) * 0.12)]


def _sym_sofa(x: float, y: float, w: float, h: float) -> list[str]:
    out = [_svg_rect(x, y, w, h, rx=min(w, h) * 0.15)]
    back_h = h * 0.34
    out.append(_svg_rect(x, y, w, back_h, rx=back_h * 0.3))
    arm_w = w * 0.10
    out.append(_svg_rect(x, y, arm_w, h, rx=arm_w * 0.3))
    out.append(_svg_rect(x + w - arm_w, y, arm_w, h, rx=arm_w * 0.3))
    seat_y0 = y + back_h
    seg = (w - 2 * arm_w) / 3
    for i in (1, 2):
        lx = x + arm_w + seg * i
        out.append(_svg_line(lx, seat_y0, lx, y + h, sw=0.8))
    return out


def _sym_coffee_table(x: float, y: float, w: float, h: float) -> list[str]:
    out = [_svg_rect(x, y, w, h, rx=min(w, h) * 0.2)]
    pad = min(w, h) * 0.18
    out.append(_svg_rect(x + pad, y + pad, w - 2 * pad, h - 2 * pad,
                          rx=max(0.0, min(w, h) * 0.12 - pad), fill="none", sw=0.8))
    return out


def _sym_tv_unit(x: float, y: float, w: float, h: float) -> list[str]:
    out = [_svg_rect(x, y, w, h)]
    sw_ = w * 0.55
    out.append(_svg_rect(x + (w - sw_) / 2, y + h * 0.18, sw_, h * 0.5, fill="none", sw=0.8))
    return out


def _sym_dining_table(x: float, y: float, w: float, h: float) -> list[str]:
    return [_svg_rect(x, y, w, h, rx=min(w, h) * 0.12)]


def _sym_chair(x: float, y: float, w: float, h: float, facing: str = "down") -> list[str]:
    out = [_svg_rect(x, y, w, h, rx=min(w, h) * 0.18)]
    back_t = min(w, h) * 0.24
    if facing == "down":       # backrest away from what's below (e.g. a table)
        out.append(_svg_rect(x, y, w, back_t, rx=back_t * 0.3))
    elif facing == "up":
        out.append(_svg_rect(x, y + h - back_t, w, back_t, rx=back_t * 0.3))
    elif facing == "right":
        out.append(_svg_rect(x, y, back_t, h, rx=back_t * 0.3))
    else:  # left
        out.append(_svg_rect(x + w - back_t, y, back_t, h, rx=back_t * 0.3))
    return out


def _sym_cabinet(x: float, y: float, w: float, h: float) -> list[str]:
    return [_svg_rect(x, y, w, h), _svg_line(x + w / 2, y, x + w / 2, y + h, sw=0.9)]


def _sym_shelf(x: float, y: float, w: float, h: float) -> list[str]:
    out = [_svg_rect(x, y, w, h)]
    for f in (1 / 3, 2 / 3):
        yy = y + h * f
        out.append(_svg_line(x, yy, x + w, yy, sw=0.8))
    return out


def _sym_bathtub(x: float, y: float, w: float, h: float) -> list[str]:
    out = [_svg_rect(x, y, w, h, rx=min(w, h) * 0.4)]
    pad = min(w, h) * 0.14
    out.append(_svg_rect(x + pad, y + pad, w - 2 * pad, h - 2 * pad,
                          rx=max(0.0, min(w, h) * 0.4 - pad), fill="none", sw=0.8))
    return out


def _sym_sink(x: float, y: float, w: float, h: float) -> list[str]:
    out = [_svg_rect(x, y, w, h, rx=min(w, h) * 0.15)]
    out.append(_svg_ellipse(x + w / 2, y + h / 2, w * 0.32, h * 0.32, fill="none", sw=0.8))
    return out


def _sym_toilet(x: float, y: float, w: float, h: float) -> list[str]:
    tank_h = h * 0.28
    out = [_svg_rect(x, y, w, tank_h)]
    bowl_cy = y + tank_h + (h - tank_h) / 2
    out.append(_svg_ellipse(x + w / 2, bowl_cy, w * 0.42, (h - tank_h) * 0.46))
    return out


def _sym_washer(x: float, y: float, w: float, h: float) -> list[str]:
    out = [_svg_rect(x, y, w, h)]
    out.append(_svg_circle(x + w / 2, y + h / 2, min(w, h) * 0.34, fill="none", sw=1.0))
    out.append(_svg_circle(x + w / 2, y + h / 2, min(w, h) * 0.20, fill="none", sw=0.7))
    return out


def _sym_drying_rack(x: float, y: float, w: float, h: float) -> list[str]:
    out = [_svg_rect(x, y, w, h, fill="none")]
    n = 4
    for i in range(1, n):
        yy = y + h * i / n
        out.append(_svg_line(x, yy, x + w, yy, sw=0.8))
    return out


def _sym_default(x: float, y: float, w: float, h: float) -> list[str]:
    return [_svg_rect(x, y, w, h)]


_SYMBOL_FNS = {
    "bed": _sym_bed,
    "wardrobe": _sym_wardrobe,
    "nightstand": _sym_nightstand,
    "sofa": _sym_sofa,
    "coffee_table": _sym_coffee_table,
    "tv_unit": _sym_tv_unit,
    "dining_table": _sym_dining_table,
    "chair": _sym_chair,
    "cabinet": _sym_cabinet,
    "shelf": _sym_shelf,
    "bathtub": _sym_bathtub,
    "sink": _sym_sink,
    "toilet": _sym_toilet,
    "washer": _sym_washer,
    "drying_rack": _sym_drying_rack,
}


def _furniture_svg(room: RoomInstance, fx1: float, fy1: float, fx2: float, fy2: float) -> list[str]:
    key = _ROOM_TYPE_TO_FURNITURE_KEY.get(room.room_type)
    items = _DEFAULT_FURNITURE.get(key, []) if key else []
    if not items:
        return []
    rw, rh = fx2 - fx1, fy2 - fy1
    lines = []
    for item in items:
        x, y = fx1 + item["x"] * rw, fy1 + item["y"] * rh
        w, h = item["w"] * rw, item["h"] * rh
        fn = _SYMBOL_FNS.get(item["type"], _sym_default)
        if "facing" in item:
            lines.extend(fn(x, y, w, h, facing=item["facing"]))
        else:
            lines.extend(fn(x, y, w, h))
    return lines


def render_room_plan_svg(
    rooms: list[RoomInstance],
    walls: list[WallSegment],
    doors: list[DoorOpening],
    windows: list[WindowOpening],
    bounding_w: float,
    bounding_d: float,
    total_m2: float,
) -> str:
    e = EXTERIOR_WALL_THICKNESS_M
    i_t = INTERIOR_WALL_THICKNESS_M

    footprint_w_m = bounding_w + e
    footprint_h_m = bounding_d + e
    canvas_w = MARGIN_PX * 2 + footprint_w_m * PX_PER_M
    canvas_h = MARGIN_PX * 2 + footprint_h_m * PX_PER_M

    def px(x_m: float) -> float:
        return MARGIN_PX + (x_m + e / 2) * PX_PER_M

    def py(y_m: float) -> float:
        return MARGIN_PX + (y_m + e / 2) * PX_PER_M

    def pl(len_m: float) -> float:
        return len_m * PX_PER_M

    lines: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w:.0f}" height="{canvas_h:.0f}" '
        f'viewBox="0 0 {canvas_w:.0f} {canvas_h:.0f}" font-family="Arial, Helvetica, sans-serif">',
        '<defs>'
        '<pattern id="roomplan-hatch" width="6" height="6" patternUnits="userSpaceOnUse" '
        'patternTransform="rotate(45)">'
        f'<rect width="6" height="6" fill="white"/>'
        f'<line x1="0" y1="0" x2="0" y2="6" stroke="{_FURNITURE_STROKE}" stroke-width="1"/>'
        '</pattern>'
        '</defs>',
        f'<rect width="{canvas_w:.0f}" height="{canvas_h:.0f}" fill="white"/>',
    ]

    fx1, fy1 = px(-e / 2), py(-e / 2)
    fx2, fy2 = px(bounding_w + e / 2), py(bounding_d + e / 2)
    lines.append(
        f'<rect x="{fx1:.1f}" y="{fy1:.1f}" width="{fx2-fx1:.1f}" height="{fy2-fy1:.1f}" '
        f'fill="{_WALL_FILL}" stroke="{_WALL_STROKE}" stroke-width="2"/>'
    )

    for room in rooms:
        left_t = e if is_exterior_edge("left", room, bounding_w, bounding_d) else i_t
        right_t = e if is_exterior_edge("right", room, bounding_w, bounding_d) else i_t
        top_t = e if is_exterior_edge("top", room, bounding_w, bounding_d) else i_t
        bottom_t = e if is_exterior_edge("bottom", room, bounding_w, bounding_d) else i_t

        fx1r = px(room.rect.x + left_t / 2)
        fy1r = py(room.rect.y + top_t / 2)
        fx2r = px(room.rect.right - right_t / 2)
        fy2r = py(room.rect.bottom - bottom_t / 2)
        # class/data-* hooks: no visual effect here, but let the frontend attach a
        # click handler per room (e.g. a "pick a room to edit" step) without having
        # to re-derive each room's on-screen rect from the meter coordinates.
        lines.append(
            f'<g class="room-rect" data-room-id="{room.id}" data-room-type="{room.room_type}">'
        )
        lines.append(
            f'<rect class="room-floor" x="{fx1r:.1f}" y="{fy1r:.1f}" width="{fx2r-fx1r:.1f}" height="{fy2r-fy1r:.1f}" '
            f'fill="{_FLOOR_FILL}" stroke="{_FLOOR_STROKE}" stroke-width="1"/>'
        )
        # Wrapped in its own group (class="room-furniture") so the frontend can swap
        # these default symbols out for the user's actual live-edited placements
        # (see CadRoomMiniMap.vue) without touching the floor rect or the labels.
        furniture_lines = _furniture_svg(room, fx1r, fy1r, fx2r, fy2r)
        if furniture_lines:
            lines.append('<g class="room-furniture">')
            lines.extend(furniture_lines)
            lines.append('</g>')

        # White stroke "halo" behind the label glyphs (paint-order draws it under the
        # fill) so the room name/area stay legible over whatever furniture line happens
        # to cross behind them, without having to estimate each string's pixel width.
        cx, cy = (fx1r + fx2r) / 2, (fy1r + fy2r) / 2
        halo = ' paint-order="stroke" stroke="white" stroke-width="3" stroke-linejoin="round"'
        lines.append(
            f'<text x="{cx:.1f}" y="{cy-6:.1f}" font-size="13" font-weight="bold"{halo} '
            f'text-anchor="middle" fill="{_TEXT_FILL}">{room.label_zh}</text>'
        )
        lines.append(
            f'<text x="{cx:.1f}" y="{cy+11:.1f}" font-size="11"{halo} '
            f'text-anchor="middle" fill="{_TEXT_FILL}">{room.actual_area_m2:.1f} m²</text>'
        )
        lines.append('</g>')

    for door in doors:
        half_w = pl(door.width_m) / 2
        wt = e if door.kind == "entry" else i_t
        gap_fill = "white" if door.kind == "entry" else _FLOOR_FILL
        cx, cy = px(door.x), py(door.y)
        if door.orientation == "horizontal":
            gap_h = pl(wt) + 6
            lines.append(
                f'<rect x="{cx-half_w:.1f}" y="{cy-gap_h/2:.1f}" width="{half_w*2:.1f}" height="{gap_h:.1f}" fill="{gap_fill}"/>'
            )
            lines.append(
                f'<line x1="{cx-half_w:.1f}" y1="{cy:.1f}" x2="{cx-half_w:.1f}" y2="{cy-half_w*2:.1f}" '
                f'stroke="{_DOOR_STROKE}" stroke-width="1.3"/>'
            )
            lines.append(
                f'<path d="M {cx-half_w:.1f} {cy-half_w*2:.1f} A {half_w*2:.1f} {half_w*2:.1f} 0 0 1 {cx+half_w:.1f} {cy:.1f}" '
                f'stroke="{_DOOR_STROKE}" stroke-width="1.1" fill="none" stroke-dasharray="4,3"/>'
            )
        else:
            gap_w = pl(wt) + 6
            lines.append(
                f'<rect x="{cx-gap_w/2:.1f}" y="{cy-half_w:.1f}" width="{gap_w:.1f}" height="{half_w*2:.1f}" fill="{gap_fill}"/>'
            )
            lines.append(
                f'<line x1="{cx:.1f}" y1="{cy-half_w:.1f}" x2="{cx+half_w*2:.1f}" y2="{cy-half_w:.1f}" '
                f'stroke="{_DOOR_STROKE}" stroke-width="1.3"/>'
            )
            lines.append(
                f'<path d="M {cx+half_w*2:.1f} {cy-half_w:.1f} A {half_w*2:.1f} {half_w*2:.1f} 0 0 1 {cx:.1f} {cy+half_w:.1f}" '
                f'stroke="{_DOOR_STROKE}" stroke-width="1.1" fill="none" stroke-dasharray="4,3"/>'
            )

    for window in windows:
        half_w = pl(window.width_m) / 2
        cx, cy = px(window.x), py(window.y)
        wall_px = pl(e)
        if window.orientation == "horizontal":
            lines.append(
                f'<rect x="{cx-half_w:.1f}" y="{cy-wall_px/2:.1f}" width="{half_w*2:.1f}" height="{wall_px:.1f}" '
                f'fill="{_WINDOW_FILL}" stroke="{_WINDOW_STROKE}" stroke-width="1.3"/>'
            )
            lines.append(
                f'<line x1="{cx:.1f}" y1="{cy-wall_px/2:.1f}" x2="{cx:.1f}" y2="{cy+wall_px/2:.1f}" stroke="{_WINDOW_STROKE}" stroke-width="1.3"/>'
            )
        else:
            lines.append(
                f'<rect x="{cx-wall_px/2:.1f}" y="{cy-half_w:.1f}" width="{wall_px:.1f}" height="{half_w*2:.1f}" '
                f'fill="{_WINDOW_FILL}" stroke="{_WINDOW_STROKE}" stroke-width="1.3"/>'
            )
            lines.append(
                f'<line x1="{cx-wall_px/2:.1f}" y1="{cy:.1f}" x2="{cx+wall_px/2:.1f}" y2="{cy:.1f}" stroke="{_WINDOW_STROKE}" stroke-width="1.3"/>'
            )

    # Overall dimension lines — generalizes the single-room tick-mark convention in
    # layout_agent.py's _generate_floor_plan (there: one room; here: the whole footprint).
    dim_y = py(-e / 2) - 28
    x0, x1 = px(0), px(bounding_w)
    lines.append(f'<line x1="{x0:.1f}" y1="{dim_y:.1f}" x2="{x1:.1f}" y2="{dim_y:.1f}" stroke="{_DIM_STROKE}" stroke-width="1"/>')
    for tx in (x0, x1):
        lines.append(f'<line x1="{tx:.1f}" y1="{dim_y-5:.1f}" x2="{tx:.1f}" y2="{dim_y+5:.1f}" stroke="{_DIM_STROKE}" stroke-width="1"/>')
    lines.append(f'<text x="{(x0+x1)/2:.1f}" y="{dim_y-8:.1f}" font-size="12" text-anchor="middle" fill="{_DIM_STROKE}">{bounding_w:.2f} m</text>')

    dim_x = px(-e / 2) - 28
    y0, y1 = py(0), py(bounding_d)
    lines.append(f'<line x1="{dim_x:.1f}" y1="{y0:.1f}" x2="{dim_x:.1f}" y2="{y1:.1f}" stroke="{_DIM_STROKE}" stroke-width="1"/>')
    for ty in (y0, y1):
        lines.append(f'<line x1="{dim_x-5:.1f}" y1="{ty:.1f}" x2="{dim_x+5:.1f}" y2="{ty:.1f}" stroke="{_DIM_STROKE}" stroke-width="1"/>')
    lines.append(
        f'<text x="{dim_x-8:.1f}" y="{(y0+y1)/2:.1f}" font-size="12" text-anchor="middle" fill="{_DIM_STROKE}" '
        f'transform="rotate(-90 {dim_x-8:.1f} {(y0+y1)/2:.1f})">{bounding_d:.2f} m</text>'
    )

    na_x, na_y = canvas_w - MARGIN_PX + 20, MARGIN_PX * 0.55
    lines.append(f'<polygon points="{na_x:.1f},{na_y-14:.1f} {na_x-8:.1f},{na_y+8:.1f} {na_x+8:.1f},{na_y+8:.1f}" fill="#333"/>')
    lines.append(f'<text x="{na_x:.1f}" y="{na_y+21:.1f}" font-size="12" text-anchor="middle" fill="#333">N</text>')

    sb_x, sb_y = px(0), canvas_h - MARGIN_PX * 0.45
    sb_w = pl(1.0)
    lines.append(f'<rect x="{sb_x:.1f}" y="{sb_y-2:.1f}" width="{sb_w:.1f}" height="4" fill="{_DIM_STROKE}"/>')
    lines.append(f'<text x="{sb_x+sb_w/2:.1f}" y="{sb_y+15:.1f}" font-size="10" text-anchor="middle" fill="{_DIM_STROKE}">1 m</text>')

    total_ping = total_m2 / PING_TO_M2
    lines.append(
        f'<text x="{MARGIN_PX*0.3:.1f}" y="{MARGIN_PX*0.55:.1f}" font-size="14" font-weight="bold" '
        f'fill="{_TEXT_FILL}">總面積 {total_m2:.1f} m²（約 {total_ping:.1f} 坪）</text>'
    )

    lines.append('</svg>')
    return '\n'.join(lines)
