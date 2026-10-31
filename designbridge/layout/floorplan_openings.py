"""平面圖的門：從牆線缺口加門弧線量出來，不靠 Gemini 猜位置。

兩間相鄰房間之間牆上的缺口，旁邊畫著四分之一圓弧的是門，沒有弧線的是開口（書房、
開放式餐廳）或拉門。弧線只畫在開門那一側，所以弧線在哪一側就是開向。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

from designbridge.layout.floorplan_segment import _wall_mask, _work_gray

_CONTACT = 4                    # 兩間房多邊形各外擴幾像素算相鄰
_DOOR_M = (0.5, 1.25)          # 門板長（＝門寬）搜尋範圍，公尺
_ARC_BINS = range(4, 87, 3)     # 弧線取樣角度（28 點）；真的門弧線是連續的，雜線湊不齊
_ARC_HIT = 26                   # 至少幾個取樣點要碰到線
_INK = 210


def _leaf_ok(ink: np.ndarray, hx: float, hy: float, px: float, py: float, radius: float) -> bool:
    """門除了弧線，還會從鉸鏈垂直牆畫出開啟的門板（一條直線）；家具的圓形沒有。"""
    H, W = ink.shape
    ks = range(6, int(radius) - 3, 2)
    hit = 0
    for k in ks:
        xi, yi = int(round(hx + k * px)), int(round(hy + k * py))
        if 1 <= xi < W - 1 and 1 <= yi < H - 1 and ink[yi - 1:yi + 2, xi - 1:xi + 2].any():
            hit += 1
    return len(ks) > 0 and hit / len(ks) >= 0.8


def _ring_clutter(ink_d: np.ndarray, hx: float, hy: float, ax: float, ay: float,
                  px: float, py: float, radius: float) -> float:
    """弧線內外各 5 px 的同心圓上墨線的比例。門弧線是孤零零一條細線，兩側應該是空的；
    窗戶的平行雙線、成排的櫃體線條旁邊都是線，隨便一個圓弧都蓋得到。"""
    H, W = ink_d.shape
    t = np.radians(np.array(_ARC_BINS))
    n = hit = 0
    for rr in (radius - 5, radius + 5):
        xi = np.rint(hx + rr * (np.cos(t) * ax + np.sin(t) * px)).astype(int)
        yi = np.rint(hy + rr * (np.cos(t) * ay + np.sin(t) * py)).astype(int)
        ok = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
        n += int(ok.sum())
        hit += int(ink_d[yi[ok], xi[ok]].sum())
    return hit / n if n else 1.0


def detect_doors(image_path: str, rooms: list[dict], mpp: float) -> list[dict[str, Any]]:
    """mpp 是原圖每像素幾公尺（換算標準門寬用）。
    回傳 [{pair: (i, j), cx, cy, width, orientation, swing}]：座標、寬度為 0–1 正規化於整張圖，
    swing 是門板掃進的房間索引。只列有弧線的門；兩房之間只有開口或拉門的不列。"""
    with Image.open(image_path) as im:
        orig_w = im.width
    g = _work_gray(image_path)
    H, W = g.shape
    wall = _wall_mask(g)
    ink = (g < _INK) & ~wall
    ink_d = ndi.binary_dilation(ink, structure=np.ones((3, 3)))   # 取樣容許 ±1 像素
    angles = np.radians(np.array(_ARC_BINS))
    cos_t, sin_t = np.cos(angles), np.sin(angles)
    px_per_m = W / orig_w / mpp
    r_lo, r_hi = (round(m * px_per_m) for m in _DOOR_M)

    masks = []
    for r in rooms:
        m = Image.new("L", (W, H), 0)
        ImageDraw.Draw(m).polygon([(x * W, y * H) for x, y in r["polygon"]], fill=1)
        masks.append(np.array(m, bool))
    grown = [ndi.binary_dilation(m, iterations=_CONTACT) for m in masks]
    center = [np.argwhere(m).mean(axis=0) for m in masks]   # (y, x)

    doors: list[dict[str, Any]] = []
    for i in range(len(rooms)):
        for j in range(i + 1, len(rooms)):
            band = grown[i] & grown[j]
            if band.sum() < 50:
                continue
            gap = ndi.binary_opening(band & ~wall, structure=np.ones((5, 5)))
            lab, _ = ndi.label(gap)
            best = None   # ((命中數, -|半徑-標準門寬|), 圓心 x, y, 沿牆方向, 開門側, 半徑, 水平？)
            for sl in ndi.find_objects(lab):
                ys, xs = sl
                horizontal = (xs.stop - xs.start) >= (ys.stop - ys.start)
                a0, a1 = (xs.start, xs.stop) if horizontal else (ys.start, ys.stop)
                if a1 - a0 < r_lo * 0.8:
                    continue
                cross0 = (ys.start + ys.stop) / 2 if horizontal else (xs.start + xs.stop) / 2
                # 鉸鏈沿牆位置 × 垂直牆的偏移（缺口中心線不一定在牆正中）
                hinge, off = np.meshgrid(np.arange(a0, a1 + 1), np.arange(-6, 7))
                hinge, cross = hinge.ravel(), (cross0 + off).ravel()
                for r in range(r_lo, r_hi + 1):
                    for sign in (1, -1):   # 另一端在鉸鏈的哪一邊
                        for side in (-1, 1):
                            ax, ay = (sign, 0) if horizontal else (0, sign)
                            px, py = (0, side) if horizontal else (side, 0)
                            hx, hy = (hinge, cross) if horizontal else (cross, hinge)
                            xi = np.rint(hx[:, None] + r * (cos_t * ax + sin_t * px)).astype(int)
                            yi = np.rint(hy[:, None] + r * (cos_t * ay + sin_t * py)).astype(int)
                            ok = (xi >= 0).all(1) & (xi < W).all(1) & (yi >= 0).all(1) & (yi < H).all(1)
                            ok &= (hinge + sign * r >= a0 - 6) & (hinge + sign * r <= a1 + 6)
                            if not ok.any():
                                continue
                            score = np.where(ok, ink_d[np.clip(yi, 0, H - 1), np.clip(xi, 0, W - 1)].sum(1), 0)
                            for k in np.argsort(-score)[:3]:
                                if score[k] < _ARC_HIT:
                                    break
                                if not _leaf_ok(ink, hx[k], hy[k], px, py, r):
                                    continue
                                c = _ring_clutter(ink_d, hx[k], hy[k], ax, ay, px, py, r)
                                if c > 0.3:
                                    continue
                                # 同分取最接近標準門寬 0.9 m 的
                                key = (int(score[k]), -abs(r - 0.9 * px_per_m))
                                if best is None or key > best[0]:
                                    best = (key, float(hx[k]), float(hy[k]), (ax, ay), side, r, horizontal)
                                break
            if best and best[0][0] >= _ARC_HIT:
                _, hx, hy, (ax, ay), side, r, horizontal = best
                cx, cy = hx + ax * r / 2, hy + ay * r / 2
                # center 是 (y, x)：開口沿 x 時兩房上下排，比 y；沿 y 時左右排，比 x
                first, second = sorted((i, j), key=lambda k: center[k][0 if horizontal else 1])
                doors.append({
                    "pair": (i, j), "cx": cx / W, "cy": cy / H, "width": r / (W if horizontal else H),
                    "orientation": "horizontal" if horizontal else "vertical",
                    "swing": first if side < 0 else second,
                })
    return doors
