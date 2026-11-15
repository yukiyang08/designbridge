"""結果圖家具描邊：遮罩 → 輪廓多邊形，以及報價方框配到哪一塊遮罩。"""

from __future__ import annotations

import numpy as np

import designbridge.pricing.outlines as outlines
from designbridge.pricing.outlines import _polygon


def _rect_mask(h, w, y0, y1, x0, x1):
    m = np.zeros((h, w), dtype=bool)
    m[y0:y1, x0:x1] = True
    return m


def _bounds(poly):
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def test_rectangle_outline_hugs_the_edges_with_few_points():
    poly = _polygon(_rect_mask(100, 200, 20, 60, 40, 120))
    assert 4 <= len(poly) <= 12, "轉角磨圓多幾個點可以，但不能是一整串像素點"
    assert all(type(v) is float for p in poly for v in p), "要能直接回成 JSON（不能是 numpy float）"
    x0, y0, x1, y1 = _bounds(poly)
    # 貼著家具外緣（誤差不到兩個像素）
    assert abs(x0 - 40 / 200) < 2 / 200 and abs(x1 - 120 / 200) < 2 / 200
    assert abs(y0 - 20 / 100) < 2 / 100 and abs(y1 - 60 / 100) < 2 / 100


def test_l_shape_keeps_the_inner_corner():
    m = _rect_mask(100, 100, 10, 90, 10, 40) | _rect_mask(100, 100, 60, 90, 10, 90)
    poly = _polygon(m)
    # 凹進去的那個角（約在 x=40, y=60）不能被抹平成斜線
    assert any(abs(px - 0.4) < 0.04 and abs(py - 0.6) < 0.04 for px, py in poly)
    # 右上那塊空的地方不能被包進輪廓
    assert not any(px > 0.5 and py < 0.5 for px, py in poly)


def test_holes_are_filled_and_only_the_biggest_piece_is_traced():
    m = _rect_mask(100, 100, 10, 90, 10, 90)
    m[40:60, 40:60] = False            # 中間的洞（茶几的鏤空）不另外描
    m |= _rect_mask(100, 100, 95, 98, 95, 98)   # 角落的小碎塊不算
    poly = _polygon(m)
    x0, y0, x1, y1 = _bounds(poly)
    assert x1 <= 0.91 and y1 <= 0.91, "小碎塊不能被包進來"
    assert not any(0.35 < px < 0.65 and 0.35 < py < 0.65 for px, py in poly), "洞不描"


def test_boxes_match_their_own_mask_and_unmatched_fall_back_to_none(monkeypatch):
    sofa = _rect_mask(100, 100, 60, 95, 5, 45)
    lamp_shade = _rect_mask(100, 100, 25, 47, 80, 90)
    insts = [
        {"mask": sofa, "bbox": [5, 60, 45, 95]},
        {"mask": lamp_shade, "bbox": [80, 25, 90, 47]},
    ]
    monkeypatch.setattr(outlines, "_sam_outlines", lambda path, boxes: None)   # 測沒有 SAM 2 時的退路
    monkeypatch.setattr(
        "designbridge.render.furniture_instances.segment_furniture", lambda path: insts, raising=False,
    )
    boxes = [
        [0.04, 0.58, 0.47, 0.97],   # 沙發：框跟遮罩幾乎一樣
        [0.78, 0.0, 0.92, 0.47],    # 吊燈：框連吊線一起框，遮罩只有燈罩
        [0.55, 0.6, 0.7, 0.9],      # 地毯：沒有對應的遮罩
    ]
    out = outlines.furniture_outlines("x.png", boxes)
    assert out[0] is not None and out[1] is not None
    assert out[2] is None


def test_a_mask_is_given_to_only_one_box(monkeypatch):
    chair = _rect_mask(100, 100, 50, 80, 50, 70)
    monkeypatch.setattr(outlines, "_sam_outlines", lambda path, boxes: None)   # 測沒有 SAM 2 時的退路
    monkeypatch.setattr(
        "designbridge.render.furniture_instances.segment_furniture",
        lambda path: [{"mask": chair, "bbox": [50, 50, 70, 80]}], raising=False,
    )
    # 同款兩件但框重複：第二件沿用方框，不會兩件描同一個輪廓
    out = outlines.furniture_outlines("x.png", [[0.5, 0.5, 0.7, 0.8], [0.5, 0.5, 0.7, 0.8]])
    assert sum(o is not None for o in out) == 1


def test_sam_prefers_the_whole_object_among_equally_confident_masks():
    from designbridge.pricing.outlines import _whole_object
    part = _rect_mask(50, 50, 10, 30, 10, 30)            # 只有沙發本體
    whole = part | _rect_mask(50, 50, 10, 20, 30, 40)    # 連上面的毯子
    tiny = _rect_mask(50, 50, 12, 14, 12, 14)
    masks = np.stack([part, whole, tiny])
    assert _whole_object(masks, np.array([0.95, 0.90, 0.97])) is not None
    assert _whole_object(masks, np.array([0.95, 0.90, 0.97])).sum() == whole.sum()
    # 整件的分數差太多就不硬選它
    assert _whole_object(masks, np.array([0.95, 0.60, 0.80])).sum() == part.sum()


def test_small_notches_are_closed_and_corners_rounded():
    m = _rect_mask(120, 120, 20, 100, 20, 100)
    m[20:24, 55:59] = False            # 邊上 4px 的小缺口（毯子沒切進去那種）
    poly = _polygon(m)
    top = [p for p in poly if p[1] < 30 / 120]
    assert all(p[1] < 23 / 120 for p in top), "小缺口要被補平，不能在輪廓上留一個凹口"
    assert len(poly) > 4, "轉角要磨圓，不是四個直角"
