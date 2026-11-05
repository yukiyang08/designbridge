"""segment_rooms 的離線測試：用 PIL 畫一張合成平面圖（粗牆、門洞、細線窗），不需呼叫 Gemini。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from designbridge.layout.floorplan_segment import segment_rooms

W, H = 1200, 800
WALL = 14


def _plan(tmp_path: Path) -> Path:
    """三間房：左大房、右上小房、右下房；左右之間與右上右下之間各有一扇門，
    右下房外牆有一段細線窗（窗外是屋外，不能漏出去）。"""
    im = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(im)

    def wall(x0, y0, x1, y1):
        d.rectangle((x0, y0, x1, y1), fill=127, outline=0)

    # 外牆，右牆 y=450..650 留給窗
    wall(200, 150, 1000, 150 + WALL)
    wall(200, 650 - WALL, 1000, 650)
    wall(200, 150, 200 + WALL, 650)
    wall(1000 - WALL, 150, 1000, 450)
    wall(1000 - WALL, 600, 1000, 650)
    d.line((993, 450, 993, 600), fill=0, width=2)  # 窗：細線
    d.line((998, 450, 998, 600), fill=0, width=2)
    # 門寬 50px：以這棟約 13m×8m 的比例約 0.8m，接近實際門寬
    # 中間隔牆，門洞 y=380..430
    wall(600, 150, 600 + WALL, 380)
    wall(600, 430, 600 + WALL, 650)
    # 右側上下隔牆，門洞 x=700..750
    wall(600, 350, 700, 350 + WALL)
    wall(750, 350, 1000, 350 + WALL)
    # 家具細線：不該把房間切開
    d.rectangle((260, 220, 420, 420), outline=0, width=2)
    path = tmp_path / "plan.png"
    im.save(path)
    return path


def _pt(x, y):
    return [round(y / H * 1000), round(x / W * 1000)]


def _inside(room, x, y):
    """射線法判斷像素座標 (x, y) 是否在 room.polygon 內。"""
    poly = [(px * W, py * H) for px, py in room["polygon"]]
    hit = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            hit = not hit
    return hit


def test_segments_rooms_at_doors_and_keeps_outside_out(tmp_path):
    seeds = [
        {"label": "A", "room_type": "living_room", "point": _pt(400, 400)},
        {"label": "B", "room_type": "bedroom", "point": _pt(800, 250)},
        {"label": "C", "room_type": "study", "point": _pt(800, 500)},
        {"label": "outside", "room_type": "other", "point": _pt(80, 80)},
    ]
    rooms = segment_rooms(str(_plan(tmp_path)), seeds)
    assert rooms is not None
    by = {r["label"]: r for r in rooms}
    assert set(by) == {"A", "B", "C"}  # 屋外的點要被丟掉

    # 每間房包含自己的代表點，且不包含別間的
    probes = {"A": (300, 550), "B": (900, 230), "C": (900, 560)}
    for name, room in by.items():
        for other, (x, y) in probes.items():
            assert _inside(room, x, y) == (name == other), (name, other)

    # 窗是細線，C 不能經由窗漏到屋外
    assert by["C"]["x"] + by["C"]["w"] < 1010 / W
    # 錨點落在自己房內
    for room in rooms:
        ax, ay = room["anchor"]
        assert _inside(room, ax * W, ay * H)


def test_finds_rooms_by_geometry_without_usable_seeds(tmp_path):
    """Gemini 的點全落在屋外時，靠牆圍出的區塊自動補種子，三間房仍要切出來。"""
    seeds = [{"label": "outside", "room_type": "other", "point": _pt(80, 80)}]
    rooms = segment_rooms(str(_plan(tmp_path)), seeds)
    assert rooms is not None and len(rooms) == 3
    assert all(r["label"] == "" and r["room_type"] == "other" for r in rooms)
    for x, y in ((300, 550), (900, 230), (900, 560)):
        assert sum(_inside(r, x, y) for r in rooms) == 1


def test_transparent_background_reads_as_white(tmp_path):
    """透明底的 PNG：透明處要當白紙，不能變成黑色線條（跟 CubiCasa 的讀法一致）。"""
    from designbridge.layout.floorplan_segment import _work_gray

    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(im).rectangle((100, 100, 300, 300), fill=(0, 0, 0, 255))
    p = tmp_path / "transparent.png"
    im.save(p)
    g = _work_gray(str(p))
    assert g[5, 5] > 250 and g[g.shape[0] // 2, g.shape[1] - 5] > 250   # 透明處
    assert g.min() < 10                                                  # 黑框還在


def test_model_masks_finding_nothing_falls_back_to_rule_walls(tmp_path, monkeypatch):
    """CubiCasa 把整張判成屋外而切不出房間時，要改用規則式牆線重切，不是直接放棄。"""
    import designbridge.layout.cubicasa_walls as cw
    import designbridge.layout.floorplan_parse as fp

    p = _plan(tmp_path)
    everything_outside = (np.zeros((H, W), bool), np.ones((H, W), bool))
    monkeypatch.setattr(cw, "predict_masks", lambda _p: everything_outside)
    monkeypatch.setattr(fp, "_room_seeds", lambda _p: [])
    monkeypatch.setattr(fp, "_relabel_rooms", lambda *_a: None)
    assert segment_rooms(str(p), [], *everything_outside) is None
    rooms = fp._detect_rooms_by_segmentation(str(p))
    assert rooms and len(rooms) == 3


def test_cubicasa_masks_cached_per_image(tmp_path, monkeypatch):
    """同一張圖第二次辨識不重跑推論；內容不同才重跑。"""
    import designbridge.layout.cubicasa_walls as cw

    calls = []
    monkeypatch.setattr(cw, "load_model", lambda: object())
    monkeypatch.setattr(cw, "_predict", lambda _m, path: calls.append(path) or ("w", "o"))
    monkeypatch.setattr(cw, "_cache", type(cw._cache)())
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    Image.new("L", (10, 10), 255).save(a)
    Image.new("L", (10, 10), 0).save(b)
    assert cw.predict_masks(str(a)) == ("w", "o")
    cw.predict_masks(str(a))
    cw.predict_masks(str(b))
    assert calls == [str(a), str(b)]
