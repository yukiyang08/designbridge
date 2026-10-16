# designbridge/layout/camera_projection.py
"""Shared camera model, id-aware z-buffer rasterizer, furniture-silhouette
decomposition and furniture-type taxonomy for the two depth-projection paths
that used to each maintain their own, divergent copy:

  - ``scene_graph_to_depth.py``  (layout_and_style_agent / photo-anchored path)
  - ``layout_projection.py``     (renderer's no-photo text-to-design fallback)

Both now build on the same :class:`LookAtCamera` (a real 3-DOF look-at camera,
not a single-axis pitch) and the same furniture-part decomposition, so the two
call sites produce geometrically consistent results instead of two unrelated
fixed viewpoints.

On top of the shared camera this module adds occlusion-based camera selection:
``select_best_camera`` renders a handful of candidate eye positions/aim points
and picks the one where the least furniture is hidden behind other furniture,
instead of always using one hard-coded station point that may happen to be
blocked for a given layout.

World axes (metres): X = left->right, Y = up (floor = 0), Z = forward/depth
(0 = entrance/near wall, room_d = far wall).

Floor-plan axes (normalized [0,1], shared with layout_agent):
    x: 0 = left wall,  1 = right wall
    y: 0 = far wall,   1 = near/entrance wall
    (x, y) = top-left corner of the footprint; (w, h) = size.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

# ── Furniture type taxonomy (heights, synonyms, mount type) ─────────────────
# Moved here (from the former scene_graph_to_depth.py) because the shared shape
# decomposition below needs the same free-text-label normalization to classify
# "platform_bed" / "floor_lamp" / etc. correctly. Re-exported by
# scene_graph_to_depth.py so existing importers (layout_agent.py, api.py, ...)
# are unaffected.

FURNITURE_HEIGHTS: dict[str, float] = {
    "sofa": 0.85, "loveseat": 0.80, "coffee_table": 0.45, "tv_unit": 0.50,
    "tv": 0.70, "table": 0.75, "dining_table": 0.75, "chair": 0.90,
    "armchair": 0.95, "stool": 0.55, "bench": 0.45, "bed": 0.55,
    "bunk_bed": 1.70, "bunk_ladder": 1.55, "crib": 0.90, "daybed": 0.55,
    "wardrobe": 2.00, "desk": 0.75, "bookshelf": 1.80, "side_table": 0.55,
    "nightstand": 0.55, "console": 0.80, "lamp": 1.50, "floor_lamp": 1.60,
    "table_lamp": 0.55, "rug": 0.02, "plant": 1.20, "cabinet": 0.90,
    "dresser": 0.85, "shelf": 1.60, "cat_tree": 1.40, "dog_bed": 0.20,
    "litter_box": 0.30, "fridge": 1.80, "washing_machine": 0.85,
    "default": 0.80,
}

_TYPE_SYNONYMS: dict[str, str] = {
    "couch": "sofa",
    "sectional": "sofa",
    "closet": "wardrobe",
    "armoire": "wardrobe",
    "bedside_table": "nightstand",
    "night_table": "nightstand",
    "tv_stand": "tv_unit",
    "tv_console": "tv_unit",
    "media_console": "tv_unit",
    "sideboard": "cabinet",
    "credenza": "cabinet",
    "chest_of_drawers": "dresser",
    "carpet": "rug",
    "area_rug": "rug",
    "potted_plant": "plant",
    "floor_plant": "plant",
    "bookcase": "bookshelf",
    "work_desk": "desk",
    "study_desk": "desk",
    "standing_lamp": "floor_lamp",
    "vase": "plant",
}

# 從天花板吊掛或貼在牆上的物件沒有地板 footprint，不能當成從地板長上來的盒子。
_CEILING_MOUNTED: frozenset[str] = frozenset({
    "ceiling_lamp", "ceiling_light", "ceiling_fan", "pendant_light", "pendant_lamp",
    "chandelier", "track_light", "downlight", "spotlight", "skylight",
})
_WALL_MOUNTED: frozenset[str] = frozenset({
    "wall_lamp", "wall_light", "sconce", "wall_sconce", "wall_shelf", "wall_art",
    "wall_decor", "painting", "artwork", "mirror", "curtain", "curtains", "blind",
    "blinds", "wall_tv", "mounted_tv",
})


def normalize_furniture_type(ftype: str) -> str:
    """把自由文字的家具 type 收斂成 FURNITURE_HEIGHTS 的標準鍵。

    依序嘗試：完全比對 → 同義詞表 → 由左往右剝除修飾詞後的後綴比對
    （platform_bed → bed、low_cabinet → cabinet、wooden_side_table → side_table）。
    都對不上時回傳原字串，由呼叫端落到 default。
    """
    key = str(ftype or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not key:
        return "default"
    if key in FURNITURE_HEIGHTS or key in _CEILING_MOUNTED or key in _WALL_MOUNTED:
        return key
    if key in _TYPE_SYNONYMS:
        return _TYPE_SYNONYMS[key]

    tokens = [t for t in key.split("_") if t]
    for start in range(1, len(tokens)):
        suffix = "_".join(tokens[start:])
        if suffix in _CEILING_MOUNTED or suffix in _WALL_MOUNTED:
            return suffix
        if suffix in FURNITURE_HEIGHTS:
            return suffix
        if suffix in _TYPE_SYNONYMS:
            return _TYPE_SYNONYMS[suffix]
    return key


def is_floor_standing(ftype: str) -> bool:
    key = normalize_furniture_type(ftype)
    return key not in _CEILING_MOUNTED and key not in _WALL_MOUNTED


def furniture_height(ftype: str) -> float:
    return FURNITURE_HEIGHTS.get(normalize_furniture_type(ftype), FURNITURE_HEIGHTS["default"])


# ── Semantic furniture silhouettes (merged) ──────────────────────────────────
# Union of the two independently-written shape sets: "panel" (TV/monitor) only
# existed in the scene_graph_to_depth version; "slim" decor (plant/lamp) is
# handled here with the richer multi-part lamp/plant breakdown instead of a
# single central pole.

_SEATING: frozenset[str] = frozenset({
    "sofa", "loveseat", "armchair", "chair", "stool", "bench", "dog_bed",
})
_BEDS: frozenset[str] = frozenset({"bed", "bunk_bed", "crib", "daybed"})
_TABLES: frozenset[str] = frozenset({
    "table", "dining_table", "coffee_table", "desk", "side_table",
    "nightstand", "console",
})
_PANELS: frozenset[str] = frozenset({"tv", "monitor", "screen"})
_LAMPS: frozenset[str] = frozenset({"lamp", "floor_lamp", "table_lamp"})
_PLANTS: frozenset[str] = frozenset({"plant"})


def shape_kind(ftype: str) -> str:
    """家具 type -> 輪廓類別。未知者退回 'box'。"""
    t = normalize_furniture_type(ftype)
    if t in _SEATING:
        return "seat"
    if t in _BEDS:
        return "bed"
    if t in _TABLES:
        return "table"
    if t in _PANELS:
        return "panel"
    if t in _LAMPS:
        return "lamp"
    if t in _PLANTS:
        return "plant"
    return "box"


def back_edge_from_fraction(fx: float, fy: float, fw: float, fh: float) -> str:
    """Nearest wall from normalized footprint position alone (room-shape-agnostic).

    平面圖座標：x=0 左牆、x=1 右牆、y=0 遠牆、y=1 近相機側。
    """
    dists = {"far": fy, "near": 1.0 - (fy + fh), "left": fx, "right": 1.0 - (fx + fw)}
    return min(dists, key=dists.get)


def nearest_wall_world(x0: float, x1: float, z0: float, z1: float, room_w: float, room_d: float) -> str:
    """Nearest wall using real metres — correct for non-square rooms.

    World axes: x=0 left, x=room_w right, z=0 near/entrance, z=room_d far wall.
    """
    d_far, d_near, d_left, d_right = room_d - z1, z0, x0, room_w - x1
    m = min(d_far, d_near, d_left, d_right)
    if m == d_far:
        return "far"
    if m == d_near:
        return "near"
    if m == d_left:
        return "left"
    return "right"


def furniture_parts(
    ftype: str, fx: float, fy: float, fw: float, fh: float, height: float,
    *, back: str | None = None,
) -> list[tuple[float, float, float, float, float, float]]:
    """把一件家具拆成數個子塊，回傳 (u0,u1,v0,v1,z0,z1)。

    u/v 是 footprint 內的正規化座標（u 沿平面圖 +x，v 沿平面圖 +y，即 v=0 為遠側），
    z0/z1 是離地高度（公尺）。兩條投影路徑（合成相機、照片錨定、純文字 layout 相機）
    共用這份形狀知識，各自把 (u,v) 映射回自己的世界座標。

    ``back``：椅背/床頭板靠的那一側（far/near/left/right）。省略時用
    ``back_edge_from_fraction`` 從正規化 footprint 推算；呼叫端知道房間實際比例時可傳入
    ``nearest_wall_world`` 算出的結果，非正方形房間會更準。
    """
    kind = shape_kind(ftype)
    if kind == "box":
        return [(0.0, 1.0, 0.0, 1.0, 0.0, height)]

    if back is None:
        back = back_edge_from_fraction(fx, fy, fw, fh)

    def _slab(frac: float, z0: float, z1: float) -> tuple:
        if back == "far":
            return (0.0, 1.0, 0.0, frac, z0, z1)
        if back == "near":
            return (0.0, 1.0, 1.0 - frac, 1.0, z0, z1)
        if back == "left":
            return (0.0, frac, 0.0, 1.0, z0, z1)
        return (1.0 - frac, 1.0, 0.0, 1.0, z0, z1)  # right

    if kind == "seat":
        seat_h = min(0.45, height * 0.5)
        arm_h = min(height, seat_h + 0.18)
        parts = [
            (0.0, 1.0, 0.0, 1.0, 0.0, seat_h),   # 座墊
            _slab(0.22, seat_h, height),          # 椅背
        ]
        if back in ("far", "near"):
            parts += [(0.0, 0.14, 0.0, 1.0, 0.0, arm_h), (0.86, 1.0, 0.0, 1.0, 0.0, arm_h)]
        else:
            parts += [(0.0, 1.0, 0.0, 0.14, 0.0, arm_h), (0.0, 1.0, 0.86, 1.0, 0.0, arm_h)]
        return parts

    if kind == "bed":
        mattress_h = min(0.45, height * 0.7)
        headboard_h = max(height, mattress_h + 0.35)
        return [
            (0.0, 1.0, 0.0, 1.0, 0.0, mattress_h),   # 床墊
            _slab(0.10, 0.0, headboard_h),            # 床頭板
        ]

    if kind == "table":
        top_th = max(0.03, min(0.06, height * 0.15))
        leg_top = max(0.0, height - top_th)
        return [
            (0.0, 1.0, 0.0, 1.0, leg_top, height),   # 桌面
            (0.0, 0.10, 0.0, 0.10, 0.0, leg_top),
            (0.90, 1.0, 0.0, 0.10, 0.0, leg_top),
            (0.0, 0.10, 0.90, 1.0, 0.0, leg_top),
            (0.90, 1.0, 0.90, 1.0, 0.0, leg_top),
        ]

    if kind == "panel":
        return [_slab(0.12, height * 0.45, height)]

    if kind == "lamp":
        base_h = height * 0.04
        pole_top = height * 0.80
        return [
            (0.36, 0.64, 0.36, 0.64, 0.0, base_h),
            (0.44, 0.56, 0.44, 0.56, base_h, pole_top),
            (0.10, 0.90, 0.10, 0.90, pole_top, height),
        ]

    if kind == "plant":
        pot_top = height * 0.22
        stem_top = height * 0.50
        return [
            (0.22, 0.78, 0.22, 0.78, 0.0, pot_top),
            (0.44, 0.56, 0.44, 0.56, pot_top, stem_top),
            (0.0, 1.0, 0.0, 1.0, stem_top, height),
        ]

    return [(0.0, 1.0, 0.0, 1.0, 0.0, height)]


# ── Camera ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CameraParams:
    """The one shared camera parameterization both projection paths now use."""

    eye_height: float = 1.35
    setback: float = 0.6
    target_h: float = 1.1
    target_depth_frac: float = 0.6
    fov_v_deg: float = 60.0


class LookAtCamera:
    """Pinhole camera at (room_w/2, eye_height, -setback), aimed at a point
    inside the room. A true 3-DOF look-at camera (position + target + up)
    rather than a single-axis pitch, so it stays correctly framed at any
    elevation/setback.
    """

    def __init__(self, room_w: float, room_d: float, img_w: int, img_h: int, params: CameraParams) -> None:
        self.img_w = img_w
        self.img_h = img_h
        self.cx = img_w / 2.0
        self.cy = img_h / 2.0
        self.params = params
        # Focal length from the *vertical* FOV; horizontal FOV then follows the
        # image aspect ratio automatically.
        self.f = (img_h / 2.0) / math.tan(math.radians(params.fov_v_deg) / 2.0)
        self.eye = np.array(
            [room_w / 2.0, params.eye_height, -float(params.setback)], dtype=np.float64
        )
        self.room_d = room_d

        target = np.array(
            [room_w / 2.0, float(params.target_h), float(params.target_depth_frac) * room_d],
            dtype=np.float64,
        )
        fwd = target - self.eye
        fwd = fwd / (np.linalg.norm(fwd) + 1e-9)
        world_up = np.array([0.0, 1.0, 0.0])
        # right = world_up x fwd, not fwd x up: the latter yields -X, making R a
        # reflection (det -1) instead of a rotation, silently mirroring left/right.
        right = np.cross(world_up, fwd)
        right = right / (np.linalg.norm(right) + 1e-9)
        up = np.cross(fwd, right)
        self.R = np.stack([right, up, fwd])  # rows [right, up, forward]

    def to_cam(self, pts: np.ndarray) -> np.ndarray:
        """World points (N,3) -> camera space (N,3)."""
        return (self.R @ (pts - self.eye).T).T


def _quad(a, b, c, d) -> list[np.ndarray]:
    a, b, c, d = (np.array(v, dtype=np.float64) for v in (a, b, c, d))
    return [np.stack([a, b, c]), np.stack([a, c, d])]


def box_faces(x0, x1, z0, z1, y0, y1) -> list[np.ndarray]:
    """5 visible faces of an axis-aligned box (bottom face omitted)."""
    faces: list[np.ndarray] = []
    faces += _quad([x0, y1, z0], [x1, y1, z0], [x1, y1, z1], [x0, y1, z1])  # top
    faces += _quad([x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0])  # near
    faces += _quad([x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1])  # far
    faces += _quad([x0, y0, z0], [x0, y0, z1], [x0, y1, z1], [x0, y1, z0])  # left
    faces += _quad([x1, y0, z0], [x1, y0, z1], [x1, y1, z1], [x1, y1, z0])  # right
    return faces


# ── Geometry assembly (id-aware) ─────────────────────────────────────────────

def fp_to_world_box(item: dict, room_w: float, room_d: float) -> tuple[float, float, float, float, float]:
    """floor-plan bbox -> world (x0,x1,z_near,z_far,top_height)."""
    fx = float(item.get("x", 0.0))
    fy = float(item.get("y", 0.0))
    fw = float(item.get("w", 0.1))
    fh = float(item.get("h", 0.1))
    ftype = str(item.get("type", "default"))

    x0 = max(0.0, fx) * room_w
    x1 = min(1.0, fx + fw) * room_w
    z_near = (1.0 - min(1.0, fy + fh)) * room_d
    z_far = (1.0 - max(0.0, fy)) * room_d
    return x0, x1, z_near, z_far, furniture_height(ftype)


def build_tagged_scene(
    placements: list[dict[str, Any]],
    room_w: float,
    room_d: float,
    room_h: float,
    *,
    semantic_shapes: bool = True,
    start_id: int = 4,
) -> tuple[list[tuple[np.ndarray, int]], dict[int, str]]:
    """Assemble room-shell + furniture triangles, each tagged with an object id.

    Shell ids are fixed (1=floor, 2=ceiling, 3=wall); furniture gets one id per
    item starting at ``start_id``, shared across all of that item's sub-parts so
    it still reads as a single instance in the id map.
    """
    W, D, H = room_w, room_d, room_h
    tagged: list[tuple[np.ndarray, int]] = []
    id_to_type: dict[int, str] = {1: "_floor", 2: "_ceiling", 3: "_wall"}

    def _add(faces: list[np.ndarray], oid: int) -> None:
        for tri in faces:
            tagged.append((tri, oid))

    _add(_quad([0, 0, 0], [W, 0, 0], [W, 0, D], [0, 0, D]), 1)  # floor
    _add(_quad([0, H, 0], [W, H, 0], [W, H, D], [0, H, D]), 2)  # ceiling
    _add(_quad([0, 0, D], [W, 0, D], [W, H, D], [0, H, D]), 3)  # far wall
    _add(_quad([0, 0, 0], [0, 0, D], [0, H, D], [0, H, 0]), 3)  # left wall
    _add(_quad([W, 0, 0], [W, 0, D], [W, H, D], [W, H, 0]), 3)  # right wall

    next_id = start_id
    for item in placements or []:
        ftype = str(item.get("type", "default"))
        if not is_floor_standing(ftype):
            continue
        try:
            fx = float(item.get("x", 0.0))
            fy = float(item.get("y", 0.0))
            fw = float(item.get("w", 0.1))
            fh = float(item.get("h", 0.1))
        except (TypeError, ValueError):
            continue
        if fw <= 0 or fh <= 0:
            continue
        x0, x1, z_near, z_far, height = fp_to_world_box(item, room_w, room_d)
        if x1 <= x0 or z_far <= z_near:
            continue

        obj_id = next_id
        next_id += 1
        id_to_type[obj_id] = ftype

        if semantic_shapes and height >= 0.10:
            back = nearest_wall_world(x0, x1, z_near, z_far, room_w, room_d)
            parts = furniture_parts(ftype, fx, fy, fw, fh, height, back=back)
        else:
            parts = [(0.0, 1.0, 0.0, 1.0, 0.0, height)]

        for u0, u1, v0, v1, pz0, pz1 in parts:
            if pz1 <= pz0:
                continue
            bx0 = x0 + u0 * (x1 - x0)
            bx1 = x0 + u1 * (x1 - x0)
            # v=0 is the far side of the footprint -> larger world z.
            bz0 = z_far - v1 * (z_far - z_near)
            bz1 = z_far - v0 * (z_far - z_near)
            if bx1 > bx0 and bz1 > bz0:
                _add(box_faces(bx0, bx1, bz0, bz1, pz0, pz1), obj_id)

    return tagged, id_to_type


def instance_summary(idbuf: np.ndarray, id_to_type: dict[int, str]) -> list[dict[str, Any]]:
    """每件家具在投影影像上實際佔到的位置，正規化到 [0,1]（左上為原點）。"""
    h_img, w_img = idbuf.shape
    out: list[dict[str, Any]] = []
    for oid, ftype in id_to_type.items():
        if ftype.startswith("_"):
            continue
        ys, xs = np.nonzero(idbuf == oid)
        if xs.size == 0:
            out.append({"id": int(oid), "type": ftype, "visible": False})
            continue
        out.append({
            "id": int(oid),
            "type": ftype,
            "visible": True,
            "x0": round(float(xs.min()) / w_img, 4),
            "x1": round(float(xs.max() + 1) / w_img, 4),
            "y0": round(float(ys.min()) / h_img, 4),
            "y1": round(float(ys.max() + 1) / h_img, 4),
            "cx": round(float(xs.mean()) / w_img, 4),
            "cy": round(float(ys.mean()) / h_img, 4),
            "area": round(float(xs.size) / (w_img * h_img), 5),
        })
    out.sort(key=lambda d: -d.get("cy", 0.0))
    return out


# ── Rasterization (id-aware z-buffer) ────────────────────────────────────────

_NEAR = 0.05


def rasterize_ids(
    tagged_tris: list[tuple[np.ndarray, int]], cam: LookAtCamera,
) -> tuple[np.ndarray, np.ndarray]:
    """Z-buffer rasterize tagged triangles.

    Returns ``(zbuf, idbuf)``: ``zbuf`` is real camera-space depth (``inf`` =
    empty, smaller = nearer); ``idbuf`` is the winning object id per pixel
    (``0`` = empty/background).
    """
    H, W = cam.img_h, cam.img_w
    zbuf = np.full((H, W), np.inf, dtype=np.float64)
    idbuf = np.zeros((H, W), dtype=np.int32)

    for verts, obj_id in tagged_tris:
        cp = cam.to_cam(verts)
        zc = cp[:, 2]
        if np.any(zc <= _NEAR):
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
        gxf, gyf = gx + 0.5, gy + 0.5
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
        sub_id = idbuf[miny:maxy + 1, minx:maxx + 1]
        upd = inside & (zpix < sub_z)
        sub_z[upd] = zpix[upd]
        sub_id[upd] = obj_id
        zbuf[miny:maxy + 1, minx:maxx + 1] = sub_z
        idbuf[miny:maxy + 1, minx:maxx + 1] = sub_id

    return zbuf, idbuf


def depth_to_gray(zbuf: np.ndarray) -> np.ndarray:
    """View-space depth -> 8-bit map (near = bright, far = dark), normalized by
    the scene's actual depth range so the full 0..255 range is used."""
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
    out[~finite] = 0
    return out


# ── Candidate camera generation + occlusion scoring ──────────────────────────

def generate_candidates(base: CameraParams, count: int = 6) -> list[CameraParams]:
    """``base`` (candidate 0) plus a handful of small perturbations — nudged back/in,
    raised/lowered, aimed slightly deeper/shallower — so minor occlusion from one
    station point can be resolved by trying a nearby one.

    Kept deliberately close to ``base``: pulling the camera back is the cheapest way
    to "see more" (everything gets smaller and less occluded), so a wide-ranging
    search would systematically drift toward a distant, flattened "establishing
    shot" — the base framing was tuned on purpose and candidates should fine-tune
    around it, not replace it.
    """
    candidates = [base]
    deltas: list[dict[str, float]] = [
        {"setback": base.setback * 1.12, "eye_height": base.eye_height + 0.15},
        {"setback": max(0.3, base.setback * 0.9)},
        {"eye_height": max(0.8, base.eye_height - 0.2)},
        {"target_depth_frac": min(0.85, base.target_depth_frac + 0.10)},
        {"target_depth_frac": max(0.3, base.target_depth_frac - 0.10)},
    ]
    for d in deltas[: max(0, count - 1)]:
        candidates.append(replace(base, **d))
    return candidates


def _framing_drift(params: CameraParams, base: CameraParams) -> float:
    """How far ``params`` has strayed from the tuned ``base`` framing, as a unitless
    fraction. Used to keep candidate selection from trading a marginal occlusion
    gain for a noticeably different (usually more distant/wide-looking) shot."""
    return (
        abs(params.setback - base.setback) / max(base.setback, 0.1)
        + abs(params.eye_height - base.eye_height) / max(base.eye_height, 0.1)
    )


def _furniture_ids(id_to_type: dict[int, str]) -> list[int]:
    return [oid for oid, t in id_to_type.items() if not t.startswith("_")]


def score_camera(
    params: CameraParams,
    base: CameraParams,
    room_w: float,
    room_d: float,
    img_w: int,
    img_h: int,
    tagged_tris: list[tuple[np.ndarray, int]],
    furn_ids: list[int],
    by_id: dict[int, list[tuple[np.ndarray, int]]],
) -> tuple[float, dict[str, Any]]:
    """Score one candidate camera by how little furniture occludes other
    furniture: for each piece, the fraction of its *own* unoccluded silhouette
    (rasterized alone) that's still visible once everything else is drawn.
    Pieces that fall entirely outside the frame are penalized separately, and a
    small penalty discourages drifting far from ``base`` (see ``_framing_drift``)
    so a marginal occlusion gain can't justify a noticeably different shot.
    """
    cam = LookAtCamera(room_w, room_d, img_w, img_h, params)
    zbuf, idbuf = rasterize_ids(tagged_tris, cam)
    drift_penalty = 0.08 * _framing_drift(params, base)

    if not furn_ids:
        return -drift_penalty, {"cam": cam, "zbuf": zbuf, "idbuf": idbuf, "ratios": {}, "off_frame": 0}

    ratios: dict[int, float] = {}
    off_frame = 0
    min_expected_px = 4
    for oid in furn_ids:
        visible = int((idbuf == oid).sum())
        _, iso_idbuf = rasterize_ids(by_id.get(oid, []), cam)
        expected = int((iso_idbuf == oid).sum())
        if expected < min_expected_px:
            off_frame += 1
            continue
        ratios[oid] = min(1.0, visible / expected)

    if not ratios:
        score = -1.0
    else:
        score = sum(ratios.values()) / len(ratios)
        score -= 0.3 * (off_frame / len(furn_ids))
    score -= drift_penalty

    return score, {"cam": cam, "zbuf": zbuf, "idbuf": idbuf, "ratios": ratios, "off_frame": off_frame}


def select_best_camera(
    base: CameraParams,
    room_w: float,
    room_d: float,
    room_h: float,
    img_w: int,
    img_h: int,
    furniture_placements: list[dict[str, Any]],
    *,
    semantic_shapes: bool = True,
    candidates: int = 6,
) -> tuple[CameraParams, dict[str, Any]]:
    """Render ``candidates`` station points, score each by furniture occlusion,
    and return the best-scoring :class:`CameraParams` plus its rasterized
    result (so the caller doesn't have to render it again).
    """
    tagged, id_to_type = build_tagged_scene(
        furniture_placements, room_w, room_d, room_h, semantic_shapes=semantic_shapes,
    )
    furn_ids = _furniture_ids(id_to_type)
    by_id: dict[int, list[tuple[np.ndarray, int]]] = {}
    for tri, oid in tagged:
        if oid in furn_ids:
            by_id.setdefault(oid, []).append((tri, oid))

    best_params = base
    best_score: float | None = None
    best_info: dict[str, Any] | None = None
    for params in generate_candidates(base, max(1, candidates)):
        score, info = score_camera(
            params, base, room_w, room_d, img_w, img_h, tagged, furn_ids, by_id,
        )
        if best_score is None or score > best_score:
            best_params, best_score, best_info = params, score, info

    assert best_info is not None
    best_info["score"] = best_score
    best_info["id_to_type"] = id_to_type
    return best_params, best_info
