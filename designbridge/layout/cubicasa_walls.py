"""用 CubiCasa5K 模型預測平面圖的牆與屋外，交給 floorplan_segment 切房間；房名、類型仍由 Gemini 給。

規則式牆線只認實心深色牆，空心雙線牆、細線隔間、彩色牆都抓不到；換成模型預測後，台灣圖的
房間數完全正確率約為原本的 2 倍（test/FLOORPLAN_SEGMENTATION_EXPERIMENT.md）。
停用、缺權重或推論失敗時回 None，呼叫端退回規則式。
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from pathlib import Path

import numpy as np
from PIL import Image

from designbridge.core.config import Config

_ROOT = Path(__file__).resolve().parents[2]
# 實驗用的輸入長邊；降到 1000 推論只快約 1 秒，結果卻變不穩
_INPUT_SIDE = 1300
# 輸出 44 通道：21 張牆角熱圖、12 類房間、11 類符號；房間類別 0 背景、2 牆、8 欄杆
_ROOM_CH = slice(21, 33)
_BACKGROUND, _WALL, _RAILING = 0, 2, 8

_lock = threading.Lock()
_model = None
_device = "cpu"
_unavailable = False
# 一次只跑一個推論：CPU 上並行不會比較快，只會讓記憶體成倍上升
_infer_lock = threading.Lock()
# 同一張圖重新辨識不重跑推論；遮罩約 1300² 布林，16 張不到 60 MB
_CACHE_SIZE = 16
_cache: OrderedDict = OrderedDict()


def load_model():
    """延遲載入、只載一次；失敗記下來不重試，之後都走規則式。"""
    global _model, _device, _unavailable
    if _model is not None or _unavailable or not Config.ENABLE_CUBICASA_WALLS:
        return _model
    with _lock:
        if _model is None and not _unavailable:
            try:
                import torch

                from designbridge.layout.cubicasa_model import hg_furukawa_original

                path = Path(Config.CUBICASA_WEIGHTS)
                path = path if path.is_absolute() else _ROOT / path
                model = hg_furukawa_original(n_classes=44)
                model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
                _device = "cuda" if torch.cuda.is_available() else "cpu"
                _model = model.eval().to(_device)
            except Exception as e:  # noqa: BLE001
                _unavailable = True
                print(f"⚠️  CubiCasa 模型載入失敗，平面圖改用規則式牆線：{e}")
    return _model


def predict_masks(image_path: str) -> tuple[np.ndarray, np.ndarray] | None:
    """回傳 (wall, outside) 布林遮罩，解析度為模型輸入（長邊最多 _INPUT_SIDE）；不可用時回 None。"""
    model = load_model()
    if model is None:
        return None
    try:
        key = hashlib.sha256(Path(image_path).read_bytes()).hexdigest()
    except OSError:
        return None
    with _infer_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
        masks = _predict(model, image_path)
        if masks is not None:
            _cache[key] = masks
            if len(_cache) > _CACHE_SIZE:
                _cache.popitem(last=False)
        return masks


def _predict(model, image_path: str) -> tuple[np.ndarray, np.ndarray] | None:
    try:
        import torch
        import torch.nn.functional as F

        with Image.open(image_path) as im:
            rgba = im.convert("RGBA")
        rgb = Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba).convert("RGB")
        s = _INPUT_SIDE / max(rgb.size)
        if s < 1:
            rgb = rgb.resize((round(rgb.width * s), round(rgb.height * s)))
        x = torch.from_numpy(np.asarray(rgb, dtype=np.float32)).permute(2, 0, 1)[None] / 127.5 - 1
        h, w = x.shape[2:]
        # 補到 64 的倍數，hourglass 上下採樣後尺寸才對得上
        x = F.pad(x, (0, (-w) % 64, 0, (-h) % 64), value=1.0)
        with torch.no_grad():
            pred = model(x.to(_device))
        pred = F.interpolate(pred, size=x.shape[2:], mode="bilinear", align_corners=False)
        cls = pred[0, _ROOM_CH, :h, :w].argmax(0).cpu().numpy()
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  CubiCasa 推論失敗，這張改用規則式牆線：{e}")
        return None
    return (cls == _WALL) | (cls == _RAILING), cls == _BACKGROUND
