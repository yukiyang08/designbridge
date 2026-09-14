# designbridge/layout_projection.py
"""Project a top-down 2D furniture layout into an eye-level perspective depth map.

The 2D floor plan and the 3D render live in *different camera views* (top-down vs
eye-level), so a raw floor-plan PNG cannot be used as a ControlNet hint — a control
image must share the output's viewpoint. This module rasterizes the layout's
furniture footprints (extruded to real-world heights) plus the room shell from a
virtual camera standing just inside the entrance, producing a depth map that *does*
match the render's viewpoint and can drive a depth-ControlNet.

Layout coordinate system (matches ``layout_agent`` / ``_furniture_to_spatial_text``):
    x in [0,1] : 0 = left wall,  1 = right wall
    y in [0,1] : 0 = back/far wall, 1 = front/entrance wall
    (x, y) = top-left corner of the footprint; (w, h) = size.

The camera stands at the entrance (front wall, y=1) at eye height, looking toward the
back wall (y=0) — the same viewpoint the spatial prompt describes.

Depth encoding follows the MiDaS convention used elsewhere in the pipeline
(``vision.run_depth_estimation``): near = bright (255), far = dark (0).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from designbridge.core.config import Config

# Approximate real-world heights (metres) per furniture type. Floor-standing objects
# are extruded from the floor (y=0) up to this height when building the depth scene.
_FURNITURE_HEIGHTS: dict[str, float] = {
    "sofa": 0.85, "armchair": 0.85, "chair": 0.90, "stool": 0.55,
    "bed": 0.55, "bunk_bed": 1.60, "crib": 0.90,
    "wardrobe": 2.00, "bookshelf": 1.80, "shelf": 1.20, "cabinet": 1.00,
    "sideboard": 0.85, "dresser": 0.80, "drawer": 0.75,
    "desk": 0.75, "dining_table": 0.75, "coffee_table": 0.40, "side_table": 0.55,
    "nightstand": 0.55, "console": 0.80,
    "tv_unit": 0.50, "tv": 0.70, "fridge": 1.80, "washing_machine": 0.85,
    "plant": 1.30, "lamp": 1.50, "floor_lamp": 1.60,
    "rug": 0.02, "carpet": 0.02,
    "default": 0.70,
}

_DEFAULT_ROOM_HEIGHT = 2.70


def _furniture_height(ftype: str) -> float:
    return _FURNITURE_HEIGHTS.get((ftype or "").lower(), _FURNITURE_HEIGHTS["default"])


class _Camera:
    """Pinhole camera looking along +Z (into the room), with optional downward pitch.

    World axes: X = right (0..room_w), Y = up (0..room_h), Z = forward/depth
    (0 = entrance/front wall, room_d = back/far wall). The camera sits at
    (room_w/2, eye_h, -setback) so the whole room is in front of it.
    """

    def __init__(
        self,
        room_w: float,
        room_d: float,
        img_w: int,
        img_h: int,
        *,
        fov_v_deg: float = 60.0,
        eye_h: float = 1.35,
        setback: float = 0.6,
        target_h: float = 1.1,
        target_depth_frac: float = 0.6,
    ) -> None:
        self.img_w = img_w
        self.img_h = img_h
        self.cx = img_w / 2.0
        self.cy = img_h / 2.0
        # Focal length in pixels derived from the *vertical* FOV; horizontal FOV then
        # follows the image aspect ratio automatically.
        self.f = (img_h / 2.0) / math.tan(math.radians(fov_v_deg) / 2.0)
        self.eye = np.array([room_w / 2.0, eye_h, -float(setback)], dtype=np.float64)
        self.setback = float(setback)
        self.room_d = room_d

        # Proper look-at basis aimed at a point inside the room (room-centre floor by
        # default). This stays correct at any elevation — raising the camera and it
        # keeps the whole layout framed, unlike a naive pitch rotation.
        target = np.array(
            [room_w / 2.0, float(target_h), float(target_depth_frac) * room_d],
            dtype=np.float64,
        )
        fwd = target - self.eye
        fwd = fwd / (np.linalg.norm(fwd) + 1e-9)
        world_up = np.array([0.0, 1.0, 0.0])
        # Screen-right is up x fwd, not fwd x up. The latter yields -X, which makes R a
        # reflection (det -1) instead of a rotation, silently mirroring the room: layout
        # x=0 -- the "left wall", drawn on the left of the 2D plan and described as "on
        # the left side" in the prompt -- would land on the RIGHT of the control image,
        # so the render contradicts both the plan the user approved and its own prompt.
        right = np.cross(world_up, fwd)
        right = right / (np.linalg.norm(right) + 1e-9)
        up = np.cross(fwd, right)
        self.R = np.stack([right, up, fwd])  # rows [right, up, forward]

    def to_cam(self, pts: np.ndarray) -> np.ndarray:
        """World points (N,3) -> camera space (N,3)."""
        return (self.R @ (pts - self.eye).T).T


def _quad(a, b, c, d) -> list[np.ndarray]:
    """A planar quad a-b-c-d as two triangles."""
    a, b, c, d = (np.array(v, dtype=np.float64) for v in (a, b, c, d))
    return [np.stack([a, b, c]), np.stack([a, c, d])]


def _box_faces(x0, x1, z0, z1, y0, y1) -> list[np.ndarray]:
    """5 visible faces of an axis-aligned box (bottom face omitted)."""
    faces: list[np.ndarray] = []
    faces += _quad([x0, y1, z0], [x1, y1, z0], [x1, y1, z1], [x0, y1, z1])  # top
    faces += _quad([x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0])  # front (near)
    faces += _quad([x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1])  # back (far)
    faces += _quad([x0, y0, z0], [x0, y0, z1], [x0, y1, z1], [x0, y1, z0])  # left
    faces += _quad([x1, y0, z0], [x1, y0, z1], [x1, y1, z1], [x1, y1, z0])  # right
    return faces


# ── Semantic furniture silhouettes ─────────────────────────────────────────────
# Instead of extruding every footprint into one plain cuboid (a box the model can't
# tell apart from a wardrobe), we assemble each piece from a few sub-boxes so the
# *silhouette* already hints the category: a sofa has a low seat + a taller backrest
# + armrests, a bed is a low platform + a headboard, a table is a thin top on legs.
# Cost is only in this projection step; the render pipeline is unchanged.
_SEATING = {"sofa", "armchair", "chair", "stool", "bench", "loveseat"}
_BEDS = {"bed", "bunk_bed", "crib", "daybed"}
_TABLES = {"dining_table", "coffee_table", "side_table", "desk", "table"}
# Slender free-standing decor. Extruding these as a full-footprint cuboid makes a
# tall wall-to-wall column (a 1.3 m "plant" reads as a pillar, not a potted plant),
# so the model misplaces or ignores them. Draw a narrow central pole instead: keeps
# the vertical cue (it IS a tall-ish object) without the blocking box silhouette.
_SLIM_DECOR = {"plant", "lamp", "floor_lamp", "standing_lamp", "vase"}
_SLIM_FRAC = 0.4  # central column footprint fraction


def _shape_kind(ftype: str) -> str:
    t = (ftype or "").lower()
    if t in _SLIM_DECOR:
        return "slim"
    if t in _SEATING:
        return "seat"
    if t in _BEDS:
        return "bed"
    if t in _TABLES:
        return "table"
    return "box"


def _nearest_wall(x0: float, x1: float, z0: float, z1: float, W: float, D: float) -> str:
    """Which room wall the footprint sits closest to (back/front/left/right).

    Used to decide where a backrest / headboard goes — furniture backs onto walls,
    matching the wall-adjacency logic in ``_furniture_to_spatial_text``.
    World axes: x=0 left, x=W right, z=0 front/entrance, z=D back/far wall.
    """
    d_back, d_front, d_left, d_right = D - z1, z0, x0, W - x1
    m = min(d_back, d_front, d_left, d_right)
    if m == d_back:
        return "back"
    if m == d_front:
        return "front"
    if m == d_left:
        return "left"
    return "right"


def _furniture_parts(
    kind: str, x0: float, x1: float, z0: float, z1: float, height: float, back: str
) -> list[tuple[float, float, float, float, float, float]]:
    """Decompose one piece into sub-boxes (x0,x1,z0,z1,y0,y1) forming its silhouette.

    ``back`` (back/front/left/right) is the edge a backrest/headboard rests against.
    """
    dx, dz = x1 - x0, z1 - z0

    def _back_slab(y0: float, y1: float, frac: float) -> tuple:
        """A slab spanning the full width along the ``back`` edge, ``frac`` deep."""
        tz = max(0.05, dz * frac)
        tx = max(0.05, dx * frac)
        if back == "back":
            return (x0, x1, z1 - tz, z1, y0, y1)
        if back == "front":
            return (x0, x1, z0, z0 + tz, y0, y1)
        if back == "left":
            return (x0, x0 + tx, z0, z1, y0, y1)
        return (x1 - tx, x1, z0, z1, y0, y1)  # right

    if kind == "slim":
        # A narrow central column (plant stem / lamp pole) — slender, not a wall.
        cx0, cx1 = x0 + dx * (1 - _SLIM_FRAC) / 2, x1 - dx * (1 - _SLIM_FRAC) / 2
        cz0, cz1 = z0 + dz * (1 - _SLIM_FRAC) / 2, z1 - dz * (1 - _SLIM_FRAC) / 2
        return [(cx0, cx1, cz0, cz1, 0.0, height)]

    if kind == "seat":
        seat_h = min(0.45, height * 0.5)
        arm_h = min(height, seat_h + 0.18)
        parts = [
            (x0, x1, z0, z1, 0.0, seat_h),          # seat cushion
            _back_slab(seat_h, height, 0.22),        # backrest
        ]
        # armrests on the two edges perpendicular to the back
        aw_x, aw_z = max(0.05, dx * 0.14), max(0.05, dz * 0.14)
        if back in ("back", "front"):
            parts += [(x0, x0 + aw_x, z0, z1, 0.0, arm_h), (x1 - aw_x, x1, z0, z1, 0.0, arm_h)]
        else:
            parts += [(x0, x1, z0, z0 + aw_z, 0.0, arm_h), (x0, x1, z1 - aw_z, z1, 0.0, arm_h)]
        return parts

    if kind == "bed":
        mattress_h = min(0.45, height * 0.7)
        headboard_h = max(height, mattress_h + 0.35)
        return [
            (x0, x1, z0, z1, 0.0, mattress_h),       # mattress platform
            _back_slab(0.0, headboard_h, 0.10),      # headboard
        ]

    if kind == "table":
        top_th = min(0.05, height * 0.15)
        leg_top = max(0.0, height - top_th)
        lw_x, lw_z = max(0.03, dx * 0.08), max(0.03, dz * 0.08)
        return [
            (x0, x1, z0, z1, leg_top, height),       # tabletop (floating slab reads as a table)
            (x0, x0 + lw_x, z0, z0 + lw_z, 0.0, leg_top),
            (x1 - lw_x, x1, z0, z0 + lw_z, 0.0, leg_top),
            (x0, x0 + lw_x, z1 - lw_z, z1, 0.0, leg_top),
            (x1 - lw_x, x1, z1 - lw_z, z1, 0.0, leg_top),
        ]

    return [(x0, x1, z0, z1, 0.0, height)]           # plain box (tall storage, etc.)


def _build_scene(
    placements: list[dict[str, Any]],
    room_w: float,
    room_d: float,
    room_h: float,
    *,
    semantic_shapes: bool = True,
) -> list[np.ndarray]:
    """Assemble room-shell + furniture triangles in world space.

    ``semantic_shapes``: extrude each piece into a rough category silhouette
    (see ``_furniture_parts``) rather than a single cuboid.
    """
    W, D, H = room_w, room_d, room_h
    tris: list[np.ndarray] = []

    # Room shell (inward-facing surfaces). Winding is irrelevant — no backface cull.
    tris += _quad([0, 0, 0], [W, 0, 0], [W, 0, D], [0, 0, D])  # floor
    tris += _quad([0, H, 0], [W, H, 0], [W, H, D], [0, H, D])  # ceiling
    tris += _quad([0, 0, D], [W, 0, D], [W, H, D], [0, H, D])  # back wall
    tris += _quad([0, 0, 0], [0, 0, D], [0, H, D], [0, H, 0])  # left wall
    tris += _quad([W, 0, 0], [W, 0, D], [W, H, D], [W, H, 0])  # right wall

    for item in placements:
        try:
            x = float(item.get("x", 0.0))
            y = float(item.get("y", 0.0))
            w = float(item.get("w", 0.0))
            h = float(item.get("h", 0.0))
        except (TypeError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        ftype = str(item.get("type", "default"))
        height = _furniture_height(ftype)

        x0 = max(0.0, x) * W
        x1 = min(1.0, x + w) * W
        # y=0 is the back wall (far, Z=D); y=1 is the front wall (near, Z=0).
        z_near = (1.0 - min(1.0, y + h)) * D
        z_far = (1.0 - max(0.0, y)) * D
        if x1 <= x0 or z_far <= z_near:
            continue

        if semantic_shapes and height >= 0.10:
            kind = _shape_kind(ftype)
            back = _nearest_wall(x0, x1, z_near, z_far, W, D)
            for bx0, bx1, bz0, bz1, by0, by1 in _furniture_parts(
                kind, x0, x1, z_near, z_far, height, back
            ):
                if bx1 > bx0 and bz1 > bz0 and by1 > by0:
                    tris += _box_faces(bx0, bx1, bz0, bz1, by0, by1)
        else:
            tris += _box_faces(x0, x1, z_near, z_far, 0.0, height)

    return tris


# ── Semantic region (segmentation-style) colours ───────────────────────────────
# Distinct, roughly ADE20K-aligned colours per furniture class. Used to render a
# flat per-object region map: each piece fills its footprint with ONE solid colour,
# giving the model an explicit "this whole area = a sofa" signal — a stronger spatial
# prior than a grey depth blob. Room shell uses ADE wall/floor/ceiling colours.
_SEG_COLORS: dict[str, tuple[int, int, int]] = {
    "wall": (120, 120, 120), "floor": (80, 50, 50), "ceiling": (120, 120, 80),
    "sofa": (11, 102, 255), "loveseat": (11, 102, 255), "armchair": (8, 255, 214),
    "chair": (204, 255, 4), "stool": (204, 255, 4),
    "coffee_table": (255, 6, 82), "side_table": (255, 6, 82), "dining_table": (255, 6, 82),
    "table": (255, 6, 82), "desk": (214, 255, 8),
    "tv_unit": (255, 163, 0), "tv": (0, 163, 255),
    "bed": (204, 5, 255), "bunk_bed": (204, 5, 255),
    "wardrobe": (0, 41, 255), "bookshelf": (235, 12, 255), "shelf": (235, 12, 255),
    "cabinet": (224, 5, 255), "dresser": (255, 173, 0), "nightstand": (255, 220, 0),
    "plant": (4, 250, 7), "lamp": (255, 5, 153), "floor_lamp": (255, 5, 153),
    "rug": (150, 150, 150), "carpet": (150, 150, 150),
    "default": (200, 200, 200),
}


def _seg_color(ftype: str) -> tuple[int, int, int]:
    return _SEG_COLORS.get((ftype or "").lower(), _SEG_COLORS["default"])


# Plausible material tones per class — for the img2img BASE image (a believable
# coloured 3D block-out that low-denoise img2img refines into a real render while
# furniture positions stay locked). Unlike the garish seg colours, these read as real
# materials, so low strength keeps a sensible interior instead of neon blocks.
_MATERIAL_COLORS: dict[str, tuple[int, int, int]] = {
    "wall": (236, 232, 226), "floor": (198, 168, 128), "ceiling": (245, 243, 240),
    "sofa": (176, 170, 160), "loveseat": (176, 170, 160), "armchair": (166, 160, 150),
    "chair": (150, 138, 118), "stool": (150, 138, 118),
    "coffee_table": (150, 110, 72), "side_table": (150, 110, 72),
    "dining_table": (150, 110, 72), "table": (150, 110, 72), "desk": (150, 110, 72),
    "tv_unit": (120, 86, 56), "tv": (32, 32, 36),
    "bed": (224, 214, 194), "bunk_bed": (200, 180, 150),
    "wardrobe": (172, 142, 112), "bookshelf": (160, 130, 100), "shelf": (160, 130, 100),
    "cabinet": (172, 142, 112), "dresser": (172, 142, 112), "nightstand": (182, 152, 122),
    "plant": (72, 120, 60), "lamp": (214, 202, 180), "floor_lamp": (214, 202, 180),
    "rug": (212, 206, 196), "carpet": (212, 206, 196),
    "default": (182, 176, 166),
}


def _material_color(ftype: str) -> tuple[int, int, int]:
    return _MATERIAL_COLORS.get((ftype or "").lower(), _MATERIAL_COLORS["default"])


def _build_colored_scene(
    placements: list[dict[str, Any]],
    room_w: float,
    room_d: float,
    room_h: float,
    *,
    semantic_shapes: bool = True,
    palette: dict[str, tuple[int, int, int]] | None = None,
) -> list[tuple[np.ndarray, tuple[int, int, int]]]:
    """Like ``_build_scene`` but pairs every triangle with an RGB colour.

    ``palette`` maps furniture type → colour (defaults to the flat seg palette). Pass
    ``_MATERIAL_COLORS`` for a believable material block-out (img2img base image).
    """
    pal = palette or _SEG_COLORS
    W, D, H = room_w, room_d, room_h
    out: list[tuple[np.ndarray, tuple[int, int, int]]] = []

    def _color_of(ftype: str) -> tuple[int, int, int]:
        return pal.get((ftype or "").lower(), pal["default"])

    def _add(faces: list[np.ndarray], color: tuple[int, int, int]) -> None:
        for tri in faces:
            out.append((tri, color))

    # Room shell
    _add(_quad([0, 0, 0], [W, 0, 0], [W, 0, D], [0, 0, D]), pal["floor"])
    _add(_quad([0, H, 0], [W, H, 0], [W, H, D], [0, H, D]), pal["ceiling"])
    _add(_quad([0, 0, D], [W, 0, D], [W, H, D], [0, H, D]), pal["wall"])
    _add(_quad([0, 0, 0], [0, 0, D], [0, H, D], [0, H, 0]), pal["wall"])
    _add(_quad([W, 0, 0], [W, 0, D], [W, H, D], [W, H, 0]), pal["wall"])

    for item in placements:
        try:
            x = float(item.get("x", 0.0)); y = float(item.get("y", 0.0))
            w = float(item.get("w", 0.0)); h = float(item.get("h", 0.0))
        except (TypeError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        ftype = str(item.get("type", "default"))
        color = _color_of(ftype)
        height = _furniture_height(ftype)
        x0 = max(0.0, x) * W
        x1 = min(1.0, x + w) * W
        z_near = (1.0 - min(1.0, y + h)) * D
        z_far = (1.0 - max(0.0, y)) * D
        if x1 <= x0 or z_far <= z_near:
            continue

        if semantic_shapes and height >= 0.10:
            kind = _shape_kind(ftype)
            back = _nearest_wall(x0, x1, z_near, z_far, W, D)
            for bx0, bx1, bz0, bz1, by0, by1 in _furniture_parts(
                kind, x0, x1, z_near, z_far, height, back
            ):
                if bx1 > bx0 and bz1 > bz0 and by1 > by0:
                    _add(_box_faces(bx0, bx1, bz0, bz1, by0, by1), color)
        else:
            _add(_box_faces(x0, x1, z_near, z_far, 0.0, height), color)

    return out


def _rasterize_color(
    colored_tris: list[tuple[np.ndarray, tuple[int, int, int]]],
    cam: _Camera,
    *,
    shade: bool = False,
) -> np.ndarray:
    """Z-buffer rasterize colored triangles → an (H, W, 3) uint8 image.

    ``shade``: modulate each triangle's colour by a cheap per-face brightness (facing
    the camera = brighter) so the block-out reads as 3D volumes — helps img2img infer
    real geometry. Off = flat colours (segmentation-style map).
    """
    NEAR = 0.05
    H, W = cam.img_h, cam.img_w
    zbuf = np.full((H, W), np.inf, dtype=np.float64)
    rgb = np.zeros((H, W, 3), dtype=np.uint8)
    light = np.array([0.3, 0.85, -0.45])
    light = light / np.linalg.norm(light)

    for verts, color in colored_tris:
        cp = cam.to_cam(verts)
        zc = cp[:, 2]
        if np.any(zc <= NEAR):
            continue
        draw_color = color
        if shade:
            n = np.cross(verts[1] - verts[0], verts[2] - verts[0])
            nn = np.linalg.norm(n)
            if nn > 1e-9:
                b = 0.62 + 0.38 * abs(float(np.dot(n / nn, light)))
                draw_color = tuple(int(min(255, c * b)) for c in color)
        sx = cam.cx + cam.f * cp[:, 0] / zc
        sy = cam.cy - cam.f * cp[:, 1] / zc
        minx = max(int(math.floor(sx.min())), 0)
        maxx = min(int(math.ceil(sx.max())), W - 1)
        miny = max(int(math.floor(sy.min())), 0)
        maxy = min(int(math.ceil(sy.max())), H - 1)
        if minx > maxx or miny > maxy:
            continue
        x0, y0 = sx[0], sy[0]; x1, y1 = sx[1], sy[1]; x2, y2 = sx[2], sy[2]
        denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(denom) < 1e-9:
            continue
        gx, gy = np.meshgrid(
            np.arange(minx, maxx + 1, dtype=np.float64),
            np.arange(miny, maxy + 1, dtype=np.float64),
        )
        gxf = gx + 0.5; gyf = gy + 0.5
        l0 = ((y1 - y2) * (gxf - x2) + (x2 - x1) * (gyf - y2)) / denom
        l1 = ((y2 - y0) * (gxf - x2) + (x0 - x2) * (gyf - y2)) / denom
        l2 = 1.0 - l0 - l1
        inside = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
        if not inside.any():
            continue
        inv_z = l0 * (1.0 / zc[0]) + l1 * (1.0 / zc[1]) + l2 * (1.0 / zc[2])
        inv_z[~inside] = 0.0
        with np.errstate(divide="ignore", invalid="ignore"):
            zpix = np.where(inv_z > 0, 1.0 / inv_z, np.inf)
        sub_z = zbuf[miny:maxy + 1, minx:maxx + 1]
        upd = inside & (zpix < sub_z)
        sub_z[upd] = zpix[upd]
        zbuf[miny:maxy + 1, minx:maxx + 1] = sub_z
        sub_rgb = rgb[miny:maxy + 1, minx:maxx + 1]
        sub_rgb[upd] = draw_color
        rgb[miny:maxy + 1, minx:maxx + 1] = sub_rgb

    return rgb


def render_layout_base_image(
    furniture_placements: list[dict[str, Any]],
    task_id: str,
    *,
    room_w: float = 4.0,
    room_d: float = 4.0,
    room_h: float = _DEFAULT_ROOM_HEIGHT,
    img_w: int = 1024,
    img_h: int = 1024,
    semantic_shapes: bool = True,
    cam_kwargs: dict | None = None,
    out_dir: Path | None = None,
) -> str | None:
    """Render a believable, shaded, material-coloured 3D block-out of the layout.

    Intended as the INIT image for low-denoise img2img: furniture sits at exact plan
    positions in plausible material tones, so the render keeps coordinates locked while
    img2img only adds texture, lighting and detail. Returns the PNG path.
    """
    if not furniture_placements:
        return None
    try:
        from PIL import Image

        room_w = float(room_w) if room_w and room_w > 0 else 4.0
        room_d = float(room_d) if room_d and room_d > 0 else 4.0
        room_h = float(room_h) if room_h and room_h > 0 else _DEFAULT_ROOM_HEIGHT
        img_w = max(256, int(img_w)); img_h = max(256, int(img_h))

        cam = _Camera(room_w, room_d, img_w, img_h, **(cam_kwargs or {}))
        colored = _build_colored_scene(
            furniture_placements, room_w, room_d, room_h,
            semantic_shapes=semantic_shapes, palette=_MATERIAL_COLORS,
        )
        rgb = _rasterize_color(colored, cam, shade=True)

        base = out_dir or (Path(Config.ARTIFACTS_DIR) / "layout")
        base.mkdir(parents=True, exist_ok=True)
        out = base / f"{task_id}_layout_base.png"
        Image.fromarray(rgb, mode="RGB").save(str(out))
        print(
            f"[layout_projection] eye-level material block-out: {out.name} "
            f"({img_w}x{img_h}, {len(furniture_placements)} items)"
        )
        return str(out)
    except Exception as e:  # pragma: no cover - defensive
        import traceback
        print(f"⚠️  layout base-image projection failed: {e}")
        traceback.print_exc()
        return None


def render_layout_segmentation_map(
    furniture_placements: list[dict[str, Any]],
    task_id: str,
    *,
    room_w: float = 4.0,
    room_d: float = 4.0,
    room_h: float = _DEFAULT_ROOM_HEIGHT,
    img_w: int = 1024,
    img_h: int = 1024,
    semantic_shapes: bool = True,
    cam_kwargs: dict | None = None,
    out_dir: Path | None = None,
) -> str | None:
    """Render an eye-level flat per-object region (segmentation-style) map.

    Each furniture piece fills its silhouette with one solid semantic colour, so the
    model gets an explicit "this whole region is a <class>" prior — a stronger spatial
    signal for precise placement than the grey depth blob alone. Returns the PNG path.
    """
    if not furniture_placements:
        return None
    try:
        from PIL import Image

        room_w = float(room_w) if room_w and room_w > 0 else 4.0
        room_d = float(room_d) if room_d and room_d > 0 else 4.0
        room_h = float(room_h) if room_h and room_h > 0 else _DEFAULT_ROOM_HEIGHT
        img_w = max(256, int(img_w)); img_h = max(256, int(img_h))

        cam = _Camera(room_w, room_d, img_w, img_h, **(cam_kwargs or {}))
        colored = _build_colored_scene(
            furniture_placements, room_w, room_d, room_h, semantic_shapes=semantic_shapes
        )
        rgb = _rasterize_color(colored, cam)

        base = out_dir or (Path(Config.ARTIFACTS_DIR) / "layout")
        base.mkdir(parents=True, exist_ok=True)
        out = base / f"{task_id}_layout_seg.png"
        Image.fromarray(rgb, mode="RGB").save(str(out))
        print(
            f"[layout_projection] eye-level region map: {out.name} "
            f"({img_w}x{img_h}, {len(furniture_placements)} items)"
        )
        return str(out)
    except Exception as e:  # pragma: no cover - defensive
        import traceback
        print(f"⚠️  layout segmentation projection failed: {e}")
        traceback.print_exc()
        return None


def _rasterize(tris: list[np.ndarray], cam: _Camera) -> np.ndarray:
    """Z-buffer rasterize triangles, returning per-pixel camera-space depth (view z)."""
    NEAR = 0.05
    H, W = cam.img_h, cam.img_w
    zbuf = np.full((H, W), np.inf, dtype=np.float64)

    for verts in tris:
        cp = cam.to_cam(verts)  # (3,3) camera space
        zc = cp[:, 2]
        # Skip triangles crossing/behind the near plane (keeps projection well-defined).
        if np.any(zc <= NEAR):
            continue
        sx = cam.cx + cam.f * cp[:, 0] / zc
        sy = cam.cy - cam.f * cp[:, 1] / zc

        minx = max(int(math.floor(sx.min())), 0)
        maxx = min(int(math.ceil(sx.max())), W - 1)
        miny = max(int(math.floor(sy.min())), 0)
        maxy = min(int(math.ceil(sy.max())), H - 1)
        if minx > maxx or miny > maxy:
            continue

        x0, y0 = sx[0], sy[0]
        x1, y1 = sx[1], sy[1]
        x2, y2 = sx[2], sy[2]
        denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(denom) < 1e-9:
            continue

        gx, gy = np.meshgrid(
            np.arange(minx, maxx + 1, dtype=np.float64),
            np.arange(miny, maxy + 1, dtype=np.float64),
        )
        gxf = gx + 0.5
        gyf = gy + 0.5
        l0 = ((y1 - y2) * (gxf - x2) + (x2 - x1) * (gyf - y2)) / denom
        l1 = ((y2 - y0) * (gxf - x2) + (x0 - x2) * (gyf - y2)) / denom
        l2 = 1.0 - l0 - l1
        inside = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
        if not inside.any():
            continue

        # Perspective-correct depth: 1/z is linear in screen space.
        inv_z = l0 * (1.0 / zc[0]) + l1 * (1.0 / zc[1]) + l2 * (1.0 / zc[2])
        inv_z[~inside] = 0.0
        with np.errstate(divide="ignore", invalid="ignore"):
            zpix = np.where(inv_z > 0, 1.0 / inv_z, np.inf)

        sub = zbuf[miny : maxy + 1, minx : maxx + 1]
        upd = inside & (zpix < sub)
        sub[upd] = zpix[upd]
        zbuf[miny : maxy + 1, minx : maxx + 1] = sub

    return zbuf


def _depth_to_gray(zbuf: np.ndarray, cam: _Camera) -> np.ndarray:
    """Map view-space depth to an 8-bit map (near = bright, far = dark).

    Normalized by the scene's actual depth range — matching MiDaS/``vision.py`` —
    so the full 0..255 range is used and the ControlNet sees maximal contrast.
    """
    finite = np.isfinite(zbuf)
    if not finite.any():
        return np.zeros(zbuf.shape, dtype=np.uint8)
    z = zbuf[finite]
    z_near, z_far = float(z.min()), float(z.max())
    gray = np.zeros(zbuf.shape, dtype=np.float64)
    if z_far - z_near < 1e-6:
        gray[finite] = 255.0
    else:
        gray[finite] = 255.0 * (z_far - zbuf[finite]) / (z_far - z_near)
    out = gray.astype(np.uint8)
    out[~finite] = 0  # background -> far/black (room shell normally fills the frame)
    return out


def render_layout_depth_map(
    furniture_placements: list[dict[str, Any]],
    task_id: str,
    *,
    room_w: float = 4.0,
    room_d: float = 4.0,
    room_h: float = _DEFAULT_ROOM_HEIGHT,
    img_w: int = 1024,
    img_h: int = 1024,
    semantic_shapes: bool = True,
    cam_kwargs: dict | None = None,
    out_dir: Path | None = None,
) -> str | None:
    """Render an eye-level perspective depth map from a top-down furniture layout.

    ``semantic_shapes``: draw furniture as rough category silhouettes (platform +
    headboard for a bed, seat + backrest + arms for a sofa, top + legs for a table)
    instead of plain cuboids, so the model can read the furniture type off the shape.

    Returns the PNG path, or ``None`` if there is nothing to render or it fails.
    """
    if not furniture_placements:
        return None
    try:
        from PIL import Image

        room_w = float(room_w) if room_w and room_w > 0 else 4.0
        room_d = float(room_d) if room_d and room_d > 0 else 4.0
        room_h = float(room_h) if room_h and room_h > 0 else _DEFAULT_ROOM_HEIGHT
        img_w = max(256, int(img_w))
        img_h = max(256, int(img_h))

        cam = _Camera(room_w, room_d, img_w, img_h, **(cam_kwargs or {}))
        tris = _build_scene(
            furniture_placements, room_w, room_d, room_h, semantic_shapes=semantic_shapes
        )
        zbuf = _rasterize(tris, cam)
        gray = _depth_to_gray(zbuf, cam)

        base = out_dir or (Path(Config.ARTIFACTS_DIR) / "layout")
        base.mkdir(parents=True, exist_ok=True)
        out = base / f"{task_id}_layout_depth.png"
        Image.fromarray(gray, mode="L").save(str(out))
        print(
            f"[layout_projection] eye-level depth map: {out.name} "
            f"({img_w}x{img_h}, {len(furniture_placements)} items, room {room_w:.1f}x{room_d:.1f}m)"
        )
        return str(out)
    except Exception as e:  # pragma: no cover - defensive; renderer falls back
        import traceback

        print(f"⚠️  layout depth projection failed: {e}")
        traceback.print_exc()
        return None


def _box_corners(x0, x1, z0, z1, y0, y1) -> np.ndarray:
    """8 corners of an axis-aligned box, ordered (x,y,z)."""
    return np.array(
        [[cx, cy, cz] for cx in (x0, x1) for cy in (y0, y1) for cz in (z0, z1)],
        dtype=np.float64,
    )


# Edge index pairs into the 8-corner ordering above (bottom + top + verticals).
_BOX_EDGES = [
    (0, 1), (2, 3), (4, 5), (6, 7),  # y-direction
    (0, 2), (1, 3), (4, 6), (5, 7),  # z-direction
    (0, 4), (1, 5), (2, 6), (3, 7),  # x-direction
]


def render_layout_edge_map(
    furniture_placements: list[dict[str, Any]],
    task_id: str,
    *,
    room_w: float = 4.0,
    room_d: float = 4.0,
    room_h: float = _DEFAULT_ROOM_HEIGHT,
    img_w: int = 1024,
    img_h: int = 1024,
    footprints_only: bool = False,
    cam_kwargs: dict | None = None,
    out_dir: Path | None = None,
) -> str | None:
    """Render an eye-level Canny-style edge map (white wireframes on black) from a
    top-down furniture layout.

    Unlike depth, edges do NOT fade with distance, so back-wall furniture stays a
    crisp outline — giving the ControlNet a distance-independent positional signal.

    ``footprints_only``: draw each item only as its floor-footprint rectangle (no
    vertical box). This marks *where* every piece sits without imposing a cuboid
    silhouette, so the model renders realistic furniture (not boxes) and flat items
    like rugs are represented naturally.

    Returns the PNG path, or ``None``.
    """
    if not furniture_placements:
        return None
    try:
        from PIL import Image, ImageDraw

        room_w = float(room_w) if room_w and room_w > 0 else 4.0
        room_d = float(room_d) if room_d and room_d > 0 else 4.0
        room_h = float(room_h) if room_h and room_h > 0 else _DEFAULT_ROOM_HEIGHT
        img_w = max(256, int(img_w))
        img_h = max(256, int(img_h))

        cam = _Camera(room_w, room_d, img_w, img_h, **(cam_kwargs or {}))
        NEAR = 0.05
        W, D, H = room_w, room_d, room_h

        # Depth buffer of the solid scene → used for hidden-line removal so we only
        # draw the VISIBLE silhouette of each box (not see-through wireframes, which
        # otherwise make the model render translucent glass boxes). In footprints_only
        # mode there are no tall boxes, so occlude against the room shell only.
        _zbuf_items = [] if footprints_only else furniture_placements
        zbuf = _rasterize(_build_scene(_zbuf_items, W, D, H), cam)

        img = Image.new("L", (img_w, img_h), 0)
        draw = ImageDraw.Draw(img)

        def project(pts: np.ndarray) -> np.ndarray:
            cp = cam.to_cam(pts)
            sx = cam.cx + cam.f * cp[:, 0] / cp[:, 2]
            sy = cam.cy - cam.f * cp[:, 1] / cp[:, 2]
            return np.stack([sx, sy, cp[:, 2]], axis=1)

        def draw_edges(corners: np.ndarray, edges, width: int, hidden_line: bool):
            sc = project(corners)
            for a, b in edges:
                za, zb = sc[a, 2], sc[b, 2]
                if za <= NEAR or zb <= NEAR:
                    continue
                if not hidden_line:
                    draw.line([(sc[a, 0], sc[a, 1]), (sc[b, 0], sc[b, 1])], fill=255, width=width)
                    continue
                # Sample the edge; keep only points that are the frontmost surface
                # (their depth ≈ z-buffer at that pixel, within tolerance).
                n = 48
                ts = np.linspace(0.0, 1.0, n)
                pts = sc[a, :2][None, :] * (1 - ts)[:, None] + sc[b, :2][None, :] * ts[:, None]
                zs = za * (1 - ts) + zb * ts
                prev = None
                for (px, py), z in zip(pts, zs):
                    ix, iy = int(round(px)), int(round(py))
                    vis = False
                    if 0 <= ix < img_w and 0 <= iy < img_h:
                        zb_pix = zbuf[iy, ix]
                        vis = (not np.isfinite(zb_pix)) or (z <= zb_pix + 0.06)
                    if vis and prev is not None:
                        draw.line([prev, (px, py)], fill=255, width=width)
                    prev = (px, py) if vis else None

        # Room shell wireframe (walls/floor/ceiling boundaries) — thin, always drawn.
        draw_edges(_box_corners(0, W, 0, D, 0, H), _BOX_EDGES, width=2, hidden_line=False)

        # Furniture — visible silhouette only, thicker so it reads as the structure.
        for item in furniture_placements:
            try:
                x = float(item.get("x", 0.0)); y = float(item.get("y", 0.0))
                w = float(item.get("w", 0.0)); h = float(item.get("h", 0.0))
            except (TypeError, ValueError):
                continue
            if w <= 0 or h <= 0:
                continue
            height = _furniture_height(str(item.get("type", "default")))
            x0 = max(0.0, x) * W
            x1 = min(1.0, x + w) * W
            z0 = (1.0 - min(1.0, y + h)) * D
            z1 = (1.0 - max(0.0, y)) * D
            if x1 <= x0 or z1 <= z0:
                continue
            if footprints_only or height < 0.10:
                # Floor-footprint rectangle only — marks position/extent without a
                # cuboid silhouette (also the natural representation for flat rugs).
                corners = _box_corners(x0, x1, z0, z1, 0.0, 0.0)
                draw_edges(corners, [(0, 4), (4, 5), (5, 1), (1, 0)], width=3, hidden_line=True)
            elif _shape_kind(str(item.get("type", "default"))) == "slim":
                # Slender decor (plant/lamp): a narrow central pole, not a wide box.
                dx, dz = x1 - x0, z1 - z0
                cx0, cx1 = x0 + dx * (1 - _SLIM_FRAC) / 2, x1 - dx * (1 - _SLIM_FRAC) / 2
                cz0, cz1 = z0 + dz * (1 - _SLIM_FRAC) / 2, z1 - dz * (1 - _SLIM_FRAC) / 2
                draw_edges(_box_corners(cx0, cx1, cz0, cz1, 0.0, height), _BOX_EDGES, width=3, hidden_line=True)
            else:
                draw_edges(_box_corners(x0, x1, z0, z1, 0.0, height), _BOX_EDGES, width=3, hidden_line=True)

        base = out_dir or (Path(Config.ARTIFACTS_DIR) / "layout")
        base.mkdir(parents=True, exist_ok=True)
        out = base / f"{task_id}_layout_edges.png"
        img.save(str(out))
        print(
            f"[layout_projection] eye-level edge map: {out.name} "
            f"({img_w}x{img_h}, {len(furniture_placements)} items)"
        )
        return str(out)
    except Exception as e:  # pragma: no cover - defensive
        import traceback

        print(f"⚠️  layout edge projection failed: {e}")
        traceback.print_exc()
        return None
