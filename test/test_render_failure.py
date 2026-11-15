"""生成失敗不能偽裝成功：照片流程不退到純文字出圖、全失敗回 502、深度 0.0 不被當成沒給值。"""

import importlib
from types import SimpleNamespace

import pytest
from PIL import Image

from designbridge.core.config import Config
# nodes/__init__ 匯出同名函式 renderer，會蓋掉模組，要用 import_module 拿模組本身
rn = importlib.import_module("designbridge.core.nodes.renderer")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setattr(Config, "FAL_KEY", "x")
    monkeypatch.setattr(Config, "HF_TOKEN", "x")
    monkeypatch.setattr(Config, "ENABLE_HF_INFERENCE", True)
    monkeypatch.setattr(Config, "ENABLE_PRODUCT_MESHES", False)
    monkeypatch.setattr(Config, "STYLE_SWAP_DEPTH_LOCK", False)
    monkeypatch.setattr(Config, "USE_MODAL_GPU", False)
    monkeypatch.setattr(rn, "resolve_style_loras", lambda *_: [])
    calls: list[str] = []
    monkeypatch.setattr(rn, "_render_hf_inference", lambda *a, **k: calls.append("hf_text") or False)
    monkeypatch.setattr(rn, "_render_flux_fal", lambda *a, **k: calls.append("fal_text") or False)
    photo = tmp_path / "photo.png"
    Image.new("RGB", (64, 48), "white").save(photo)
    return SimpleNamespace(tmp=tmp_path, photo=str(photo), calls=calls)


def _state(**user_input):
    return {"task_id": "t", "composed_prompt": "a cozy room", "user_input": {"text_prompt": "x", **user_input}}


def test_photo_flow_never_falls_back_to_text_only(env):
    out = rn.renderer(_state(initial_image=env.photo))
    assert env.calls == []
    assert out["render_result"]["generation_params"]["render_error"]


def test_text_flow_still_uses_text_fallback(env):
    rn.renderer(_state())
    assert env.calls == ["hf_text", "fal_text"]


def test_zero_depth_scale_is_weakest_lock_not_default(env, monkeypatch):
    depth = env.tmp / "depth.png"
    Image.new("L", (64, 48), 128).save(depth)
    seen = {}

    def _fake_cn(prompt, depth_path, out_path, **kw):
        seen["scale"] = kw["conditioning_scale"]
        return True

    monkeypatch.setattr(Config, "LAYOUT_DEPTH_CONTROL_BACKEND", "controlnet")
    monkeypatch.setattr(rn, "_render_flux_controlnet_depth_fal", _fake_cn)
    state = _state(initial_image=env.photo)
    state["structured_requirement"] = {"depth_conditioning_scale": 0.0}
    state["vision_features"] = {"depth": str(depth)}
    rn.renderer(state)
    assert seen["scale"] == pytest.approx(0.20)


def test_generate_returns_502_when_render_failed(monkeypatch):
    from fastapi.testclient import TestClient

    import api
    from routers import generate as gen
    from routers.common import charge_credit, get_user_id

    failed = {"generated_image": "artifacts/render/missing.png",
              "render_result": {"generation_params": {"backend": "placeholder", "render_error": "所有雲端後端皆失敗"}}}
    monkeypatch.setattr(gen, "_get_graph", lambda: SimpleNamespace(invoke=lambda state: failed))
    monkeypatch.setattr(gen, "_save_history", lambda *a, **k: pytest.fail("失敗結果不該存進歷史"))
    monkeypatch.setitem(api.app.dependency_overrides, get_user_id, lambda: "u1")
    monkeypatch.setitem(api.app.dependency_overrides, charge_credit, lambda: "u1")   # 不真的扣點
    res = TestClient(api.app).post("/api/generate", json={"text_prompt": "x"})
    assert res.status_code == 502
    assert "生成失敗" in res.json()["detail"]
