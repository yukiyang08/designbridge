"""合成平面圖驗證門的幾何偵測：兩間房隔一道牆，牆上留缺口，缺口旁畫門板加四分之一弧線。"""
import math

from PIL import Image, ImageDraw

from designbridge.layout.floorplan_openings import detect_doors
from designbridge.layout.floorplan_upload_plan import _pretrim_boxes


def _plan(tmp_path, with_door=True):
    im = Image.new("L", (1240, 800), 255)
    d = ImageDraw.Draw(im)
    d.rectangle([100, 80, 1140, 720], outline=0, width=10)
    d.rectangle([615, 80, 625, 300], fill=0)
    d.rectangle([615, 390, 625, 720], fill=0)   # 牆中間留 y 300~390 的缺口（0.9 m @ 0.01 m/px）
    if with_door:
        d.line([(620, 300), (530, 300)], fill=0, width=1)   # 門板
        d.line([(620 - 90 * math.sin(math.radians(t)), 300 + 90 * math.cos(math.radians(t)))
                for t in range(0, 91, 2)], fill=0, width=1)   # 弧線
    path = tmp_path / "plan.png"
    im.save(path)
    return str(path)


def _rooms():
    box = lambda x0, x1: [[x0, 0.1], [x1, 0.1], [x1, 0.9], [x0, 0.9]]
    return [{"polygon": box(0.08, 0.5)}, {"polygon": box(0.5, 0.92)}]


def test_door_found_and_swing_side(tmp_path):
    doors = detect_doors(_plan(tmp_path), _rooms(), 0.01)
    assert len(doors) == 1
    d = doors[0]
    assert d["orientation"] == "vertical" and d["swing"] == 0   # 弧線畫在左邊那間
    assert abs(d["cx"] - 0.5) < 0.03 and abs(d["width"] * 800 - 90) < 10


def test_opening_without_arc_is_not_a_door(tmp_path):
    assert detect_doors(_plan(tmp_path, with_door=False), _rooms(), 0.01) == []


def test_pretrim_min_dim_scales_with_image_width():
    # 兩間房外框重疊：圖很寬時，縮開後各自仍要保有下限邊長，不被誤縮成細條
    rooms = [{"x": 0.0, "y": 0.0, "w": 0.6, "h": 1.0, "polygon": [[0, 0], [0.6, 0], [0.6, 1], [0, 1]]},
             {"x": 0.5, "y": 0.0, "w": 0.5, "h": 1.0, "polygon": [[0.5, 0], [1, 0], [1, 1], [0.5, 1]]}]
    a, b = _pretrim_boxes(rooms, (12.0, 8.0))
    assert a[2] <= b[0] + 1e-6
