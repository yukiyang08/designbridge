"""局部修改／擴圖走自架 Fill dev：成功就不碰 fal，失敗或未開啟一律退回 fal。離線，假的 Modal 與 fal。"""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from designbridge.core.config import Config
from designbridge.render import inpaint
from designbridge.render import render_backends as rb

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def files(tmp_path, monkeypatch):
    img = tmp_path / "in.png"
    Image.new("RGB", (64, 32), "white").save(img)
    mask = Image.new("L", (64, 32), 0)
    mask.paste(255, (0, 0, 32, 32))
    monkeypatch.setattr(Config, "FAL_KEY", "fake")
    monkeypatch.setitem(sys.modules, "fal_client", SimpleNamespace())
    return str(img), mask, tmp_path / "out" / "result.png"


def _fal(monkeypatch, calls):
    def fake(label, *_a, **_k):
        calls.append(label)
        return {"images": [{"url": "https://fal/x.png"}]}
    monkeypatch.setattr("designbridge.core.timing.fal_subscribe", fake)
    monkeypatch.setattr("requests.get", lambda url, timeout: SimpleNamespace(
        content=b"FAL", raise_for_status=lambda: None))


def _modal(monkeypatch, enabled=True, result="red"):
    monkeypatch.setattr(Config, "USE_MODAL_EDIT", enabled)
    seen = []

    def fake(image, mask, prompt, **kw):
        seen.append(kw)
        return Image.new("RGB", image.size, result) if result else None
    monkeypatch.setattr(rb, "modal_fill", fake)
    return seen


def test_inpaint_uses_modal_and_skips_fal(files, monkeypatch):
    img, mask, out = files
    fal_calls = []
    _fal(monkeypatch, fal_calls)
    seen = _modal(monkeypatch)
    assert inpaint.run_fal_inpainting(img, mask, "p", out, num_steps=50) is True
    assert fal_calls == []
    assert seen[0]["steps"] == 50 and seen[0]["guidance"] == Config.FAL_INPAINT_DEV_GUIDANCE
    assert Image.open(out).getpixel((5, 5)) == (255, 0, 0)


def test_inpaint_falls_back_to_fal_when_modal_fails(files, monkeypatch):
    img, mask, out = files
    fal_calls = []
    _fal(monkeypatch, fal_calls)
    _modal(monkeypatch, result=None)
    assert inpaint.run_fal_inpainting(img, mask, "p", out) is True
    assert fal_calls == ["inpaint"] and out.read_bytes() == b"FAL"


def test_inpaint_flag_off_never_calls_modal(files, monkeypatch):
    img, mask, out = files
    _fal(monkeypatch, [])
    seen = _modal(monkeypatch, enabled=False)
    assert inpaint.run_fal_inpainting(img, mask, "p", out) is True
    assert seen == []


def test_outpaint_uses_modal_and_keeps_unmasked_canvas(files, monkeypatch, tmp_path):
    _, mask, _ = files
    fal_calls = []
    _fal(monkeypatch, fal_calls)
    _modal(monkeypatch)
    canvas = Image.new("RGB", (64, 32), (0, 0, 255))
    merged = inpaint.run_fal_outpainting(canvas, mask, "p", out_dir=tmp_path / "dbg")
    assert fal_calls == []
    assert merged.getpixel((5, 16)) == (255, 0, 0)      # 遮罩內：重畫的內容
    assert merged.getpixel((60, 16)) == (0, 0, 255)     # 遮罩外：原畫布
    assert (tmp_path / "dbg" / "outpaint_merged.png").exists()


def test_modal_fill_off_or_unavailable_returns_none(monkeypatch):
    img, mask = Image.new("RGB", (32, 32)), Image.new("L", (32, 32))
    monkeypatch.setattr(Config, "USE_MODAL_EDIT", False)
    assert rb.modal_fill(img, mask, "p", steps=4, guidance=30) is None
    monkeypatch.setattr(Config, "USE_MODAL_EDIT", True)
    monkeypatch.setattr(Config, "MODAL_EDIT_APP_NAME", "app-that-does-not-exist-xyz")
    assert rb.modal_fill(img, mask, "p", steps=4, guidance=30) is None


def _fill_module():
    spec = importlib.util.spec_from_file_location("fill_inference", ROOT / "scripts/modal_flux/fill_inference.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_fill_helpers_fit16_and_paste_back():
    fi = _fill_module()
    assert fi.fit16((1200, 675)) == (1200, 672) and fi.fit16((10, 10)) == (16, 16)
    original = Image.new("RGB", (40, 20), "blue")
    mask = Image.new("L", (40, 20), 0)
    mask.paste(255, (0, 0, 20, 20))
    out = fi.paste_back(original, Image.new("RGB", (32, 16), "red"), mask)
    assert out.size == (40, 20) and out.getpixel((5, 5)) == (255, 0, 0) and out.getpixel((35, 5)) == (0, 0, 255)
