"""在任何一張圖上搬家具：選取、透視縮放、搬移後只重畫舊位置與新位置邊緣。離線，假的 SAM 2 與 inpaint。"""
import numpy as np
import pytest
from PIL import Image

from designbridge.render import image_move as im


@pytest.fixture
def room(tmp_path):
    """灰色房間，左下有一塊紅色「家具」（x 20–60、y 60–90）。"""
    arr = np.full((100, 200, 3), 128, np.uint8)
    arr[60:90, 20:60] = (220, 30, 30)
    p = tmp_path / "room.png"
    Image.fromarray(arr).save(p)
    return p


def _red_seg(path, xy):
    a = np.asarray(Image.open(path).convert("RGB"))
    m = (a[..., 0] > 200) & (a[..., 1] < 60)
    return m if m[int(xy[1]), int(xy[0])] else np.zeros(a.shape[:2], bool)


def test_pick_returns_layer_bbox_and_floor_anchor(room, tmp_path):
    hit = im.pick(str(room), 40 / 200, 75 / 100, tmp_path / "out", segment=_red_seg)
    assert hit and Image.open(hit["layer_path"]).mode == "RGBA"
    assert hit["bbox"]["x0"] < 0.11 and hit["bbox"]["x1"] > 0.29
    assert hit["anchor"]["y"] == pytest.approx(0.92, abs=0.03)     # 家具底部（含外擴 2px）
    assert hit["horizon_y"] < hit["anchor"]["y"]


def test_pick_misses_background_or_whole_wall(room, tmp_path):
    assert im.pick(str(room), 0.9, 0.2, tmp_path, segment=_red_seg) is None
    whole = lambda p, xy: np.ones((100, 200), bool)                 # 切到整片牆：不算家具
    assert im.pick(str(room), 0.5, 0.5, tmp_path, segment=whole) is None


def test_perspective_scale_smaller_when_dragged_toward_horizon():
    assert im.perspective_scale(0.9, 0.9, 0.45) == pytest.approx(1.0)
    assert im.perspective_scale(0.9, 0.675, 0.45) == pytest.approx(0.5)
    assert im.perspective_scale(0.9, 0.2, 0.45) == pytest.approx(0.2)   # 拖過地平線：夾在下限


def test_move_repaints_only_old_spot_and_new_edges(room, tmp_path):
    hit = im.pick(str(room), 40 / 200, 75 / 100, tmp_path / "out", segment=_red_seg)
    seen = {}

    def fake_inpaint(image_path, mask, prompt, out_path):
        seen["mask"] = np.asarray(mask) > 127
        Image.open(image_path).convert("RGB").point(lambda v: v).save(out_path)
        # 模擬補背景：把要重畫的地方塗回牆色
        a = np.asarray(Image.open(out_path)).copy()
        a[seen["mask"]] = 128
        Image.fromarray(a).save(out_path)
        return True

    out = im.move(str(room), hit["mask_path"], (150 / 200, hit["anchor"]["y"]), hit["horizon_y"],
                  tmp_path / "moved.png", fake_inpaint)
    a = np.asarray(Image.open(out).convert("RGB"))
    assert tuple(a[75, 40]) == (128, 128, 128)          # 舊位置補成背景
    assert tuple(a[75, 150]) == (220, 30, 30)           # 新位置有家具，本體是原像素
    assert seen["mask"][75, 40] and not seen["mask"][75, 150] and not seen["mask"][10, 100]


def test_move_raises_when_inpaint_fails(room, tmp_path):
    hit = im.pick(str(room), 40 / 200, 75 / 100, tmp_path / "out", segment=_red_seg)
    with pytest.raises(RuntimeError):
        im.move(str(room), hit["mask_path"], (0.7, 0.9), 0.45, tmp_path / "m.png", lambda *a: False)
