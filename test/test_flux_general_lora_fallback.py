from __future__ import annotations

import sys
from types import SimpleNamespace

from designbridge.core.config import Config
from designbridge.render.render_backends import _render_flux_controlnet_depth_fal


def test_retries_flux_general_without_lora_after_lora_download_error(tmp_path, monkeypatch):
    depth_path = tmp_path / "depth.png"
    depth_path.write_bytes(b"depth")
    output_path = tmp_path / "render.png"
    calls = []

    def subscribe(model, *, arguments, with_logs):
        calls.append((model, arguments, with_logs))
        if "loras" in arguments:
            raise RuntimeError(
                "[{'loc': ['body', 'loras.0'], 'type': 'file_download_error'}]"
            )
        return {"images": [{"url": "https://example.test/render.png"}]}

    fake_fal_client = SimpleNamespace(
        upload=lambda data, content_type: "https://example.test/depth.png",
        subscribe=subscribe,
    )
    monkeypatch.setitem(sys.modules, "fal_client", fake_fal_client)
    monkeypatch.setattr(Config, "FAL_KEY", "test-key")

    import requests

    class FakeResponse:
        content = b"rendered image"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(requests, "get", lambda url, timeout: FakeResponse())

    succeeded = _render_flux_controlnet_depth_fal(
        "A furnished room",
        str(depth_path),
        output_path,
        loras=[{"path": "https://example.test/style.safetensors", "scale": 0.8}],
    )

    assert succeeded
    assert len(calls) == 2
    assert all(model == "fal-ai/flux-general" for model, _, _ in calls)
    first_arguments, retry_arguments = calls[0][1], calls[1][1]
    assert "loras" in first_arguments
    assert "loras" not in retry_arguments
    assert retry_arguments["controlnets"] == first_arguments["controlnets"]
    assert retry_arguments["controlnets"][0]["control_image_url"] == "https://example.test/depth.png"
    assert output_path.read_bytes() == b"rendered image"

    calls.clear()
    second_output_path = tmp_path / "render_second.png"
    assert _render_flux_controlnet_depth_fal(
        "A furnished room",
        str(depth_path),
        second_output_path,
        loras=[{"path": "https://example.test/style.safetensors", "scale": 0.8}],
    )
    assert len(calls) == 1
    assert "loras" not in calls[0][1]
    assert calls[0][1]["controlnets"][0]["control_image_url"] == "https://example.test/depth.png"