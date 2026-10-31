"""照片入口「調整家具位置」：直接在原圖上搬家具，房間其他像素不動。

整張重新生成只靠深度圖約束，挑高、樓梯、窗型這類結構常常跑掉；這裡改成
挖掉移動／刪除的家具 → 補背景 → 把同一件家具的原圖像素依地板透視縮放後貼到新位置；
新加的家具才用 inpaint 生成。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageFilter

_KEYS = ("x", "y", "w", "h")
_SCALE_RANGE = (0.3, 3.0)


def diff_layout(baseline: list[dict], placements: list[dict], tol: float = 0.01):
    """依 id 比對偵測基準與目前佈局，回傳 (moved [(舊, 新)], removed, added)。"""
    base = {str(p.get("id")): p for p in baseline}
    now = {str(p.get("id")): p for p in placements}
    moved = [
        (base[i], now[i]) for i in now
        if i in base and any(abs(float(now[i].get(k, 0)) - float(base[i].get(k, 0))) > tol for k in _KEYS)
    ]
    removed = [base[i] for i in base if i not in now]
    added = [now[i] for i in now if i not in base]
    return moved, removed, added


def _near_edge(geom: Any, p: dict, scale: tuple[float, float]) -> tuple[np.ndarray, float]:
    """家具俯視框靠鏡頭那條邊的中點（影像像素）與那條邊在畫面上的寬度。家具在照片裡的底部大致就在這條邊。"""
    x, y, w, h = (float(p.get(k, 0)) for k in _KEYS)
    pts = geom.plan_to_pixel(np.array([[x + w / 2, y + h], [x, y + h], [x + w, y + h]]))
    pts = pts * np.asarray(scale)
    return pts[0], max(float(np.linalg.norm(pts[2] - pts[1])), 1.0)


def moved_box(geom: Any, old: dict, new: dict, box_px: tuple[float, float, float, float],
              scale: tuple[float, float]) -> tuple[tuple[float, float, float, float], float]:
    """舊的照片框 → 新位置的照片框與縮放倍率：以俯視框的近邊中點為錨點平移，近邊寬度比例縮放。"""
    a0, w0 = _near_edge(geom, old, scale)
    a1, w1 = _near_edge(geom, new, scale)
    s = float(np.clip(w1 / w0, *_SCALE_RANGE))
    x0, y0, x1, y1 = box_px
    nx0, ny0 = a1 + (np.array([x0, y0]) - a0) * s
    nx1, ny1 = a1 + (np.array([x1, y1]) - a0) * s
    return (float(nx0), float(ny0), float(nx1), float(ny1)), s


def added_box(geom: Any, p: dict, height_m: float, scale: tuple[float, float]) -> tuple[float, float, float, float]:
    """新加家具的俯視框 → 照片上的外框（含高度）。"""
    x, y, w, h = (float(p.get(k, 0)) for k in _KEYS)
    base = geom.plan_to_pixel(np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]]))
    top = geom.lift(base, height_m)
    pts = np.concatenate([base, top]) * np.asarray(scale)
    return float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())


def _box_px(image_box: list[float], size: tuple[int, int]) -> tuple[float, float, float, float]:
    w, h = size
    x0, y0, x1, y1 = image_box
    return x0 * w, y0 * h, x1 * w, y1 * h


def _object_mask(image_path: str, box: tuple[float, float, float, float], size: tuple[int, int],
                 segment: Callable | None) -> np.ndarray:
    """家具輪廓遮罩（bool, H×W）：SAM 2 切得出來就用，切不出來或切到框外一大片就退回整個框。"""
    w, h = size
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    rect = np.zeros((h, w), dtype=bool)
    rect[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = True
    if segment is None:
        return rect
    m = segment(image_path, (x0, y0, x1, y1))
    if m is None or m.shape != rect.shape or not m.any():
        return rect
    m = m & rect
    return m if m.sum() > 0.15 * rect.sum() else rect


def _dilate(mask: np.ndarray, px: int) -> Image.Image:
    img = Image.fromarray((mask * 255).astype(np.uint8), mode="L")
    return img.filter(ImageFilter.MaxFilter(px * 2 + 1)) if px > 0 else img


def move_furniture_in_photo(
    image_path: str,
    geom: Any,
    detected: list[dict],
    baseline: list[dict],
    placements: list[dict],
    out_dir: Path,
    tag: str,
    *,
    inpaint: Callable[[str, Image.Image, str, Path], bool],
    segment: Callable | None = None,
    height_of: Callable[[str], float] = lambda t: 0.8,
) -> dict[str, Any]:
    """回傳 {"image_path", "moved", "removed", "added", "pasted"}；沒有任何變動時 image_path 為 None。

    inpaint(image_path, mask, prompt, out_path) -> bool；segment(image_path, box_xyxy) -> bool 遮罩或 None。
    """
    moved, removed, added = diff_layout(baseline, placements)
    if not (moved or removed or added):
        return {"image_path": None, "moved": 0, "removed": 0, "added": 0, "pasted": 0}

    photo = Image.open(image_path).convert("RGB")
    size = photo.size
    gw, gh = geom.image_size
    scale = (size[0] / gw, size[1] / gh)   # 地板幾何是在深度圖解析度上解的
    boxes = {str(p.get("id")): p.get("image_box") for p in detected if p.get("image_box")}
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. 挖掉移動／刪除的家具並補背景
    cutouts: list[tuple[dict, Image.Image, tuple[float, float, float, float], float]] = []
    hole = np.zeros((size[1], size[0]), dtype=bool)
    for old, new in moved:
        box = boxes.get(str(old.get("id")))
        if not box:
            continue
        px = _box_px(box, size)
        obj = _object_mask(image_path, px, size, segment)
        hole |= obj
        rgba = photo.copy()
        rgba.putalpha(Image.fromarray((obj * 255).astype(np.uint8), mode="L"))
        crop = rgba.crop(tuple(int(round(v)) for v in px))
        new_px, s = moved_box(geom, old, new, px, scale)
        cutouts.append((new, crop, new_px, s))
    for old in removed:
        box = boxes.get(str(old.get("id")))
        if box:
            hole |= _object_mask(image_path, _box_px(box, size), size, segment)

    # 2. 原家具先貼到新位置（遠的先貼，近的蓋在上面），再一次重畫「舊位置＋新位置邊緣一圈」：
    #    跟渲染圖拖曳（move_furniture）同一個順序，邊緣才融得進去、有接觸陰影；先補洞再貼會留下硬邊
    placed = Image.new("RGBA", size, (0, 0, 0, 0))
    for new, crop, (x0, y0, x1, y1), _s in sorted(cutouts, key=lambda c: float(c[0].get("y", 0)) + float(c[0].get("h", 0))):
        piece = crop.resize((max(1, int(round(x1 - x0))), max(1, int(round(y1 - y0)))), Image.LANCZOS)
        placed.paste(piece, (int(round(x0)), int(round(y0))), piece)
    new_obj = np.asarray(placed.getchannel("A")) > 127
    canvas = photo.copy()
    canvas.paste(placed, (0, 0), placed)
    composed = out_dir / f"{tag}_moved.png"
    canvas.save(composed)
    current = str(composed)

    # 接縫只畫在家具外圍，不碰家具本身：細椅腳、鏤空椅背被內縮或蓋到就會被補背景整個抹掉
    region = (np.asarray(_dilate(hole, 12)) > 127) & ~new_obj
    if new_obj.any():
        region |= (np.asarray(_dilate(new_obj, 8)) > 127) & ~new_obj
    if region.any():
        blended = out_dir / f"{tag}_blended.png"
        prompt = ("empty floor and wall continuing the surrounding room, natural soft contact shadows, "
                  "no new furniture, photorealistic")
        if not inpaint(current, Image.fromarray((region * 255).astype(np.uint8), mode="L"), prompt, blended):
            raise RuntimeError("補背景失敗（inpaint 服務都沒有回應）")
        # 家具本體貼回原像素：重畫只負責背景與接縫，不改家具長相
        out = Image.open(blended).convert("RGB").resize(size, Image.LANCZOS)
        out.paste(placed.convert("RGB"), (0, 0), placed.getchannel("A"))
        out.save(blended)
        current = str(blended)

    # 3. 新加的家具：在新位置的外框裡生成
    for i, p in enumerate(added):
        ftype = str(p.get("type", "furniture"))
        x0, y0, x1, y1 = added_box(geom, p, height_of(ftype), scale)
        mask = Image.new("L", size, 0)
        mask.paste(255, (int(max(0, x0)), int(max(0, y0)), int(min(size[0], x1)), int(min(size[1], y1))))
        out = out_dir / f"{tag}_add{i}.png"
        if inpaint(current, mask, f"a {ftype.replace('_', ' ')} standing on the floor, matching the room, photorealistic", out):
            current = str(out)

    return {"image_path": current, "moved": len(moved), "removed": len(removed), "added": len(added),
            "pasted": len(cutouts)}
