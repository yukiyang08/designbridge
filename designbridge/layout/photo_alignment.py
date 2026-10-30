"""照片錨定投影的對齊檢查：把推算的地板幾何與新家具腳印疊回原照片，並給幾個分數。

只給除錯台判斷「幾何猜得對不對」，不影響生圖。門檻是經驗值，用來提示要不要看疊圖，不是驗收標準。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from designbridge.layout.photo_geometry import (
    CEILING_LABELS,
    FLOOR_LABELS,
    WALL_LABELS,
    PhotoFloorGeometry,
    _load_labels_matched,
    mask_for_labels,
)

_MIN_FLOOR_IN_QUAD = 0.8    # 照片裡的地板有多少落在推算的地板範圍內
_MAX_QUAD_ON_WALL = 0.15    # 推算的地板範圍有多少壓到牆、門窗、天花板
_MAX_FOOT_ON_WALL = 0.3     # 新家具腳印壓到牆的比例，超過代表會浮空或穿牆
_MIN_QUAD_AREA = 0.1        # 推算的地板範圍佔畫面比例；太小是整個房間被縮成一角


def _polygon_mask(points: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    from PIL import Image, ImageDraw

    img = Image.new("L", size, 0)
    ImageDraw.Draw(img).polygon([(float(x), float(y)) for x, y in points], fill=1)
    return np.asarray(img, dtype=bool)


def alignment_report(
    geom: PhotoFloorGeometry,
    depth_path: str | Path,
    seg_path: str | Path,
    seg_meta_path: str | Path,
    footprints: list[tuple[str, np.ndarray]],
    photo_path: str | Path | None,
    overlay_path: Path,
) -> dict[str, Any]:
    from PIL import Image

    w, h = geom.image_size
    disp = np.asarray(Image.open(str(depth_path)).convert("L"), dtype=np.float32)
    labels, id_to_label = _load_labels_matched(seg_path, seg_meta_path, disp.shape)
    floor = mask_for_labels(labels, id_to_label, FLOOR_LABELS)
    blocked = mask_for_labels(labels, id_to_label, WALL_LABELS | CEILING_LABELS)
    quad = _polygon_mask(geom.floor_quad, (w, h))

    floor_in_quad = float((floor & quad).sum() / max(floor.sum(), 1))
    quad_on_wall = float((quad & blocked).sum() / max(quad.sum(), 1))
    # 推算的地板平面 vs 照片本身的深度（0–255 灰階），差越大代表地板斜率猜錯
    floor_depth_mae = float(np.abs(geom.floor_disparity_grid() - disp)[floor].mean()) if floor.any() else None

    items = []
    for item_id, base in footprints:
        fp = _polygon_mask(base, (w, h))
        area = int(fp.sum())
        on_wall = float((fp & blocked).sum() / area) if area else None
        items.append({"id": item_id, "in_view": bool(area), "on_wall": None if on_wall is None else round(on_wall, 3)})

    problems = []
    if floor_in_quad < _MIN_FLOOR_IN_QUAD:
        problems.append(f"推算的地板範圍漏掉 {1 - floor_in_quad:.0%} 的地板")
    if quad.mean() < _MIN_QUAD_AREA:
        problems.append(f"推算的地板範圍只佔畫面 {quad.mean():.0%}，房間可能被縮成一角")
    if quad_on_wall > _MAX_QUAD_ON_WALL:
        problems.append(f"推算的地板範圍有 {quad_on_wall:.0%} 壓到牆或門窗")
    for it in items:
        if it["on_wall"] is not None and it["on_wall"] > _MAX_FOOT_ON_WALL:
            problems.append(f"{it['id']} 的腳印有 {it['on_wall']:.0%} 落在牆上")
        elif not it["in_view"]:
            problems.append(f"{it['id']} 投影在畫面外")

    _draw_overlay(geom, floor, footprints, items, photo_path, disp, overlay_path)
    return {
        "overlay_path": str(overlay_path),
        "verdict": "check" if problems else "ok",
        "problems": problems,
        "floor_in_quad": round(floor_in_quad, 3),
        "quad_on_wall": round(quad_on_wall, 3),
        "floor_depth_mae": None if floor_depth_mae is None else round(floor_depth_mae, 1),
        # 整個房間被縮成畫面一角時，前兩個分數可能都正常，要看這個
        "quad_area": round(float(quad.mean()), 3),
        "horizon_source": geom.horizon_source,
        "items": items,
    }


def _draw_overlay(geom, floor, footprints, items, photo_path, disp, out: Path) -> None:
    """原照片上疊：照片地板（綠）、推算的地板範圍（黃框）、消失線（青）、新家具腳印（紅＝壓到牆）。"""
    from PIL import Image, ImageDraw, ImageFont

    w, h = geom.image_size
    if photo_path and Path(str(photo_path)).is_file():
        base = Image.open(str(photo_path)).convert("RGB").resize((w, h), Image.LANCZOS)
    else:
        base = Image.fromarray(disp.astype(np.uint8)).convert("RGB")
    tint = np.asarray(base, dtype=np.float32)
    tint[floor] = tint[floor] * 0.6 + np.array([60, 200, 90]) * 0.4
    img = Image.fromarray(tint.astype(np.uint8))
    draw = ImageDraw.Draw(img)
    lw = max(2, w // 300)
    try:
        font = ImageFont.load_default(size=max(14, w // 50))
    except TypeError:   # Pillow < 10.1 的預設字型不能調大小
        font = ImageFont.load_default()

    draw.polygon([(float(x), float(y)) for x, y in geom.floor_quad], outline=(255, 210, 0), width=lw)
    v0, v1 = geom.horizon_v(np.array([0.0, float(w - 1)]))
    draw.line([(0, float(v0)), (w - 1, float(v1))], fill=(0, 220, 255), width=lw)

    by_id = {it["id"]: it for it in items}
    for item_id, pts in footprints:
        bad = (by_id[item_id]["on_wall"] or 0) > _MAX_FOOT_ON_WALL
        color = (255, 60, 60) if bad else (255, 140, 0)
        draw.polygon([(float(x), float(y)) for x, y in pts], outline=color, width=lw)
        cx, cy = pts.mean(axis=0)
        draw.text((float(cx), float(cy)), item_id, fill=color, font=font, anchor="mm")

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out))


def load_alignment(task_id: str) -> dict[str, Any] | None:
    """從投影 metadata 讀回對齊檢查結果（合成相機路徑沒有這份資料）。"""
    from designbridge.core.config import Config

    path = Path(Config.ARTIFACTS_DIR) / "layout" / f"{task_id}_projection.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("alignment")
    except (OSError, ValueError):
        return None
