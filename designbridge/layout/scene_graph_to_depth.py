#!/usr/bin/env python3
"""
scene_graph_to_depth.py
-----------------------
把 Layout Agent 的 scene graph 座標（俯視 bounding box）投影成「與算圖視角一致」的
透視深度圖（perspective depth map），作為 FLUX ControlNet / Kontext 的精確空間條件。

設計理念（老師建議）：
  不做完整 3D（不需 Blender / TripoSR）。每件家具用一個長方體代表，由 scene graph
  的正規化座標直接在 3D 房間中擺位，再用固定針孔相機投影 + z-buffer，得到透視深度圖。
  純 NumPy 即可。之後若需要再加 segmentation mask（同一個 pass 順手輸出）。

深度極性與 vision.run_depth_estimation 一致：近處亮（255）、遠處暗（0），
對齊 Depth-Anything V2 的視覺化慣例，方便沿用既有 Kontext / ControlNet 深度條件。

座標慣例：
  floor-plan x ∈ [0,1] 左→右；y ∈ [0,1] 上(遠牆)→下(近相機側)
  world: X 左右、Y 遠近(由近相機側往遠牆遞增)、Z 上下(地板 0、天花板 H)

用法：
  python -m designbridge.layout.scene_graph_to_depth placements.json --out depth.png --seg seg.png --vis
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np


# ── 家具高度（公尺）─ footprint 已由 layout_agent.FURNITURE_SIZES 提供，這裡補垂直高度 ──
FURNITURE_HEIGHTS: dict[str, float] = {
    "sofa": 0.85,
    "loveseat": 0.80,
    "coffee_table": 0.45,
    "tv_unit": 0.50,
    "tv": 0.70,
    "table": 0.75,
    "dining_table": 0.75,
    "chair": 0.90,
    "armchair": 0.95,
    "bed": 0.55,
    "bunk_bed": 1.70,
    "bunk_ladder": 1.55,
    "wardrobe": 2.00,
    "desk": 0.75,
    "bookshelf": 1.80,
    "side_table": 0.55,
    "nightstand": 0.55,
    "lamp": 1.50,
    "rug": 0.02,
    "plant": 1.20,
    "cabinet": 0.90,
    "dresser": 0.85,
    "shelf": 1.60,
    "default": 0.80,
}

# LLM 產出的 type 是自由文字（platform_bed / low_cabinet / floor_lamp…），與上表的短鍵對不上時
# 會全部落到 default 0.80，導致整屋家具等高。這裡把同義詞收斂回標準鍵。
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
}

# 從天花板吊掛或貼在牆上的物件沒有地板 footprint，不能當成從地板長上來的盒子。
# 投影時整個略過，改由 layout_prompt 的文字通道表達。
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

# 房間外殼（地板/牆/天花板）在 segmentation 中的中性顏色
_SHELL_COLORS: dict[str, tuple[int, int, int]] = {
    "floor": (190, 190, 190),
    "ceiling": (225, 225, 225),
    "wall": (210, 210, 210),
}


def _furniture_color(ftype: str) -> tuple[int, int, int]:
    from designbridge.layout.layout_agent import FURNITURE_COLORS
    if ftype in FURNITURE_COLORS:
        return FURNITURE_COLORS[ftype]
    return FURNITURE_COLORS.get(normalize_furniture_type(ftype), FURNITURE_COLORS["default"])


# ── 相機 ──────────────────────────────────────────────────────────────────────

def _build_camera(
    image_size: tuple[int, int],
    *,
    hfov_deg: float = 60.0,
    eye_height: float = 1.40,
    setback: float = 0.80,
    pitch_deg: float = -6.0,
) -> dict[str, float]:
    """固定針孔相機：站在近牆後方 `setback` 公尺、眼高 `eye_height`，朝 +Y（房間內）看。

    pitch_deg < 0 代表略微俯視（看到較多地板），符合一般室內算圖視角。
    """
    w, h = image_size
    f = 0.5 * w / np.tan(np.radians(hfov_deg) / 2.0)
    return {
        "x": 0.0,
        "y": -float(setback),
        "z": float(eye_height),
        "pitch": np.radians(pitch_deg),
        "f": float(f),
        "cx": w / 2.0,
        "cy": h / 2.0,
        "w": w,
        "h": h,
        "near": 0.05,
    }


def _project(points: np.ndarray, cam: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
    """world points (N,3) → 像素座標 (N,2) 與前向深度 (N,)。"""
    rx = points[:, 0] - cam["x"]
    ry = points[:, 1] - cam["y"]
    rz = points[:, 2] - cam["z"]

    th = cam["pitch"]
    fwd = ry * np.cos(th) + rz * np.sin(th)   # 進入畫面方向
    up = -ry * np.sin(th) + rz * np.cos(th)   # 畫面上方

    depth = np.maximum(fwd, cam["near"])
    u = cam["cx"] + cam["f"] * rx / depth
    v = cam["cy"] - cam["f"] * up / depth
    return np.stack([u, v], axis=1), fwd


# ── 三角形光柵化 + z-buffer ────────────────────────────────────────────────────

def _raster_triangle(
    zbuf: np.ndarray,
    idbuf: np.ndarray,
    p0: np.ndarray, p1: np.ndarray, p2: np.ndarray,
    d0: float, d1: float, d2: float,
    obj_id: int,
) -> None:
    """把單一三角形以 z-buffer 寫入。p* 為像素座標 (2,)，d* 為各頂點的 **inverse depth**。

    緩衝區一律採 inverse-depth 語意（大=近、0=無限遠）：平面的 1/深度 在螢幕空間是
    仿射的，所以這裡的重心座標內插才是透視正確的；直接內插「距離」會讓大跨度的
    地板/天花板三角形深度嚴重偏斜。
    """
    h, w = zbuf.shape
    minx = max(int(np.floor(min(p0[0], p1[0], p2[0]))), 0)
    maxx = min(int(np.ceil(max(p0[0], p1[0], p2[0]))), w - 1)
    miny = max(int(np.floor(min(p0[1], p1[1], p2[1]))), 0)
    maxy = min(int(np.ceil(max(p0[1], p1[1], p2[1]))), h - 1)
    if minx > maxx or miny > maxy:
        return

    denom = (p1[1] - p2[1]) * (p0[0] - p2[0]) + (p2[0] - p1[0]) * (p0[1] - p2[1])
    if abs(denom) < 1e-9:
        return

    xs = np.arange(minx, maxx + 1)
    ys = np.arange(miny, maxy + 1)
    gx, gy = np.meshgrid(xs, ys)

    a = ((p1[1] - p2[1]) * (gx - p2[0]) + (p2[0] - p1[0]) * (gy - p2[1])) / denom
    b = ((p2[1] - p0[1]) * (gx - p2[0]) + (p0[0] - p2[0]) * (gy - p2[1])) / denom
    c = 1.0 - a - b
    inside = (a >= 0) & (b >= 0) & (c >= 0)
    if not inside.any():
        return

    depth = a * d0 + b * d1 + c * d2
    sub_z = zbuf[miny:maxy + 1, minx:maxx + 1]
    sub_id = idbuf[miny:maxy + 1, minx:maxx + 1]
    closer = inside & (depth > sub_z)
    sub_z[closer] = depth[closer]
    sub_id[closer] = obj_id


def _raster_quad(
    zbuf: np.ndarray, idbuf: np.ndarray,
    world_quad: np.ndarray, cam: dict[str, float], obj_id: int,
) -> None:
    """把世界座標四邊形（4,3，順序為環繞）拆成兩個三角形光柵化。"""
    pix, depth = _project(world_quad, cam)
    # 任一頂點在相機後方則略過（PoC：房間內物件皆在前方，足夠）
    if (depth <= cam["near"]).any():
        return
    inv = 1.0 / depth
    _raster_triangle(zbuf, idbuf, pix[0], pix[1], pix[2], inv[0], inv[1], inv[2], obj_id)
    _raster_triangle(zbuf, idbuf, pix[0], pix[2], pix[3], inv[0], inv[2], inv[3], obj_id)


# ── 幾何組裝 ──────────────────────────────────────────────────────────────────

def _room_dims(space_info: dict) -> tuple[float, float, float]:
    size = (space_info or {}).get("estimated_size") or {}
    w = float(size.get("width", 5.0))
    d = float(size.get("depth", 4.0))
    h = float(size.get("height", 2.8))
    return w, d, h


def _fp_to_world_box(item: dict, room_w: float, room_d: float) -> tuple[float, float, float, float, float]:
    """floor-plan bbox → world (x0,x1,y0,y1,top_z)。"""
    fx = float(item.get("x", 0.0))
    fy = float(item.get("y", 0.0))
    fw = float(item.get("w", 0.1))
    fh = float(item.get("h", 0.1))
    ftype = str(item.get("type", "default"))

    x0 = (fx - 0.5) * room_w
    x1 = (fx + fw - 0.5) * room_w
    # floor-plan y=0 為遠牆、y=1 為近相機側 → world Y 由近(0)到遠(room_d)
    y_near = (1.0 - (fy + fh)) * room_d
    y_far = (1.0 - fy) * room_d
    top_z = furniture_height(ftype)
    return x0, x1, y_near, y_far, top_z


def _add_room_shell(
    zbuf: np.ndarray, idbuf: np.ndarray, cam: dict[str, float],
    room_w: float, room_d: float, room_h: float,
    shell_ids: dict[str, int],
) -> None:
    hx = room_w / 2.0
    # 地板
    _raster_quad(zbuf, idbuf, np.array([
        [-hx, 0.0, 0.0], [hx, 0.0, 0.0], [hx, room_d, 0.0], [-hx, room_d, 0.0],
    ]), cam, shell_ids["floor"])
    # 天花板
    _raster_quad(zbuf, idbuf, np.array([
        [-hx, 0.0, room_h], [hx, 0.0, room_h], [hx, room_d, room_h], [-hx, room_d, room_h],
    ]), cam, shell_ids["ceiling"])
    # 遠牆
    _raster_quad(zbuf, idbuf, np.array([
        [-hx, room_d, 0.0], [hx, room_d, 0.0], [hx, room_d, room_h], [-hx, room_d, room_h],
    ]), cam, shell_ids["wall"])
    # 左牆
    _raster_quad(zbuf, idbuf, np.array([
        [-hx, 0.0, 0.0], [-hx, room_d, 0.0], [-hx, room_d, room_h], [-hx, 0.0, room_h],
    ]), cam, shell_ids["wall"])
    # 右牆
    _raster_quad(zbuf, idbuf, np.array([
        [hx, 0.0, 0.0], [hx, room_d, 0.0], [hx, room_d, room_h], [hx, 0.0, room_h],
    ]), cam, shell_ids["wall"])


def _add_box(
    zbuf: np.ndarray, idbuf: np.ndarray, cam: dict[str, float],
    x0: float, x1: float, y0: float, y1: float, z1: float, obj_id: int,
) -> None:
    """擺一個長方體（z0=0 在地板）。渲染頂面 + 四側面。"""
    z0 = 0.0
    # 頂面
    _raster_quad(zbuf, idbuf, np.array([
        [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]]), cam, obj_id)
    # 近面 (y0)
    _raster_quad(zbuf, idbuf, np.array([
        [x0, y0, z0], [x1, y0, z0], [x1, y0, z1], [x0, y0, z1]]), cam, obj_id)
    # 遠面 (y1)
    _raster_quad(zbuf, idbuf, np.array([
        [x0, y1, z0], [x1, y1, z0], [x1, y1, z1], [x0, y1, z1]]), cam, obj_id)
    # 左面 (x0)
    _raster_quad(zbuf, idbuf, np.array([
        [x0, y0, z0], [x0, y1, z0], [x0, y1, z1], [x0, y0, z1]]), cam, obj_id)
    # 右面 (x1)
    _raster_quad(zbuf, idbuf, np.array([
        [x1, y0, z0], [x1, y1, z0], [x1, y1, z1], [x1, y0, z1]]), cam, obj_id)


# ── 主函式 ────────────────────────────────────────────────────────────────────

def project_scene_graph_to_depth(
    furniture_placements: list[dict],
    space_info: dict | None = None,
    out_path: str | Path | None = None,
    *,
    image_size: tuple[int, int] = (1024, 1024),
    seg_out_path: str | Path | None = None,
    camera_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把 furniture_placements 投影成透視深度圖（近亮遠暗），可選輸出 segmentation。

    回傳 dict：depth_path / seg_path / depth_array / id_map / meta。
    """
    space_info = space_info or {}
    w_img, h_img = image_size
    cam = _build_camera(image_size, **(camera_overrides or {}))
    room_w, room_d, room_h = _room_dims(space_info)

    zbuf = np.zeros((h_img, w_img), dtype=np.float32)  # inverse depth，0 = 無限遠 / 空
    idbuf = np.zeros((h_img, w_img), dtype=np.int32)  # 0 = 空 / 背景

    # id 配置：1..N_shell 給外殼，之後給家具
    shell_ids = {"floor": 1, "ceiling": 2, "wall": 3}
    _add_room_shell(zbuf, idbuf, cam, room_w, room_d, room_h, shell_ids)

    id_to_type: dict[int, str] = {
        1: "_floor", 2: "_ceiling", 3: "_wall",
    }
    next_id = 4
    for item in (furniture_placements or []):
        if not is_floor_standing(str(item.get("type", "default"))):
            continue
        x0, x1, y0, y1, z1 = _fp_to_world_box(item, room_w, room_d)
        if x1 <= x0 or y1 <= y0:
            continue
        obj_id = next_id
        next_id += 1
        id_to_type[obj_id] = str(item.get("type", "default"))
        _add_box(zbuf, idbuf, cam, x0, x1, y0, y1, z1, obj_id)

    # 深度 → 8-bit 灰階（近亮遠暗）。這裡用 **inverse depth（disparity）** 而非線性距離，
    # 才與 Depth-Anything V2 的輸出一致 —— depth ControlNet 就是拿那種色調曲線訓練的，
    # 餵線性距離會讓模型誤判各面之間的相對遠近。
    covered = zbuf > 0
    depth_img = np.zeros((h_img, w_img), dtype=np.uint8)
    if covered.any():
        ivals = zbuf[covered]
        imin, imax = float(ivals.min()), float(ivals.max())
        if imax - imin < 1e-9:
            depth_img[covered] = 255
        else:
            bright = ((zbuf - imin) / (imax - imin) * 255.0).clip(0, 255)
            depth_img[covered] = bright[covered].astype(np.uint8)

    # 合成深度是硬邊方塊（家具邊緣沒有真實深度圖的漸層過渡），ControlNet 用力
    # 對齊硬邊時容易在物件邊界生成半透明疊影。輕微模糊軟化邊緣，緩解此瑕疵。
    from PIL import Image, ImageFilter
    depth_img = np.array(
        Image.fromarray(depth_img, mode="L").filter(ImageFilter.GaussianBlur(radius=3))
    )

    result: dict[str, Any] = {
        "depth_array": depth_img,
        "id_map": idbuf,
        "id_to_type": id_to_type,
        "meta": {
            "room_dims": {"width": room_w, "depth": room_d, "height": room_h},
            "image_size": {"width": w_img, "height": h_img},
            "furniture_count": next_id - 4,
        },
    }

    from PIL import Image
    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(depth_img, mode="L").save(str(out_path))
        result["depth_path"] = str(out_path)

    if seg_out_path is not None:
        seg_rgb = np.zeros((h_img, w_img, 3), dtype=np.uint8)
        for oid, ftype in id_to_type.items():
            mask = idbuf == oid
            if not mask.any():
                continue
            if ftype.startswith("_"):
                color = _SHELL_COLORS.get(ftype[1:], _SHELL_COLORS["wall"])
            else:
                color = _furniture_color(ftype)
            seg_rgb[mask] = color
        seg_out_path = Path(seg_out_path)
        seg_out_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(seg_rgb, mode="RGB").save(str(seg_out_path))
        result["seg_path"] = str(seg_out_path)

    return result


# ── 照片錨定投影（首選路徑）────────────────────────────────────────────────────

def _raster_pixel_quad(
    zbuf: np.ndarray, idbuf: np.ndarray,
    pix: np.ndarray, disp: np.ndarray, obj_id: int,
) -> None:
    """直接以影像像素座標 + disparity 光柵化四邊形（緩衝區同為 inverse-depth 語意）。"""
    _raster_triangle(zbuf, idbuf, pix[0], pix[1], pix[2],
                     float(disp[0]), float(disp[1]), float(disp[2]), obj_id)
    _raster_triangle(zbuf, idbuf, pix[0], pix[2], pix[3],
                     float(disp[0]), float(disp[2]), float(disp[3]), obj_id)


def project_layout_onto_photo(
    furniture_placements: list[dict],
    depth_path: str | Path,
    seg_path: str | Path,
    seg_meta_path: str | Path,
    out_path: str | Path | None = None,
    *,
    seg_out_path: str | Path | None = None,
    eye_height: float = 1.5,
    output_size: tuple[int, int] | None = None,
    preserve_types: frozenset[str] = frozenset(),
    preserve_mask: np.ndarray | None = None,
) -> dict[str, Any] | None:
    """把新規劃的家具長方體疊回**原始照片自己的深度圖**上。

    相對於 `project_scene_graph_to_depth`（合成相機 + 空盒子），這條路徑：
      - 相機視角、房間比例直接沿用原始照片，不需估焦距或房間尺寸
      - 保留照片中的窗、門、牆角、樑柱等建築結構（只清掉舊家具）
      - 家具腳印經由地板 homography 落在照片裡真實的地板位置

    `preserve_types`：使用者沒要求變動的家具 type（已正規化）。這些家具在照片裡的像素
    深度原封不動保留，也不會再畫合成長方體——ControlNet 因此鎖住的是照片裡的真實幾何，
    而不是一個近似的方盒。`preserve_mask` 供實例級保留使用（SAM 2 路徑）。

    無法可靠解出地板幾何時回傳 None，由呼叫端 fallback 到合成相機版本。
    """
    from designbridge.layout.photo_geometry import (
        build_empty_room_disparity,
        resolve_floor_geometry,
        seg_labels_for_furniture,
    )

    geom = resolve_floor_geometry(depth_path, seg_path, seg_meta_path, eye_height=eye_height)
    if geom is None:
        return None

    zbuf, idbuf, preserved_id_to_type = build_empty_room_disparity(
        depth_path, seg_path, seg_meta_path, geom,
        preserve_labels=seg_labels_for_furniture(preserve_types),
        preserve_mask=preserve_mask,
    )
    zbuf = zbuf.astype(np.float32)
    h_img, w_img = zbuf.shape

    id_to_type: dict[int, str] = {1: "_floor", 2: "_ceiling", 3: "_wall"}
    id_to_type.update(preserved_id_to_type)
    next_id = 4
    placed = 0
    skipped_non_floor: list[str] = []
    skipped_preserved: list[str] = []

    # 遠的先畫、近的後畫仍由 z-buffer 決定勝負，這裡只是讓 id 配置穩定
    for item in sorted(
        furniture_placements or [],
        key=lambda it: float(it.get("y", 0.0)),
    ):
        fx, fy = float(item.get("x", 0.0)), float(item.get("y", 0.0))
        fw, fh = float(item.get("w", 0.1)), float(item.get("h", 0.1))
        if fw <= 0 or fh <= 0:
            continue
        ftype = str(item.get("type", "default"))
        if not is_floor_standing(ftype):
            skipped_non_floor.append(ftype)
            continue
        # 原地保留的家具已經以照片原始深度存在於 zbuf，再畫一次合成盒子只會蓋掉真實幾何
        if normalize_furniture_type(ftype) in preserve_types:
            skipped_preserved.append(ftype)
            continue
        height_m = furniture_height(ftype)

        # 俯視 footprint 四角（環繞：遠左 → 遠右 → 近右 → 近左）
        plan = np.array([
            [fx, fy], [fx + fw, fy], [fx + fw, fy + fh], [fx, fy + fh],
        ])
        base = geom.plan_to_pixel(plan)
        if not np.isfinite(base).all():
            continue
        # 家具必須落在畫面附近，否則是 homography 外插到荒謬區域
        if (base[:, 0].max() < -w_img or base[:, 0].min() > 2 * w_img
                or base[:, 1].max() < -h_img or base[:, 1].min() > 2 * h_img):
            continue

        disp = geom.floor_disparity(base)
        top = geom.lift(base, height_m)

        obj_id = next_id
        next_id += 1
        id_to_type[obj_id] = ftype
        placed += 1

        # 頂面
        _raster_pixel_quad(zbuf, idbuf, top, disp, obj_id)
        # 四個側面：footprint 邊 (i → j) 往上長成一片
        for i in range(4):
            j = (i + 1) % 4
            side = np.stack([base[i], base[j], top[j], top[i]])
            side_disp = np.array([disp[i], disp[j], disp[j], disp[i]])
            _raster_pixel_quad(zbuf, idbuf, side, side_disp, obj_id)

    depth_img = np.clip(zbuf, 0.0, 255.0).astype(np.uint8)

    result: dict[str, Any] = {
        "depth_array": depth_img,
        "id_map": idbuf,
        "id_to_type": id_to_type,
        "meta": {
            "mode": "photo_anchored",
            "image_size": {"width": w_img, "height": h_img},
            "furniture_count": placed,
            "non_floor_skipped": skipped_non_floor,
            "preserved_in_place": skipped_preserved,
            "preserved_regions": len(preserved_id_to_type),
            "floor_coverage": round(geom.floor_coverage, 4),
            "eye_height": geom.eye_height,
            "horizon_source": geom.horizon_source,
        },
    }

    from PIL import Image

    depth_pil = Image.fromarray(depth_img, mode="L")
    seg_pil: Any = None
    if seg_out_path is not None:
        seg_rgb = np.zeros((h_img, w_img, 3), dtype=np.uint8)
        for oid, ftype in id_to_type.items():
            mask = idbuf == oid
            if not mask.any():
                continue
            if ftype.startswith("_"):
                color = _SHELL_COLORS.get(ftype[1:], _SHELL_COLORS["wall"])
            else:
                color = _furniture_color(ftype)
            seg_rgb[mask] = color
        seg_pil = Image.fromarray(seg_rgb, mode="RGB")

    if output_size is not None and tuple(output_size) != (w_img, h_img):
        depth_pil = depth_pil.resize(tuple(output_size), Image.BICUBIC)
        if seg_pil is not None:
            seg_pil = seg_pil.resize(tuple(output_size), Image.NEAREST)
        result["meta"]["output_size"] = {"width": output_size[0], "height": output_size[1]}

    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        depth_pil.save(str(out_path))
        result["depth_path"] = str(out_path)

    if seg_pil is not None:
        seg_out_path = Path(seg_out_path)
        seg_out_path.parent.mkdir(parents=True, exist_ok=True)
        seg_pil.save(str(seg_out_path))
        result["seg_path"] = str(seg_out_path)

    msg = f"[scene_graph_to_depth] 照片錨定投影完成：{placed} 件家具疊回原照片深度"
    if skipped_preserved:
        msg += (
            f"；原地保留 {len(preserved_id_to_type)} 區真實深度"
            f"（{', '.join(skipped_preserved)}）"
        )
    if skipped_non_floor:
        msg += f"；跳過 {len(skipped_non_floor)} 件非地板物件（{', '.join(skipped_non_floor)}）"
    print(msg)
    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

def _load_placements(path: Path) -> tuple[list[dict], dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data, {}
    placements = (
        data.get("furniture_placements")
        or data.get("furniture")
        or (data.get("scene_graph") or {}).get("furniture_placements")
        or []
    )
    space_info = data.get("space_info") or {}
    return placements, space_info


def main() -> None:
    parser = argparse.ArgumentParser(
        description="把 scene graph 家具座標投影成透視深度圖（FLUX ControlNet 條件）"
    )
    parser.add_argument("placements", help="furniture_placements JSON（list 或含該欄位的物件）")
    parser.add_argument("--out", default=None, help="深度圖輸出路徑（預設同目錄 projected_depth.png）")
    parser.add_argument("--seg", default=None, help="可選 segmentation mask 輸出路徑")
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--hfov", type=float, default=60.0)
    parser.add_argument("--pitch", type=float, default=-6.0, help="相機俯角（負=俯視，看更多地板）")
    parser.add_argument("--vis", action="store_true", help="另存深度+seg 並排視覺化圖")
    args = parser.parse_args()

    src = Path(args.placements)
    placements, space_info = _load_placements(src)
    out_path = Path(args.out) if args.out else src.parent / "projected_depth.png"
    seg_path = Path(args.seg) if args.seg else None

    res = project_scene_graph_to_depth(
        placements, space_info, out_path,
        image_size=(args.width, args.height),
        seg_out_path=seg_path,
        camera_overrides={"hfov_deg": args.hfov, "pitch_deg": args.pitch},
    )

    print(f"家具數：{res['meta']['furniture_count']}")
    print(f"房間尺寸：{res['meta']['room_dims']}")
    print(f"深度圖：{res.get('depth_path')}")
    if res.get("seg_path"):
        print(f"Segmentation：{res['seg_path']}")

    if args.vis:
        try:
            import matplotlib.pyplot as plt
            n = 2 if seg_path else 1
            fig, axes = plt.subplots(1, n, figsize=(7 * n, 6))
            axes = np.atleast_1d(axes)
            axes[0].imshow(res["depth_array"], cmap="gray", vmin=0, vmax=255)
            axes[0].set_title("Projected Depth (near=bright)")
            axes[0].axis("off")
            if seg_path:
                from PIL import Image
                axes[1].imshow(np.array(Image.open(seg_path)))
                axes[1].set_title("Segmentation")
                axes[1].axis("off")
            vis_out = out_path.parent / (out_path.stem + "_vis.png")
            plt.tight_layout()
            plt.savefig(vis_out, dpi=110, bbox_inches="tight")
            plt.close()
            print(f"視覺化：{vis_out}")
        except ImportError:
            print("matplotlib 未安裝，略過視覺化")


if __name__ == "__main__":
    main()
