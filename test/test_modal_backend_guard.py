"""Modal 後端的守門邏輯：不碰網路，只驗證「不該走 Modal 的情況一律回 False（讓 renderer 退回 fal）」。"""

from pathlib import Path

from designbridge.core.config import Config
from designbridge.render import render_backends as rb

_NORDIC_LORA = [{"path": "https://huggingface.co/x/y/resolve/main/flux1dev/designbridge_v5_flux1dev_nordic.safetensors", "scale": 1.0}]
_EDGE = {"path": rb._MODAL_EDGE_CN, "image_path": "edge.png", "scale": 0.3, "mode": None}


def _call(monkeypatch, **kw):
    monkeypatch.setattr(Config, "USE_MODAL_GPU", kw.pop("flag", True))
    return rb._render_flux_controlnet_depth_modal("p", "depth.png", Path("out.png"), **kw)


def test_flag_off_returns_false(monkeypatch):
    assert _call(monkeypatch, flag=False) is False


def test_unsupported_depth_model_returns_false(monkeypatch):
    assert _call(monkeypatch, controlnet_model="Shakker-Labs/FLUX.1-dev-ControlNet-Union-Pro") is False


def test_unsupported_edge_model_returns_false(monkeypatch):
    assert _call(monkeypatch, extra_controls=[{**_EDGE, "path": "other/canny"}]) is False


def test_unknown_lora_returns_false(monkeypatch):
    assert _call(monkeypatch, loras=[{"path": "https://example.com/custom.safetensors", "scale": 1.0}]) is False
    assert _call(monkeypatch, loras=_NORDIC_LORA * 2) is False


def test_modal_failure_returns_false(monkeypatch, tmp_path):
    """modal 沒裝或應用不存在時，不丟例外，回 False 讓上層退回 fal。"""
    monkeypatch.setattr(Config, "USE_MODAL_GPU", True)
    monkeypatch.setattr(Config, "MODAL_APP_NAME", "app-that-does-not-exist-xyz")
    depth = tmp_path / "d.png"
    depth.write_bytes(b"x")
    assert rb._render_flux_controlnet_depth_modal("p", str(depth), tmp_path / "o.png", loras=_NORDIC_LORA) is False


def _union(monkeypatch, **kw):
    monkeypatch.setattr(Config, "USE_MODAL_GPU", kw.pop("flag", True))
    return rb._render_flux_depth_controlnet_modal("p", "depth.png", Path("out.png"), **kw)


def test_union_flag_off_returns_false(monkeypatch):
    assert _union(monkeypatch, flag=False) is False


def test_union_unsupported_model_or_mode_returns_false(monkeypatch):
    monkeypatch.setattr(Config, "FAL_DEPTH_CONTROLNET_MODEL", "other/union")
    assert _union(monkeypatch) is False
    monkeypatch.setattr(Config, "FAL_DEPTH_CONTROLNET_MODEL", rb._MODAL_UNION_CN)
    monkeypatch.setattr(Config, "FAL_DEPTH_CONTROL_MODE", "pose")
    assert _union(monkeypatch) is False


def test_union_unknown_lora_returns_false(monkeypatch):
    monkeypatch.setattr(Config, "FAL_DEPTH_CONTROLNET_MODEL", rb._MODAL_UNION_CN)
    monkeypatch.setattr(Config, "FAL_DEPTH_CONTROL_MODE", "depth")
    assert _union(monkeypatch, loras=[{"path": "https://example.com/custom.safetensors"}]) is False


def test_modal_lora_parsing():
    assert rb._modal_lora(None) == (True, None, 1.0)
    assert rb._modal_lora(_NORDIC_LORA) == (True, "nordic", 1.0)
    assert rb._modal_lora([{"path": "x/custom.safetensors"}])[0] is False


def test_timing_detail_marks_cold_start():
    assert rb._modal_timing_detail({"cold_start": True, "load_seconds": 23.4, "generate_seconds": 9.3}) == "冷啟動｜載入模型 23.4s、算圖 9.3s"
    assert rb._modal_timing_detail({"cold_start": False, "generate_seconds": 3.2}) == "暖機｜算圖 3.2s"
    assert rb._modal_timing_detail({"generate_seconds": 3.2}) == "算圖 3.2s"  # 舊版部署沒有旗標就不標註
