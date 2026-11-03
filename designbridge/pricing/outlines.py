"""報價家具的輪廓：結果圖上沿著家具描邊，而不是只畫方框。

有 SAM 2 時直接拿 Gemini 給的方框當提示切出那一件（整張圖只編碼一次，每個框各切一次）——
方框本身就是「這一件家具」，切出來最準。沒有 SAM 2 的環境退回 segment_furniture
（「移動家具」那套語意分割＋深度分件，依圖檔快取）配對方框；配不到的回傳 None，前端沿用方框。
"""

from __future__ import annotations

import numpy as np

_MIN_IOU = 0.25       # 遮罩跟方框的 IoU 至少這麼多才算同一件
_MIN_INSIDE = 0.6     # 遮罩至少這個比例落在框內：大件家具不會被旁邊的小框搶走
# 吊燈這類：框連吊線一起框（又細又長），遮罩只有燈罩，IoU 偏低但確實是它——
# 遮罩幾乎整塊在框內、而且遮罩範圍佔框三成以上也算；只切到椅背一角這種仍退回方框
_LOOSE_INSIDE = 0.85
_LOOSE_SPAN = 0.3
_SIMPLIFY_PX = 1.0    # 多邊形簡化的容許誤差（像素）；先平滑過再簡化，不會留下階梯
# 平滑：先補小缺口（閉運算，半徑隨家具大小 2~6px），再輕微模糊重新二值化去鋸齒，最後把轉角磨圓。
# 模糊只用 1px：再大會把軌道燈的軌道、吊燈的吊線這種細線抹掉
_CLOSE_SCALE = 0.02   # 閉運算半徑 ≈ 家具面積開根號 × 這個比例
_BLUR_SIGMA = 1.0
_CHAIKIN_PASSES = 2

# 8 鄰居，順時針（畫面座標 y 往下）：N, NE, E, SE, S, SW, W, NW
_DIRS = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]


_SAM_MIN_FILL = 0.08  # SAM 切出來的面積連框的 8% 都不到，多半是切到雜訊，退回方框


def furniture_outlines(image_path: str, boxes: list[list[float]]) -> list[list[list[float]] | None]:
    """boxes 是報價家具的 [x1, y1, x2, y2]（0~1），回傳每個框對應的輪廓 [[x, y], …]（0~1）或 None。"""
    sam = _sam_outlines(image_path, boxes)
    return sam if sam is not None else _segment_outlines(image_path, boxes)


def _sam_outlines(image_path: str, boxes: list[list[float]]) -> list[list[list[float]] | None] | None:
    """SAM 2 以方框為提示逐一切出家具；SAM 2 不可用回傳 None（呼叫端改走語意分割）。"""
    from designbridge.render.inpaint import _SAM2_INFER_LOCK, _get_sam2_predictor

    predictor = _get_sam2_predictor()
    if predictor is None:
        return None
    import torch
    from PIL import Image

    img = np.asarray(Image.open(image_path).convert("RGB"))
    h, w = img.shape[:2]
    out: list[list[list[float]] | None] = [None] * len(boxes)
    done: dict[tuple, list[list[float]] | None] = {}   # 同款多件、框重複的不重切
    try:
        with torch.inference_mode(), _SAM2_INFER_LOCK:
            predictor.set_image(img)
            for i, b in enumerate(boxes):
                if not b or len(b) != 4:
                    continue
                key = tuple(b)
                if key not in done:
                    px = np.array([b[0] * w, b[1] * h, b[2] * w, b[3] * h])
                    m = _whole_object(*predictor.predict(box=px, multimask_output=True)[:2])
                    box_area = max(1.0, (px[2] - px[0]) * (px[3] - px[1]))
                    done[key] = _polygon(m) if m.sum() >= _SAM_MIN_FILL * box_area else None
                out[i] = done[key]
    except Exception as e:  # noqa: BLE001
        print(f"[outlines] SAM 2 failed, falling back to segmentation: {e}")
        return None
    return out


_WHOLE_SCORE_SLACK = 0.1   # 分數跟最好的差不到這麼多，就算「一樣可信」


def _whole_object(masks: np.ndarray, scores: np.ndarray) -> np.ndarray:
    """SAM 對一個框給三種粒度（局部／部件／整件）：分數差不多的裡面挑面積最大的，
    也就是整件家具——沙發連上面的毯子、抱枕一起，不會在毯子那裡缺一個口。"""
    best = float(np.max(scores))
    ok = [i for i in range(len(scores)) if scores[i] >= best - _WHOLE_SCORE_SLACK]
    return masks[max(ok, key=lambda i: int(masks[i].sum()))].astype(bool)


def _segment_outlines(image_path: str, boxes: list[list[float]]) -> list[list[list[float]] | None]:
    """沒有 SAM 2：方框配到 segment_furniture 的家具遮罩。"""
    from designbridge.render.furniture_instances import segment_furniture

    insts = segment_furniture(image_path)
    out: list[list[list[float]] | None] = [None] * len(boxes)
    if not insts:
        return out
    h, w = insts[0]["mask"].shape
    areas = [int(i["mask"].sum()) for i in insts]

    pairs: list[tuple[float, int, int]] = []
    for bi, b in enumerate(boxes):
        if not b or len(b) != 4:
            continue
        x0, y0 = max(0, int(b[0] * w)), max(0, int(b[1] * h))
        x1, y1 = min(w, int(np.ceil(b[2] * w))), min(h, int(np.ceil(b[3] * h)))
        box_area = max(1, (x1 - x0) * (y1 - y0))
        for ii, inst in enumerate(insts):
            inter = int(inst["mask"][y0:y1, x0:x1].sum())
            if not inter:
                continue
            iou = inter / (box_area + areas[ii] - inter)
            mx0, my0, mx1, my1 = inst["bbox"]
            span = (mx1 - mx0) * (my1 - my0) / box_area
            if (iou >= _MIN_IOU and inter >= _MIN_INSIDE * areas[ii]) or \
               (inter >= _LOOSE_INSIDE * areas[ii] and span >= _LOOSE_SPAN):
                pairs.append((iou, bi, ii))

    # 一個遮罩只給一個框（同款多件、框又重複時，第二件沿用方框）
    used_b: set[int] = set()
    used_i: set[int] = set()
    for _, bi, ii in sorted(pairs, reverse=True):
        if bi in used_b or ii in used_i:
            continue
        used_b.add(bi)
        used_i.add(ii)
        out[bi] = _polygon(insts[ii]["mask"])
    return out


def _polygon(mask: np.ndarray) -> list[list[float]] | None:
    """最大那一塊的外輪廓（填掉內部的洞），簡化後換成 0~1 座標。"""
    from scipy import ndimage

    lab, n = ndimage.label(mask)
    if not n:
        return None
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    blob = _smooth_mask(ndimage.binary_fill_holes(lab == int(np.argmax(sizes)) + 1))
    if not blob.any():
        return None
    pts = _trace(np.pad(blob, 1))
    if len(pts) < 3:
        return None
    # 像素輪廓是一格一格的階梯：先磨圓再簡化；扣掉 pad 的一格
    ring = _chaikin(np.array(pts, dtype=float) - 1.0, _CHAIKIN_PASSES)
    # 頭尾接起來再簡化（閉合輪廓），最後去掉重複的終點
    pts = _simplify(np.vstack([ring, ring[:1]]), _SIMPLIFY_PX)[:-1]
    if len(pts) < 3:
        return None
    h, w = mask.shape
    # 邊緣像素的中心 → 0~1（比家具外緣內縮半個像素，顯示上看不出來）；轉成 float 才能直接回成 JSON
    return [[round(float(x + 0.5) / w, 4), round(float(y + 0.5) / h, 4)] for y, x in pts]


def _smooth_mask(blob: np.ndarray) -> np.ndarray:
    """補掉邊緣的小缺口（沙發上的毯子沒切進去那種凹口），再去掉鋸齒；只留最大一塊。"""
    from scipy import ndimage

    r = int(np.clip(_CLOSE_SCALE * np.sqrt(blob.sum()), 2, 6))
    yy, xx = np.ogrid[-r:r + 1, -r:r + 1]
    disk = xx * xx + yy * yy <= r * r
    padded = np.pad(blob, r + 2)   # 貼著圖邊的家具：閉運算不會從圖邊往內吃
    closed = ndimage.binary_closing(padded, structure=disk)[r + 2:-(r + 2), r + 2:-(r + 2)]
    smooth = ndimage.gaussian_filter(closed.astype(float), _BLUR_SIGMA) > 0.5
    lab, n = ndimage.label(smooth)
    if n > 1:
        sizes = ndimage.sum(smooth, lab, range(1, n + 1))
        smooth = lab == int(np.argmax(sizes)) + 1
    return ndimage.binary_fill_holes(smooth)


def _chaikin(ring: np.ndarray, passes: int) -> np.ndarray:
    """Chaikin 切角（閉合）：每條邊取 1/4、3/4 兩點取代原本的頂點，跑幾輪轉角就圓了。"""
    for _ in range(passes):
        nxt = np.roll(ring, -1, axis=0)
        out = np.empty((len(ring) * 2, 2))
        out[0::2] = 0.75 * ring + 0.25 * nxt
        out[1::2] = 0.25 * ring + 0.75 * nxt
        ring = out
    return ring


def _trace(m: np.ndarray) -> list[tuple[int, int]]:
    """Moore 鄰居輪廓追蹤：從最上排最左邊的像素出發，順時針沿外緣走一圈。m 外圍要有一圈 0。"""
    ys, xs = np.nonzero(m)
    start = (int(ys[0]), int(xs[0]))
    pts = [start]
    cur, back = start, 6   # 起點是該排最左邊，左邊（W）一定是背景
    for _ in range(4 * m.size):
        for k in range(8):
            d = (back + k) % 8
            ny, nx = cur[0] + _DIRS[d][0], cur[1] + _DIRS[d][1]
            if m[ny, nx]:
                # 下一輪從「找到它之前檢查的那個背景鄰居」開始掃，換算成從新像素看過去的方向
                by, bx = cur[0] + _DIRS[(d - 1) % 8][0], cur[1] + _DIRS[(d - 1) % 8][1]
                cur = (ny, nx)
                back = _DIRS.index((by - ny, bx - nx))
                break
        else:
            return pts   # 孤立的單一像素
        if cur == start:
            return pts
        pts.append(cur)
    return pts


def _simplify(pts: np.ndarray, eps: float) -> list[tuple[float, float]]:
    """Ramer–Douglas–Peucker：輪廓上千點 → 幾十點，SVG 才不會太肥。"""
    keep = np.zeros(len(pts), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        p, q = pts[a], pts[b]
        seg = q - p
        norm = float(np.hypot(*seg))
        rel = pts[a + 1:b] - p
        dist = np.abs(seg[0] * rel[:, 1] - seg[1] * rel[:, 0]) / norm if norm else np.hypot(rel[:, 0], rel[:, 1])
        i = int(np.argmax(dist))
        if dist[i] > eps:
            keep[a + 1 + i] = True
            stack += [(a, a + 1 + i), (a + 1 + i, b)]
    return [tuple(p) for p in pts[keep]]
