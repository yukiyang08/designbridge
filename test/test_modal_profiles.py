"""DESIGNBRIDGE_MODAL_MODE：部署參數（profiles.resolve）與後端執行時預設值（Config）。"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "modal_flux"))
import profiles  # noqa: E402


def test_resolve_modes(monkeypatch):
    monkeypatch.delenv("DESIGNBRIDGE_MODAL_GPU", raising=False)
    monkeypatch.delenv("DESIGNBRIDGE_MODAL_MODE", raising=False)
    assert profiles.resolve() == {"gpu": "L40S", "scaledown": 60}
    monkeypatch.setenv("DESIGNBRIDGE_MODAL_MODE", "dev")
    assert profiles.resolve() == {"gpu": "L40S", "scaledown": 60}
    monkeypatch.setenv("DESIGNBRIDGE_MODAL_MODE", "demo")
    assert profiles.resolve() == {"gpu": "H100!", "scaledown": 600}
    monkeypatch.setenv("DESIGNBRIDGE_MODAL_GPU", "A100-80GB")  # bench 臨時換 GPU
    assert profiles.resolve() == {"gpu": "A100-80GB", "scaledown": 600}


def _config(mode=None):
    e = {k: v for k, v in os.environ.items() if k != "DESIGNBRIDGE_MODAL_MODE"}
    e["PYTHONUTF8"] = "1"
    if mode:
        e["DESIGNBRIDGE_MODAL_MODE"] = mode
    code = (
        "import dotenv; dotenv.load_dotenv = lambda *a, **k: False; "  # 不讀專案 .env，測試才不受本機設定影響
        "from designbridge.core.config import Config as C; print(C.USE_MODAL_GPU, C.MODAL_WARMUP)"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=e, capture_output=True, text=True).stdout.split()
    return tuple(out[-2:])


def test_config_follows_mode():
    assert _config() == ("False", "off")  # 沒設任何變數 = 全走 fal
    assert _config("off") == ("False", "off")
    assert _config("dev") == ("True", "off")
    assert _config("demo") == ("True", "studio")


def test_warmup_follows_config(monkeypatch):
    from designbridge.core.config import Config
    from designbridge.render import render_backends as rb

    spawned: list[str] = []

    class _Fake:
        def __init__(self, mode):
            self.info = type("I", (), {"spawn": staticmethod(lambda: spawned.append(mode))})

    monkeypatch.setattr(rb, "_modal_renderer", lambda app, mode: _Fake(mode))
    monkeypatch.setattr(Config, "MODAL_WARMUP_MODES", "union")

    monkeypatch.setattr(Config, "USE_MODAL_GPU", False)
    assert rb.warmup_modal_gpu("studio") == []                     # 沒開 Modal
    monkeypatch.setattr(Config, "USE_MODAL_GPU", True)
    monkeypatch.setattr(Config, "MODAL_WARMUP", "off")
    assert rb.warmup_modal_gpu("studio") == []                     # dev：不暖機
    monkeypatch.setattr(Config, "MODAL_WARMUP", "studio")
    assert rb.warmup_modal_gpu("startup") == []                    # 時機不對
    assert rb.warmup_modal_gpu("studio") == ["union"] and spawned == ["union"]
