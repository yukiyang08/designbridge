"""局部編輯：fal 修圖成功時寫入結果圖、失敗時回報失敗（不能回傳原圖當成功）。離線，假的 fal 與下載。"""
import sys
from types import SimpleNamespace

import pytest
from PIL import Image

from designbridge.core.config import Config
from designbridge.render import inpaint


@pytest.fixture
def files(tmp_path, monkeypatch):
    img = tmp_path / "in.png"
    Image.new("RGB", (32, 32), "white").save(img)
    mask = Image.new("L", (32, 32), 255)
    monkeypatch.setattr(Config, "FAL_KEY", "fake")
    monkeypatch.setitem(sys.modules, "fal_client", SimpleNamespace())
    return str(img), mask, tmp_path / "out" / "result.png"


def _fal(monkeypatch, result=None, exc=None):
    def fake(*_a, **_k):
        if exc:
            raise exc
        return result
    monkeypatch.setattr("designbridge.core.timing.fal_subscribe", fake)


def test_success_downloads_result_with_requests(files, monkeypatch):
    img, mask, out = files
    _fal(monkeypatch, {"images": [{"url": "https://fal/x.png"}]})
    monkeypatch.setattr("requests.get", lambda url, timeout: SimpleNamespace(
        content=b"RESULT", raise_for_status=lambda: None))
    assert inpaint.run_fal_inpainting(img, mask, "p", out) is True
    assert out.read_bytes() == b"RESULT"


def test_fal_error_reports_failure_and_writes_nothing(files, monkeypatch):
    img, mask, out = files
    _fal(monkeypatch, exc=RuntimeError("quota exceeded"))
    assert inpaint.run_fal_inpainting(img, mask, "p", out) is False
    assert not out.exists()


def test_no_images_reports_failure(files, monkeypatch):
    img, mask, out = files
    _fal(monkeypatch, {"images": []})
    assert inpaint.run_fal_inpainting(img, mask, "p", out) is False
    assert not out.exists()


def test_download_error_reports_failure(files, monkeypatch):
    img, mask, out = files
    _fal(monkeypatch, {"images": [{"url": "https://fal/x.png"}]})

    def boom(*_a, **_k):
        raise RuntimeError("CERTIFICATE_VERIFY_FAILED")
    monkeypatch.setattr("requests.get", boom)
    assert inpaint.run_fal_inpainting(img, mask, "p", out) is False
