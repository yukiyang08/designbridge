"""CubiCasa 牆線遮罩：停用或缺權重時退回規則式；外部遮罩尺寸不同也能切。離線。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import designbridge.layout.cubicasa_walls as cw
from designbridge.core.config import Config
from designbridge.layout.floorplan_segment import segment_rooms


@pytest.fixture(autouse=True)
def _fresh_model_state(monkeypatch):
    monkeypatch.setattr(cw, "_model", None)
    monkeypatch.setattr(cw, "_unavailable", False)


def _two_rooms(tmp_path: Path) -> tuple[Path, np.ndarray, np.ndarray]:
    """空心雙線牆的兩房圖（規則式只認實心牆，抓不到）＋同一張圖一半解析度的牆／屋外遮罩。"""
    W, H = 1200, 800
    im = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(im)
    for box in ((200, 150, 1000, 650), (214, 164, 986, 636)):   # 外牆：兩條細線
        d.rectangle(box, outline=0, width=2)
    d.line((600, 150, 600, 380), fill=0, width=2)   # 隔牆，門洞 y=380..430
    d.line((614, 150, 614, 380), fill=0, width=2)
    d.line((600, 430, 600, 650), fill=0, width=2)
    d.line((614, 430, 614, 650), fill=0, width=2)
    path = tmp_path / "hollow.png"
    im.save(path)

    wall = Image.new("L", (W // 2, H // 2), 0)
    dw = ImageDraw.Draw(wall)
    dw.rectangle((100, 75, 500, 325), outline=255, width=7)
    dw.rectangle((300, 75, 307, 190), fill=255)
    dw.rectangle((300, 215, 307, 325), fill=255)
    outside = Image.new("L", (W // 2, H // 2), 255)
    ImageDraw.Draw(outside).rectangle((100, 75, 500, 325), fill=0)
    return path, np.array(wall) > 0, np.array(outside) > 0


def test_external_masks_of_other_size_split_hollow_walls(tmp_path):
    path, wall, outside = _two_rooms(tmp_path)
    seeds = [{"room_type": "bedroom", "label": "臥室", "point": [500, 330]},
             {"room_type": "living_room", "label": "客廳", "point": [500, 670]}]
    rooms = segment_rooms(str(path), [dict(s) for s in seeds], wall_mask=wall, outside_mask=outside)
    assert sorted(r["label"] for r in rooms or []) == ["客廳", "臥室"]
    assert wall.shape == (400, 600)   # 呼叫端的遮罩不被改動


def test_disabled_flag_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "ENABLE_CUBICASA_WALLS", False)
    path, _, _ = _two_rooms(tmp_path)
    assert cw.predict_masks(str(path)) is None


def test_missing_weights_falls_back_once(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "ENABLE_CUBICASA_WALLS", True)
    monkeypatch.setattr(Config, "CUBICASA_WEIGHTS", str(tmp_path / "missing.pt"))
    path, _, _ = _two_rooms(tmp_path)
    assert cw.predict_masks(str(path)) is None
    assert cw._unavailable   # 記住失敗，之後不再每張重試載入


@pytest.mark.skipif(not (Path(__file__).resolve().parent.parent / Config.CUBICASA_WEIGHTS).is_file(),
                    reason="沒有 CubiCasa 權重（scripts/fetch_cubicasa_weights.py）")
def test_real_model_returns_masks(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "ENABLE_CUBICASA_WALLS", True)
    path, _, _ = _two_rooms(tmp_path)
    wall, outside = cw.predict_masks(str(path))
    assert wall.shape == outside.shape == (800, 1200)
    assert wall.any() and outside.any()
