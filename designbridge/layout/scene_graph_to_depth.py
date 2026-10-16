#!/usr/bin/env python3
"""
scene_graph_to_depth.py
-----------------------
把 Layout Agent 的 scene graph 座標（俯視 bounding box）投影成「與算圖視角一致」的
透視深度圖（perspective depth map），作為 FLUX ControlNet / Kontext 的精確空間條件。

設計理念（老師建議）：
  不做完整 3D（不需 Blender / TripoSR）。每件家具用一個長方體代表，由 scene graph
  的正規化座標直接在 3D 房間中擺位，再用 `camera_projection.py` 共用的 look-at 相機
  + z-buffer，得到透視深度圖。純 NumPy 即可。

深度極性與 vision.run_depth_estimation 一致：近處亮（255）、遠處暗（0），
對齊 Depth-Anything V2 的視覺化慣例，方便沿用既有 Kontext / ControlNet 深度條件。

座標慣例（與 `camera_projection.py` / `layout_projection.py` 共用）：
  floor-plan x ∈ [0,1] 左→右；y ∈ [0,1] 上(遠牆)→下(近相機側)
  world: X 左右、Y 上下（地板 0、天花板 H）、Z 前後（近相機側 0、遠牆 room_d）

沒有真實照片時（synthetic 分支），相機站位不是固定死的：會產生幾個候選站位，
依「家具互相遮擋的程度」評分，自動選分數最好的一個（見 `camera_projection.select_best_camera`）。

用法：
  python -m designbridge.layout.scene_graph_to_depth placements.json --out depth.png --seg seg.png --vis
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import numpy as np

from designbridge.layout.camera_projection import (
    CameraParams,
    FURNITURE_HEIGHTS,
    LookAtCamera,
    build_tagged_scene,
    depth_to_gray,
    furniture_height,
    furniture_parts,
    instance_summary,
    is_floor_standing,
    normalize_furniture_type,
    rasterize_ids,
    select_best_camera,
)

__all__ = [
    "FURNITURE_HEIGHTS",
    "normalize_furniture_type",
    "is_floor_standing",
    "furniture_height",
    "furniture_parts",
    "project_scene_graph_to_depth",
    "project_layout_onto_photo",
]


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


def _render_seg(idbuf: np.ndarray, id_to_type: dict[int, str]) -> np.ndarray:
    h_img, w_img = idbuf.shape
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
    return seg_rgb


# ── 幾何組裝（僅 synthetic 相機分支需要的房間尺寸讀取）────────────────────────

def _room_dims(space_info: dict) -> tuple[float, float, float]:
    size = (space_info or {}).get("estimated_size") or {}
    w = float(size.get("width", 5.0))
    d = float(size.get("depth", 4.0))
    h = float(size.get("height", 2.8))
    return w, d, h


def _base_camera_params(overrides: dict[str, Any] | None) -> CameraParams:
    from designbridge.core.config import Config

    base = CameraParams(
        eye_height=Config.LAYOUT_CAM_EYE_H,
        setback=Config.LAYOUT_CAM_SETBACK,
        target_h=Config.LAYOUT_CAM_TARGET_H,
        target_depth_frac=Config.LAYOUT_CAM_TARGET_DEPTH_FRAC,
        fov_v_deg=Config.LAYOUT_CAM_FOV,
    )
    return replace(base, **overrides) if overrides else base


# ── 主函式（synthetic 相機：無真實照片時使用）─────────────────────────────────

def project_scene_graph_to_depth(
    furniture_placements: list[dict],
    space_info: dict | None = None,
    out_path: str | Path | None = None,
    *,
    image_size: tuple[int, int] = (1024, 1024),
    seg_out_path: str | Path | None = None,
    camera_overrides: dict[str, Any] | None = None,
    auto_select_camera: bool | None = None,
) -> dict[str, Any]:
    """把 furniture_placements 投影成透視深度圖（近亮遠暗），可選輸出 segmentation。

    ``camera_overrides``：覆寫 base `CameraParams` 的欄位（`eye_height` /
    `setback` / `target_h` / `target_depth_frac` / `fov_v_deg`），當成候選 0。
    ``auto_select_camera``：是否在候選 0 周圍再產生幾個候選站位、依家具遮擋程度
    評分自動挑最好的一個（預設讀 `Config.LAYOUT_CAMERA_AUTO_SELECT`）。關掉時只用
    候選 0，等同過去的固定站位行為。

    回傳 dict：depth_path / seg_path / depth_array / id_map / meta
    （`meta.camera`/`meta.camera_score` 記錄實際選中的相機與分數）。
    """
    from designbridge.core.config import Config

    space_info = space_info or {}
    w_img, h_img = image_size
    room_w, room_d, room_h = _room_dims(space_info)
    base_params = _base_camera_params(camera_overrides)

    use_auto = Config.LAYOUT_CAMERA_AUTO_SELECT if auto_select_camera is None else auto_select_camera
    if use_auto:
        chosen_params, picked = select_best_camera(
            base_params, room_w, room_d, room_h, w_img, h_img,
            furniture_placements or [],
            semantic_shapes=Config.ENABLE_SEMANTIC_SHAPES,
            candidates=Config.LAYOUT_CAMERA_CANDIDATES,
        )
        zbuf, idbuf, id_to_type = picked["zbuf"], picked["idbuf"], picked["id_to_type"]
        camera_score = picked["score"]
        if furniture_placements:
            _p = chosen_params
            print(
                f"[scene_graph_to_depth] 候選角度評分選用相機："
                f"eye_height={_p.eye_height:.2f} setback={_p.setback:.2f} "
                f"target_h={_p.target_h:.2f} target_depth_frac={_p.target_depth_frac:.2f} "
                f"fov_v={_p.fov_v_deg:.0f}°（分數 {camera_score:.3f}）"
            )
    else:
        chosen_params = base_params
        tagged, id_to_type = build_tagged_scene(
            furniture_placements or [], room_w, room_d, room_h,
            semantic_shapes=Config.ENABLE_SEMANTIC_SHAPES,
        )
        cam = LookAtCamera(room_w, room_d, w_img, h_img, chosen_params)
        zbuf, idbuf = rasterize_ids(tagged, cam)
        camera_score = None

    depth_img = depth_to_gray(zbuf)

    # 合成深度是硬邊方塊（家具邊緣沒有真實深度圖的漸層過渡），ControlNet 用力
    # 對齊硬邊時容易在物件邊界生成半透明疊影。輕微模糊軟化邊緣，緩解此瑕疵。
    from PIL import Image, ImageFilter
    depth_img = np.array(
        Image.fromarray(depth_img, mode="L").filter(ImageFilter.GaussianBlur(radius=3))
    )

    furniture_count = sum(1 for t in id_to_type.values() if not t.startswith("_"))
    result: dict[str, Any] = {
        "depth_array": depth_img,
        "id_map": idbuf,
        "id_to_type": id_to_type,
        "meta": {
            "room_dims": {"width": room_w, "depth": room_d, "height": room_h},
            "image_size": {"width": w_img, "height": h_img},
            "furniture_count": furniture_count,
            "instances": instance_summary(idbuf, id_to_type),
            "camera": asdict(chosen_params),
            "camera_score": camera_score,
        },
    }

    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(depth_img, mode="L").save(str(out_path))
        result["depth_path"] = str(out_path)

    if seg_out_path is not None:
        seg_out_path = Path(seg_out_path)
        seg_out_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(_render_seg(idbuf, id_to_type), mode="RGB").save(str(seg_out_path))
        result["seg_path"] = str(seg_out_path)

    return result


# ── 照片錨定投影（首選路徑，相機由照片本身決定，候選評分不適用）──────────────────

def _raster_pixel_triangle(
    zbuf: np.ndarray,
    idbuf: np.ndarray,
    p0: np.ndarray, p1: np.ndarray, p2: np.ndarray,
    d0: float, d1: float, d2: float,
    obj_id: int,
) -> None:
    """直接以影像像素座標 + disparity 光柵化三角形（inverse-depth 語意，大=近）。

    這是給「貼真實照片」路徑用的——相機已經是照片本身，沒有世界座標投影，純粹是
    像素空間的疊圖，跟 `camera_projection.rasterize_ids`（世界座標合成相機）無關。
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


def _raster_pixel_quad(
    zbuf: np.ndarray, idbuf: np.ndarray,
    pix: np.ndarray, disp: np.ndarray, obj_id: int,
) -> None:
    """直接以影像像素座標 + disparity 光柵化四邊形（緩衝區同為 inverse-depth 語意）。"""
    _raster_pixel_triangle(zbuf, idbuf, pix[0], pix[1], pix[2],
                            float(disp[0]), float(disp[1]), float(disp[2]), obj_id)
    _raster_pixel_triangle(zbuf, idbuf, pix[0], pix[2], pix[3],
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
      - 相機視角、房間比例直接沿用原始照片，不需估焦距或房間尺寸，候選角度評分不適用
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

        obj_id = next_id
        next_id += 1
        id_to_type[obj_id] = ftype
        placed += 1

        # 拆成語意子塊後逐塊投影。整件家具共用一個 obj_id，segmentation 上仍是單一實例。
        for u0, u1, v0, v1, pz0, pz1 in furniture_parts(ftype, fx, fy, fw, fh, height_m):
            if pz1 <= pz0:
                continue
            sub = np.array([
                [fx + u0 * fw, fy + v0 * fh], [fx + u1 * fw, fy + v0 * fh],
                [fx + u1 * fw, fy + v1 * fh], [fx + u0 * fw, fy + v1 * fh],
            ])
            foot = geom.plan_to_pixel(sub)
            if not np.isfinite(foot).all():
                continue
            # geom.lift 只沿畫面垂直方向抬升，視差沿用地板落點 —— 上下兩面共用同一組 disp
            disp = geom.floor_disparity(foot)
            bottom = foot if pz0 <= 0.0 else geom.lift(foot, pz0)
            top = geom.lift(foot, pz1)
            if not (np.isfinite(bottom).all() and np.isfinite(top).all()):
                continue
            # 頂面
            _raster_pixel_quad(zbuf, idbuf, top, disp, obj_id)
            # 四個側面：子塊底邊 (i → j) 往上長成一片
            for i in range(4):
                j = (i + 1) % 4
                side = np.stack([bottom[i], bottom[j], top[j], top[i]])
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
            "instances": instance_summary(idbuf, id_to_type),
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
        seg_pil = Image.fromarray(_render_seg(idbuf, id_to_type), mode="RGB")

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
    parser.add_argument("--setback", type=float, default=None, help="相機後退距離（公尺），覆寫候選 0")
    parser.add_argument("--eye-height", type=float, default=None, help="相機眼高（公尺），覆寫候選 0")
    parser.add_argument("--no-auto-camera", action="store_true", help="關閉候選角度評分，只用候選 0")
    parser.add_argument("--vis", action="store_true", help="另存深度+seg 並排視覺化圖")
    args = parser.parse_args()

    src = Path(args.placements)
    placements, space_info = _load_placements(src)
    out_path = Path(args.out) if args.out else src.parent / "projected_depth.png"
    seg_path = Path(args.seg) if args.seg else None

    overrides: dict[str, Any] = {}
    if args.setback is not None:
        overrides["setback"] = args.setback
    if args.eye_height is not None:
        overrides["eye_height"] = args.eye_height

    res = project_scene_graph_to_depth(
        placements, space_info, out_path,
        image_size=(args.width, args.height),
        seg_out_path=seg_path,
        camera_overrides=overrides or None,
        auto_select_camera=not args.no_auto_camera,
    )

    print(f"家具數：{res['meta']['furniture_count']}")
    print(f"房間尺寸：{res['meta']['room_dims']}")
    print(f"選用相機：{res['meta']['camera']}（分數 {res['meta']['camera_score']}）")
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
