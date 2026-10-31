"""在任何一張圖上直接搬家具：點選 → SAM 2 切出整件 → 拖到新位置 → 補舊位置、融合邊緣。

CAD 的結果圖有相機與家具配置，走 move_furniture（換算成地板座標重繪）；
照片入口與「直接描述」的結果沒有這些資料，走這裡，只在影像上操作，一次 inpaint 就完成。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageFilter

# 沒有相機資料時假設的地平線（畫面高度比例）：室內圖多半接近水平拍攝，拖遠變小、拖近變大用
HORIZON_Y = 0.45
_MIN_FRAC, _MAX_FRAC = 0.002, 0.4
_SCALE_RANGE = (0.2, 4.0)

FILL_PROMPT = (
    "Empty floor and walls seamlessly continuing the surrounding room's materials, patterns and lighting, "
    "with natural soft contact shadows. No furniture or objects added. Photorealistic. "
    "No text, no writing, no letters, no words, no typography, no signage or wall decals anywhere in the image."
)


def _grow(mask: np.ndarray, px: int) -> np.ndarray:
    if px <= 0:
        return mask
    img = Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(2 * px + 1))
    return np.asarray(img) > 127


def pick(image_path: str, u: float, v: float, out_dir: Path,
         segment: Callable[[str, tuple[float, float]], Any] | None = None) -> dict | None:
    """點到 (u, v)（0–1）的物件：存下遮罩與去背圖層，回傳拖曳需要的框、地板錨點與地平線。沒點到家具回 None。"""
    if segment is None:
        from designbridge.render.inpaint import sam2_mask_from_point as segment
    img = Image.open(image_path).convert("RGB")
    W, H = img.size
    m = segment(image_path, (u * W, v * H))
    if m is None:
        return None
    m = np.asarray(m).astype(bool)
    frac = m.mean()
    if not (_MIN_FRAC <= frac <= _MAX_FRAC):
        return None
    m = _grow(m, 2)   # 邊緣多帶一點，搬走後不留一圈殘影

    ys, xs = np.nonzero(m)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    out_dir.mkdir(parents=True, exist_ok=True)
    key = uuid.uuid4().hex[:10]
    mask_path = out_dir / f"move_{key}_mask.png"
    Image.fromarray((m * 255).astype(np.uint8)).save(mask_path)
    layer = img.convert("RGBA")
    layer.putalpha(Image.fromarray((m * 255).astype(np.uint8)))
    layer_path = out_dir / f"move_{key}_layer.png"
    layer.crop((x0, y0, x1, y1)).save(layer_path)

    anchor_y = y1 / H
    return {
        "mask_path": str(mask_path).replace("\\", "/"),
        "layer_path": str(layer_path).replace("\\", "/"),
        "bbox": {"x0": x0 / W, "y0": y0 / H, "x1": x1 / W, "y1": y1 / H},
        "anchor": {"x": (x0 + x1) / 2 / W, "y": anchor_y},   # 家具底部中點，大致就是貼地的位置
        "horizon_y": min(HORIZON_Y, anchor_y - 0.05),
    }


def perspective_scale(from_y: float, to_y: float, horizon_y: float) -> float:
    """地板上的東西大小跟離地平線的距離成正比。"""
    s = (max(to_y, horizon_y + 0.01) - horizon_y) / max(from_y - horizon_y, 0.01)
    return float(np.clip(s, *_SCALE_RANGE))


def move(image_path: str, mask_path: str, to_xy: tuple[float, float], horizon_y: float, out_path: Path,
         inpaint: Callable[[str, Image.Image, str, Path], bool]) -> Path:
    """把遮罩內的物件依透視縮放後搬到 to_xy（新的地板錨點，0–1），一次 inpaint 補舊位置並融合新位置邊緣。"""
    img = Image.open(image_path).convert("RGB")
    W, H = img.size
    m = np.asarray(Image.open(mask_path).convert("L").resize((W, H), Image.NEAREST)) > 127
    if not m.any():
        raise ValueError("遮罩是空的")
    ys, xs = np.nonzero(m)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    ax, ay = (x0 + x1) / 2, y1
    tx, ty = to_xy[0] * W, to_xy[1] * H
    s = perspective_scale(ay / H, ty / H, horizon_y)

    obj = img.convert("RGBA")
    obj.putalpha(Image.fromarray((m * 255).astype(np.uint8)))
    obj = obj.crop((x0, y0, x1, y1))
    nw, nh = max(1, round((x1 - x0) * s)), max(1, round((y1 - y0) * s))
    obj = obj.resize((nw, nh), Image.LANCZOS)
    nx0, ny0 = round(tx + (x0 - ax) * s), round(ty + (y0 - ay) * s)

    placed = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    placed.paste(obj, (nx0, ny0), obj)
    new_alpha = np.asarray(placed.getchannel("A")) > 127

    composite = img.copy()
    composite.paste(placed, (0, 0), placed)
    # 要重畫的：舊位置（扣掉新位置蓋住的）＋新位置外圍一圈（融光影、補接觸陰影）；
    # 不碰家具本身，細椅腳、鏤空椅背被蓋到會被補背景整個抹掉
    region = (_grow(m, 6) & ~new_alpha) | (_grow(new_alpha, 8) & ~new_alpha)
    region_img = Image.fromarray((region * 255).astype(np.uint8))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    comp_path = out_path.with_name(f"{out_path.stem}_composite.png")
    composite.save(comp_path)
    if not inpaint(str(comp_path), region_img, FILL_PROMPT, out_path):
        raise RuntimeError("補背景失敗，請稍後再試")

    # 家具本體貼回原像素：inpaint 只負責背景與邊緣，不讓它改掉家具長相
    filled = Image.open(out_path).convert("RGB").resize((W, H), Image.LANCZOS)
    filled.paste(placed.convert("RGB"), (0, 0), placed.getchannel("A"))
    filled.save(out_path)
    return out_path


def default_inpaint(image_path: str, mask: Image.Image, prompt: str, out_path: Path) -> bool:
    """Fill dev（有開 Modal 先走自架，否則 fal）；都失敗退回本機 LaMa，至少把舊位置補起來。"""
    from designbridge.render.inpaint import run_fal_inpainting, run_lama_inpainting

    if run_fal_inpainting(image_path, mask, prompt, out_path, num_steps=28):
        return True
    return bool(run_lama_inpainting(image_path, mask, out_path))
