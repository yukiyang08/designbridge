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

The camera stands near the entrance at eye height, looking toward the back wall —
the same viewpoint the spatial prompt describes. Camera, rasterizer and furniture
silhouette decomposition are shared with ``scene_graph_to_depth.py`` via
``camera_projection.py`` so both projection paths produce geometrically consistent
results instead of two independently tuned viewpoints. When no explicit camera is
given, a handful of candidate station points are scored by furniture occlusion and
the best one is picked automatically (see ``camera_projection.select_best_camera``).

Depth encoding follows the MiDaS convention used elsewhere in the pipeline
(``vision.run_depth_estimation``): near = bright (255), far = dark (0).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from designbridge.core.config import Config
from designbridge.layout.camera_projection import (
    CameraParams,
    LookAtCamera,
    build_tagged_scene,
    depth_to_gray,
    furniture_height,
    nearest_wall_world,
    rasterize_ids,
    select_best_camera,
)

_DEFAULT_ROOM_HEIGHT = 2.70


def _furniture_height(ftype: str) -> float:
    return furniture_height(ftype)


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


def _base_camera_params(cam_kwargs: dict | None) -> CameraParams:
    base = CameraParams(
        eye_height=Config.LAYOUT_CAM_EYE_H,
        setback=Config.LAYOUT_CAM_SETBACK,
        target_h=Config.LAYOUT_CAM_TARGET_H,
        target_depth_frac=Config.LAYOUT_CAM_TARGET_DEPTH_FRAC,
        fov_v_deg=Config.LAYOUT_CAM_FOV,
    )
    return replace(base, **cam_kwargs) if cam_kwargs else base


def _resolve_camera(
    room_w: float, room_d: float, img_w: int, img_h: int,
    furniture_placements: list[dict[str, Any]],
    *, semantic_shapes: bool, cam_kwargs: dict | None,
) -> LookAtCamera:
    """Build the camera to render with.

    If the caller already pinned ``cam_kwargs`` to a concrete pose (as
    ``renderer.py`` does, so depth/edge/base/seg stay geometrically consistent
    for one render job), use it directly — no rescoring. Otherwise run the same
    occlusion-based candidate selection ``scene_graph_to_depth`` uses.
    """
    base = _base_camera_params(cam_kwargs)
    if cam_kwargs or not Config.LAYOUT_CAMERA_AUTO_SELECT:
        return LookAtCamera(room_w, room_d, img_w, img_h, base)
    chosen, picked = select_best_camera(
        base, room_w, room_d, _DEFAULT_ROOM_HEIGHT, img_w, img_h,
        furniture_placements, semantic_shapes=semantic_shapes,
        candidates=Config.LAYOUT_CAMERA_CANDIDATES,
    )
    if furniture_placements:
        print(
            f"[layout_projection] 候選角度評分選用相機："
            f"eye_height={chosen.eye_height:.2f} setback={chosen.setback:.2f} "
            f"target_h={chosen.target_h:.2f} target_depth_frac={chosen.target_depth_frac:.2f} "
            f"fov_v={chosen.fov_v_deg:.0f}°（分數 {picked['score']:.3f}）"
        )
    return picked["cam"]


# ── Semantic region (segmentation-style) colours ───────────────────────────────
# Distinct, roughly ADE20K-aligned colours per furniture class. Used to render a
# flat per-object region map: each piece fills its footprint with ONE solid colour,
# giving the model an explicit "this whole area = a sofa" signal — a stronger spatial
# prior than a grey depth blob. Room shell uses ADE wall/floor/ceiling colours.
_SEG_COLORS: dict[str, tuple[int, int, int]] = {
    "_wall": (120, 120, 120), "_floor": (80, 50, 50), "_ceiling": (120, 120, 80),
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

# Plausible material tones per class — for the img2img BASE image (a believable
# coloured 3D block-out that low-denoise img2img refines into a real render while
# furniture positions stay locked). Unlike the garish seg colours, these read as real
# materials, so low strength keeps a sensible interior instead of neon blocks.
_MATERIAL_COLORS: dict[str, tuple[int, int, int]] = {
    "_wall": (236, 232, 226), "_floor": (198, 168, 128), "_ceiling": (245, 243, 240),
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


def _color_of(ftype: str, palette: dict[str, tuple[int, int, int]]) -> tuple[int, int, int]:
    if ftype.startswith("_"):
        return palette.get(ftype, palette["default"])
    return palette.get((ftype or "").lower(), palette["default"])


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

        cam = _resolve_camera(
            room_w, room_d, img_w, img_h, furniture_placements,
            semantic_shapes=semantic_shapes, cam_kwargs=cam_kwargs,
        )
        tagged, _id_to_type = build_tagged_scene(
            furniture_placements, room_w, room_d, room_h, semantic_shapes=semantic_shapes,
        )
        zbuf, _idbuf = rasterize_ids(tagged, cam)
        gray = depth_to_gray(zbuf)

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
        img_w = max(256, int(img_w))
        img_h = max(256, int(img_h))

        cam = _resolve_camera(
            room_w, room_d, img_w, img_h, furniture_placements,
            semantic_shapes=semantic_shapes, cam_kwargs=cam_kwargs,
        )
        tagged, id_to_type = build_tagged_scene(
            furniture_placements, room_w, room_d, room_h, semantic_shapes=semantic_shapes,
        )
        _zbuf, idbuf = rasterize_ids(tagged, cam)
        rgb = np.zeros((img_h, img_w, 3), dtype=np.uint8)
        for oid, ftype in id_to_type.items():
            mask = idbuf == oid
            if mask.any():
                rgb[mask] = _color_of(ftype, _MATERIAL_COLORS)

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
        img_w = max(256, int(img_w))
        img_h = max(256, int(img_h))

        cam = _resolve_camera(
            room_w, room_d, img_w, img_h, furniture_placements,
            semantic_shapes=semantic_shapes, cam_kwargs=cam_kwargs,
        )
        tagged, id_to_type = build_tagged_scene(
            furniture_placements, room_w, room_d, room_h, semantic_shapes=semantic_shapes,
        )
        _zbuf, idbuf = rasterize_ids(tagged, cam)
        rgb = np.zeros((img_h, img_w, 3), dtype=np.uint8)
        for oid, ftype in id_to_type.items():
            mask = idbuf == oid
            if mask.any():
                rgb[mask] = _color_of(ftype, _SEG_COLORS)

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

        cam = _resolve_camera(
            room_w, room_d, img_w, img_h, furniture_placements,
            semantic_shapes=True, cam_kwargs=cam_kwargs,
        )
        NEAR = 0.05
        W, D, H = room_w, room_d, room_h

        # Depth buffer of the solid scene → used for hidden-line removal so we only
        # draw the VISIBLE silhouette of each box (not see-through wireframes, which
        # otherwise make the model render translucent glass boxes). In footprints_only
        # mode there are no tall boxes, so occlude against the room shell only.
        _zbuf_items = [] if footprints_only else furniture_placements
        tagged, _ = build_tagged_scene(_zbuf_items, W, D, H)
        zbuf, _idbuf = rasterize_ids(tagged, cam)

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
        # Drawn per decomposed part (seat/backrest, tabletop/legs, ...) rather than one
        # bounding box, so the wireframe itself hints the furniture category too.
        for item in furniture_placements:
            try:
                x = float(item.get("x", 0.0)); y = float(item.get("y", 0.0))
                w = float(item.get("w", 0.0)); h = float(item.get("h", 0.0))
            except (TypeError, ValueError):
                continue
            if w <= 0 or h <= 0:
                continue
            ftype = str(item.get("type", "default"))
            height = _furniture_height(ftype)
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
                continue

            from designbridge.layout.camera_projection import furniture_parts
            back = nearest_wall_world(x0, x1, z0, z1, W, D)
            parts = furniture_parts(ftype, x, y, w, h, height, back=back)
            for u0, u1, v0, v1, pz0, pz1 in parts:
                if pz1 <= pz0:
                    continue
                bx0, bx1 = x0 + u0 * (x1 - x0), x0 + u1 * (x1 - x0)
                bz0, bz1 = z1 - v1 * (z1 - z0), z1 - v0 * (z1 - z0)
                if bx1 <= bx0 or bz1 <= bz0:
                    continue
                draw_edges(
                    _box_corners(bx0, bx1, bz0, bz1, pz0, pz1), _BOX_EDGES,
                    width=3, hidden_line=True,
                )

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
