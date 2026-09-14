# designbridge/render_backends.py
"""Image generation backend implementations: HF Inference, Kontext, FLUX Redux, IP-Adapter, local Flux."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from designbridge.core.config import Config

# ── Model caches (loaded once, reused) ────────────────────────────────────────

_flux_pipeline: Any = None
_flux_redux_prior: Any = None
_flux_redux_pipe: Any = None


# ── Pipeline loaders ──────────────────────────────────────────────────────────

def _get_flux_pipeline():
    """Load Flux.1 pipeline once and cache it."""
    global _flux_pipeline
    if _flux_pipeline is not None:
        return _flux_pipeline
    from diffusers import FluxPipeline
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    kwargs: dict[str, Any] = {
        "torch_dtype": torch.bfloat16 if device == "cuda" else torch.float32,
    }
    if Config.HF_TOKEN:
        kwargs["token"] = Config.HF_TOKEN
    _flux_pipeline = FluxPipeline.from_pretrained(Config.FLUX_MODEL, **kwargs).to(device)
    return _flux_pipeline


def _get_flux_redux_pipelines():
    """Load FLUX.1-Redux prior + FLUX.1-dev backbone once and cache them.
    CPU 推理非常慢（30 分鐘以上 / 張），建議有 GPU 再用。
    需要 HF_TOKEN 且已接受 black-forest-labs/FLUX.1-dev 授權。
    """
    global _flux_redux_prior, _flux_redux_pipe
    if _flux_redux_prior is not None and _flux_redux_pipe is not None:
        return _flux_redux_prior, _flux_redux_pipe

    from diffusers import FluxPriorReduxPipeline, FluxPipeline
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if device == "cuda" else torch.float32

    # CPU 模式明確指定 device_map=None，避免 accelerate 用 meta tensor 初始化
    # 造成後續 .to() / enable_sequential_cpu_offload() 失敗
    load_kwargs: dict = {"torch_dtype": dtype}
    if device == "cpu":
        load_kwargs["device_map"] = None

    print("⏳ 載入 FLUX.1-Redux prior（首次約需數分鐘下載）...")
    _flux_redux_prior = FluxPriorReduxPipeline.from_pretrained(
        "black-forest-labs/FLUX.1-Redux-dev",
        **load_kwargs,
    )

    print("⏳ 載入 FLUX.1-dev backbone（含文字編碼器，支援 prompt + 風格圖）...")
    _flux_redux_pipe = FluxPipeline.from_pretrained(
        "black-forest-labs/FLUX.1-dev",
        **load_kwargs,
    )

    if device == "cuda":
        # GPU 模式：model cpu offload 讓各層推理完即釋放 VRAM，峰值從 ~50GB 降到約 8-12GB
        _flux_redux_prior.enable_model_cpu_offload()
        _flux_redux_pipe.enable_model_cpu_offload()
    else:
        print("⚠️  CPU 模式：推理速度極慢，每張可能需要 30 分鐘以上")

    print("✅ FLUX.1-Redux 載入完成")
    return _flux_redux_prior, _flux_redux_pipe


# ── Cloud backends ─────────────────────────────────────────────────────────────

def _render_hf_inference(
    prompt: str,
    out_path: Path,
    model: str = "",
    output_size: tuple[int, int] = (1024, 1024),
) -> bool:
    """Generate image via Hugging Face Inference API. No local model download."""
    import secrets

    api_key = Config.HF_TOKEN
    if not api_key:
        return False
    try:
        from huggingface_hub import InferenceClient

        client = InferenceClient(
            provider=Config.HF_INFERENCE_PROVIDER,
            api_key=api_key,
        )
        seed = secrets.randbelow(2**31)
        print(f"🎲 HF Inference seed: {seed}")
        width, height = output_size
        image = client.text_to_image(
            prompt,
            model=model,
            seed=seed,
            width=width,
            height=height,
        )
        if image is None:
            return False
        out_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(str(out_path))
        return True
    except Exception as e:
        import traceback
        print(f"⚠️  HF Inference render failed ({type(e).__name__}: {e})")
        traceback.print_exc()
        return False


def _render_flux_fal(
    prompt: str,
    out_path: Path,
    model: str = "fal-ai/flux/schnell",
    num_steps: int = 4,
    output_size: tuple[int, int] = (1024, 1024),
) -> bool:
    """Generate image via fal.ai FLUX text-to-image (cloud, no style/depth reference needed)."""
    fal_key = Config.FAL_KEY
    if not fal_key:
        return False
    try:
        import fal_client
        import requests
        import os

        os.environ["FAL_KEY"] = fal_key

        print(f"☁️  fal.ai {model} 推理中...")

        width, height = output_size
        size_map = {
            (1024, 1024): "square_hd",
            (512, 512): "square",
            (1024, 768): "landscape_4_3",
            (768, 1024): "portrait_4_3",
            (1280, 720): "landscape_16_9",
            (720, 1280): "portrait_16_9",
        }
        image_size = size_map.get((width, height), {"width": width, "height": height})

        result = fal_client.subscribe(
            model,
            arguments={
                "prompt": prompt,
                "image_size": image_size,
                "num_inference_steps": num_steps,
            },
            with_logs=False,
        )

        img_url = result["images"][0]["url"]
        resp = requests.get(img_url, timeout=60)
        resp.raise_for_status()

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(resp.content)
        print(f"✅ fal.ai {model} 完成：{out_path.name}")
        return True

    except ImportError:
        print("⚠️  fal_client 未安裝，請執行：pip install fal-client")
        return False
    except Exception as e:
        print(f"⚠️  fal.ai {model} 失敗：{e}")
        return False


def _render_hf_inference_redux(
    prompt: str,
    style_image_path: str,
    out_path: Path,
    output_size: tuple[int, int] = (1024, 1024),
) -> bool:
    """Generate image via FLUX.1-Redux-dev using a style reference image + text prompt."""
    api_key = Config.HF_TOKEN
    if not api_key:
        return False
    try:
        import base64
        import io
        import requests
        from PIL import Image

        style_img = Image.open(style_image_path).convert("RGB")
        buf = io.BytesIO()
        style_img.save(buf, format="JPEG", quality=90)
        image_bytes = buf.getvalue()
        width, height = output_size

        url = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-Redux-dev"
        auth_header = {"Authorization": f"Bearer {api_key}"}

        print(f"🎨 FLUX.1-Redux 風格參考生圖：{Path(style_image_path).name}")

        payload: dict = {
            "inputs": base64.b64encode(image_bytes).decode(),
            "parameters": {"width": width, "height": height},
        }
        if prompt.strip():
            payload["parameters"]["prompt"] = prompt.strip()

        response = requests.post(
            url,
            headers={**auth_header, "Content-Type": "application/json"},
            json=payload,
            timeout=120,
        )

        if response.status_code in (400, 422):
            print("⚠️  FLUX.1-Redux JSON payload 不支援，改用 raw image bytes")
            response = requests.post(
                url,
                headers={**auth_header, "Content-Type": "image/jpeg"},
                data=image_bytes,
                timeout=120,
            )

        if response.status_code != 200:
            print(f"⚠️  FLUX.1-Redux HTTP {response.status_code}: {response.text[:200]}")
            return False
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result_img = Image.open(io.BytesIO(response.content))
        result_img.save(str(out_path))
        return True
    except Exception as e:
        import traceback
        print(f"⚠️  FLUX.1-Redux render failed ({type(e).__name__}: {e})")
        traceback.print_exc()
        return False


def _render_hf_kontext(
    prompt: str,
    depth_path: str,
    out_path: Path,
    strength: float = 0.85,
    depth_conditioning_scale: float = 0.85,
) -> bool:
    """Generate image via Kontext LoRA using depth map as spatial reference through Replicate.

    strength is fixed high so the model runs enough denoising steps to produce a proper room image.
    depth_conditioning_scale controls how strongly the prompt instructs the model to follow the depth structure.
    """
    api_key = Config.HF_TOKEN
    if not api_key:
        return False
    try:
        from huggingface_hub import InferenceClient

        with open(depth_path, "rb") as f:
            input_image = f.read()

        if depth_conditioning_scale >= 0.75:
            depth_instruction = "strictly preserve the spatial layout, depth structure, camera angle and perspective"
        elif depth_conditioning_scale >= 0.45:
            depth_instruction = "generally follow the spatial layout and camera perspective"
        else:
            depth_instruction = "use as loose spatial reference"

        client = InferenceClient(
            provider=Config.KONTEXT_PROVIDER,
            api_key=api_key,
        )
        image = client.image_to_image(
            input_image,
            prompt=f"redepthkontext {prompt}, {depth_instruction}",
            model=Config.KONTEXT_LORA_MODEL,
            strength=strength,
        )
        if image is None:
            return False
        out_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(str(out_path))
        print(f"[kontext] Generated via {Config.KONTEXT_PROVIDER}")
        return True
    except Exception as e:
        import traceback
        print(f"⚠️  Kontext render failed ({type(e).__name__}: {e})")
        traceback.print_exc()
        return False


def _render_flux_kontext_fal(
    prompt: str,
    depth_path: str,
    out_path: Path,
    depth_conditioning_scale: float = 0.85,
    num_steps: int = 28,
    guidance_scale: float = 2.5,
    output_size: tuple[int, int] = (1024, 1024),
) -> bool:
    """Generate image via fal.ai FLUX Kontext + depth LoRA.

    depth_conditioning_scale controls both lora scale (structural weight)
    and prompt phrasing (how strongly to follow the depth map).
    """
    fal_key = Config.FAL_KEY
    if not fal_key:
        return False
    try:
        import fal_client
        import requests
        import os

        os.environ["FAL_KEY"] = fal_key

        print("☁️  fal.ai FLUX Kontext + depth LoRA 推理中...")

        with open(depth_path, "rb") as f:
            depth_url = fal_client.upload(f.read(), content_type="image/png")

        if depth_conditioning_scale >= 0.75:
            depth_instruction = "strictly preserve the spatial layout, depth structure, camera angle and perspective"
        elif depth_conditioning_scale >= 0.45:
            depth_instruction = "generally follow the spatial layout and camera perspective"
        else:
            depth_instruction = "use as loose spatial reference"

        width, height = output_size
        size_map = {
            (1024, 1024): "square_hd",
            (512, 512): "square",
            (1024, 768): "landscape_4_3",
            (768, 1024): "portrait_4_3",
            (1280, 720): "landscape_16_9",
            (720, 1280): "portrait_16_9",
        }
        image_size = size_map.get((width, height), {"width": width, "height": height})

        full_prompt = f"redepthkontext {prompt}, {depth_instruction}"
        print(f"[kontext] prompt preview: {full_prompt[:120]}")
        print(f"[kontext] lora scale: {depth_conditioning_scale}")

        result = fal_client.subscribe(
            "fal-ai/flux-kontext/dev",
            arguments={
                "prompt": full_prompt,
                "image_url": depth_url,
                "loras": [{
                    "path": "https://huggingface.co/thedeoxen/FLUX.1-Kontext-dev-reference-depth-fusion-LORA/resolve/main/LORA_flux_kontext_depth_reference_cotrol.safetensors",
                    "scale": depth_conditioning_scale,
                }],
                "num_inference_steps": num_steps,
                "guidance_scale": guidance_scale,
                "image_size": image_size,
            },
            with_logs=True,
        )
        logs = result.get("logs") or []
        for log in logs:
            print(f"[fal log] {log.get('message', '')}")

        img_url = result["images"][0]["url"]
        resp = requests.get(img_url, timeout=60)
        resp.raise_for_status()

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(resp.content)
        print(f"✅ fal.ai FLUX Kontext 完成：{out_path.name}")
        return True

    except ImportError:
        print("⚠️  fal_client 未安裝，請執行：pip install fal-client")
        return False
    except Exception as e:
        import traceback
        print(f"⚠️  fal.ai FLUX Kontext 失敗：{e}")
        traceback.print_exc()
        return False


def _render_flux_redux_fal(
    style_image_path: str,
    out_path: Path,
    prompt: str = "",
    num_steps: int = 28,
    guidance_scale: float = 3.5,
    output_size: tuple[int, int] = (1024, 1024),
) -> bool:
    """Generate image via fal.ai FLUX.1-Redux API (cloud, fast)."""
    fal_key = Config.FAL_KEY
    if not fal_key:
        return False
    try:
        import fal_client
        import requests
        import os

        os.environ["FAL_KEY"] = fal_key

        print("☁️  fal.ai FLUX.1-Redux 推理中...")

        with open(style_image_path, "rb") as f:
            image_url = fal_client.upload(f.read(), content_type="image/jpeg")

        width, height = output_size
        size_map = {
            (1024, 1024): "square_hd",
            (512, 512): "square",
            (1024, 768): "landscape_4_3",
            (768, 1024): "portrait_4_3",
            (1280, 720): "landscape_16_9",
            (720, 1280): "portrait_16_9",
        }
        image_size = size_map.get((width, height), {"width": width, "height": height})

        arguments: dict = {
            "image_url": image_url,
            "num_inference_steps": num_steps,
            "guidance_scale": guidance_scale,
            "image_size": image_size,
        }
        if prompt.strip():
            arguments["prompt"] = prompt.strip()

        result = fal_client.subscribe(
            "fal-ai/flux-1/dev/redux",
            arguments=arguments,
            with_logs=False,
        )

        img_url = result["images"][0]["url"]
        resp = requests.get(img_url, timeout=60)
        resp.raise_for_status()

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(resp.content)
        print(f"✅ fal.ai FLUX.1-Redux 完成：{out_path.name}")
        return True

    except ImportError:
        print("⚠️  fal_client 未安裝，請執行：pip install fal-client")
        return False
    except Exception as e:
        print(f"⚠️  fal.ai FLUX.1-Redux 失敗：{e}")
        return False


def _render_flux_controlnet_depth_fal(
    prompt: str,
    depth_path: str,
    out_path: Path,
    conditioning_scale: float = 0.7,
    num_steps: int = 28,
    guidance_scale: float = 3.5,
    output_size: tuple[int, int] = (1024, 1024),
    extra_controls: list[dict] | None = None,
) -> bool:
    """Generate image via fal.ai FLUX-general + a true depth ControlNet.

    Unlike the Kontext depth-fusion LoRA (loose "reference depth"), a real depth
    ControlNet enforces the depth map's geometry much more strictly — so the
    scene-graph projected depth actually constrains furniture placement in the render.

    conditioning_scale: 0.0 = ignore depth, ~1.0 = strongly follow depth geometry.

    extra_controls: further ControlNets stacked on the same call, each
    `{"path", "image_path", "scale", "mode"}` (`mode` only for union-style models).
    Used to add the segmentation-derived boundary condition, which supplies the hard
    edges depth cannot. A failure to upload one of these is not fatal — the render
    proceeds on whatever conditions did upload.
    """
    fal_key = Config.FAL_KEY
    if not fal_key:
        return False
    if not prompt.strip():
        print("⚠️  fal.ai depth ControlNet 需要文字 prompt 描述目標空間")
        return False
    try:
        import fal_client
        import requests
        import os

        os.environ["FAL_KEY"] = fal_key

        print("☁️  fal.ai FLUX-general + Depth ControlNet 推理中...")

        with open(depth_path, "rb") as f:
            depth_url = fal_client.upload(f.read(), content_type="image/png")

        width, height = output_size
        size_map = {
            (1024, 1024): "square_hd",
            (512, 512): "square",
            (1024, 768): "landscape_4_3",
            (768, 1024): "portrait_4_3",
            (1280, 720): "landscape_16_9",
            (720, 1280): "portrait_16_9",
        }
        image_size = size_map.get((width, height), {"width": width, "height": height})

        print(f"[controlnet] model: {Config.DEPTH_CONTROLNET_MODEL}  scale: {conditioning_scale}")

        controlnets: list[dict] = [
            {
                "path": Config.DEPTH_CONTROLNET_MODEL,
                "control_image_url": depth_url,
                "conditioning_scale": conditioning_scale,
            }
        ]

        for control in extra_controls or []:
            image_path = str(control.get("image_path") or "")
            path = str(control.get("path") or "")
            if not image_path or not path or not Path(image_path).is_file():
                continue
            try:
                with open(image_path, "rb") as f:
                    control_url = fal_client.upload(f.read(), content_type="image/png")
            except Exception as e:
                print(f"⚠️  條件圖上傳失敗（{Path(image_path).name}: {e}），略過該 ControlNet")
                continue
            entry: dict = {
                "path": path,
                "control_image_url": control_url,
                "conditioning_scale": float(control.get("scale", 0.5)),
            }
            mode = control.get("mode")
            if mode not in (None, ""):
                entry["control_mode"] = int(mode)
            controlnets.append(entry)
            print(f"[controlnet] + {path}  scale: {entry['conditioning_scale']}")

        arguments: dict = {
            "prompt": prompt.strip(),
            "num_inference_steps": num_steps,
            "guidance_scale": guidance_scale,
            "image_size": image_size,
            "controlnets": controlnets,
        }

        result = fal_client.subscribe(
            "fal-ai/flux-general",
            arguments=arguments,
            with_logs=False,
        )

        img_url = result["images"][0]["url"]
        resp = requests.get(img_url, timeout=60)
        resp.raise_for_status()

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(resp.content)
        print(f"✅ fal.ai FLUX Depth ControlNet 完成：{out_path.name}")
        return True

    except ImportError:
        print("⚠️  fal_client 未安裝，請執行：pip install fal-client")
        return False
    except Exception as e:
        import traceback
        print(f"⚠️  fal.ai FLUX Depth ControlNet 失敗：{e}")
        traceback.print_exc()
        return False


def _render_flux_ipadapter_fal(
    style_image_path: str,
    out_path: Path,
    prompt: str,
    ip_adapter_scale: float = 0.6,
    num_steps: int = 28,
    guidance_scale: float = 3.5,
    output_size: tuple[int, int] = (1024, 1024),
) -> bool:
    """Generate image via fal.ai FLUX-general + XLabs IP-Adapter.

    Text prompt controls room type; style reference image controls visual style.
    ip_adapter_scale: 0.0 = ignore image, 1.0 = full style transfer.
    """
    fal_key = Config.FAL_KEY
    if not fal_key:
        return False
    if not prompt.strip():
        print("⚠️  fal.ai IP-Adapter 需要文字 prompt 描述目標空間")
        return False
    try:
        import fal_client
        import requests
        import os

        os.environ["FAL_KEY"] = fal_key

        print("☁️  fal.ai FLUX-general + IP-Adapter 推理中...")

        with open(style_image_path, "rb") as f:
            image_url = fal_client.upload(f.read(), content_type="image/jpeg")

        width, height = output_size
        size_map = {
            (1024, 1024): "square_hd",
            (512, 512): "square",
            (1024, 768): "landscape_4_3",
            (768, 1024): "portrait_4_3",
            (1280, 720): "landscape_16_9",
            (720, 1280): "portrait_16_9",
        }
        image_size = size_map.get((width, height), {"width": width, "height": height})

        arguments: dict = {
            "prompt": prompt.strip(),
            "num_inference_steps": num_steps,
            "guidance_scale": guidance_scale,
            "image_size": image_size,
            "ip_adapters": [
                {
                    "path": "XLabs-AI/flux-ip-adapter",
                    "weight_name": "ip_adapter.safetensors",
                    "image_encoder_path": "openai/clip-vit-large-patch14",
                    "image_url": image_url,
                    "scale": ip_adapter_scale,
                }
            ],
        }

        result = fal_client.subscribe(
            "fal-ai/flux-general",
            arguments=arguments,
            with_logs=False,
        )

        img_url = result["images"][0]["url"]
        resp = requests.get(img_url, timeout=60)
        resp.raise_for_status()

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(resp.content)
        print(f"✅ fal.ai FLUX IP-Adapter 完成：{out_path.name}")
        return True

    except ImportError:
        print("⚠️  fal_client 未安裝，請執行：pip install fal-client")
        return False
    except Exception as e:
        print(f"⚠️  fal.ai FLUX IP-Adapter 失敗：{e}")
        return False


def _render_flux_depth_controlnet_fal(
    prompt: str,
    depth_path: str,
    out_path: Path,
    *,
    edge_path: str | None = None,
    edge_conditioning_scale: float = 0.55,
    negative_prompt: str = "",
    conditioning_scale: float = 0.7,
    depth_control_end: float = 1.0,
    edge_control_end: float = 1.0,
    num_steps: int = 28,
    guidance_scale: float = 3.5,
    output_size: tuple[int, int] = (1024, 1024),
) -> bool:
    """Generate via fal.ai FLUX-general + a FLUX ControlNet Union.

    Feeds an eye-level depth map (from ``layout_projection.render_layout_depth_map``)
    so the render honors the 2D floor-plan furniture layout. ``conditioning_scale``
    controls how strictly the geometry is followed (0 = ignore, ~1 = strict).

    ``depth_control_end`` / ``edge_control_end`` (0..1) end each control partway
    through denoising — the structure is fixed in the early steps, then the model
    freely resolves materials and realistic detail. 1.0 = control the whole run.

    When ``edge_path`` is given, a Canny edge map is added as a SECOND control on the
    same Union model. Edges don't fade with distance, so this locks the position of
    far/back-wall furniture that the depth map alone renders as near-black (invisible).
    """
    fal_key = Config.FAL_KEY
    if not fal_key:
        return False
    try:
        import os

        import fal_client
        import requests

        os.environ["FAL_KEY"] = fal_key

        print("☁️  fal.ai FLUX-general + ControlNet Union 推理中...")

        with open(depth_path, "rb") as f:
            depth_url = fal_client.upload(f.read(), content_type="image/png")

        width, height = output_size
        size_map = {
            (1024, 1024): "square_hd",
            (512, 512): "square",
            (1024, 768): "landscape_4_3",
            (768, 1024): "portrait_4_3",
            (1280, 720): "landscape_16_9",
            (720, 1280): "portrait_16_9",
        }
        image_size = size_map.get((width, height), {"width": width, "height": height})

        # FLUX ControlNet Union on fal uses the `controlnet_unions` schema; each entry
        # in `controls` selects a modality via a string `control_mode`. We can stack a
        # Canny edge control (distance-independent placement) + a depth control
        # (3D structure) on the SAME Union model.
        controls: list[dict] = []
        if edge_path and os.path.isfile(edge_path):
            with open(edge_path, "rb") as f:
                edge_url = fal_client.upload(f.read(), content_type="image/png")
            controls.append({
                "control_image_url": edge_url,
                "control_mode": "canny",
                "conditioning_scale": edge_conditioning_scale,
                "start_percentage": 0.0,
                "end_percentage": edge_control_end,
            })
        controls.append({
            "control_image_url": depth_url,
            "control_mode": Config.FAL_DEPTH_CONTROL_MODE,
            "conditioning_scale": conditioning_scale,
            "start_percentage": 0.0,
            "end_percentage": depth_control_end,
        })

        controlnet_union: dict = {
            "path": Config.FAL_DEPTH_CONTROLNET_MODEL,
            "controls": controls,
        }

        arguments: dict = {
            "prompt": prompt,
            "num_inference_steps": num_steps,
            "guidance_scale": guidance_scale,
            "image_size": image_size,
            "controlnet_unions": [controlnet_union],
        }
        # NOTE: negative_prompt is intentionally NOT sent. On fal, a ControlNet-Union
        # pipeline fails to load with a negative prompt via either NAG (default) or
        # real-CFG ("Could not load pipeline", HTTP 422). Undesired content is steered
        # out via positive phrasing in the prompt instead.
        if negative_prompt.strip():
            print("[controlnet] negative_prompt ignored (incompatible with ControlNet-Union on fal)")
        _modes = "+".join(c["control_mode"] for c in controls)
        print(f"[controlnet] model={Config.FAL_DEPTH_CONTROLNET_MODEL} "
              f"controls={_modes} depth_scale={conditioning_scale} edge_scale={edge_conditioning_scale} "
              f"depth_end={depth_control_end} edge_end={edge_control_end}")

        result = fal_client.subscribe(
            "fal-ai/flux-general",
            arguments=arguments,
            with_logs=True,
        )
        for log in (result.get("logs") or []):
            print(f"[fal log] {log.get('message', '')}")

        img_url = result["images"][0]["url"]
        resp = requests.get(img_url, timeout=60)
        resp.raise_for_status()

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(resp.content)
        print(f"✅ fal.ai FLUX depth-ControlNet 完成：{out_path.name}")
        return True

    except ImportError:
        print("⚠️  fal_client 未安裝，請執行：pip install fal-client")
        return False
    except Exception as e:
        import traceback

        print(f"⚠️  fal.ai FLUX depth-ControlNet 失敗：{e}")
        traceback.print_exc()
        return False


def _render_flux_img2img_fal(
    prompt: str,
    init_path: str,
    out_path: Path,
    *,
    strength: float = 0.65,
    num_steps: int = 40,
    guidance_scale: float = 3.5,
    output_size: tuple[int, int] = (1024, 1024),
) -> bool:
    """Refine a material block-out into a photorealistic render via fal FLUX img2img.

    ``strength`` is the denoise amount: LOW (~0.5) keeps furniture positions almost
    exactly (precise coords, less texture); HIGH (~0.85) adds realism but drifts. This
    is the precision↔realism slider — the block-out fixes WHERE things are, img2img
    fills in materials/lighting.
    """
    fal_key = Config.FAL_KEY
    if not fal_key:
        return False
    try:
        import os

        import fal_client
        import requests

        os.environ["FAL_KEY"] = fal_key

        with open(init_path, "rb") as f:
            init_url = fal_client.upload(f.read(), content_type="image/png")

        width, height = output_size
        size_map = {
            (1024, 1024): "square_hd", (512, 512): "square",
            (1024, 768): "landscape_4_3", (768, 1024): "portrait_4_3",
            (1280, 720): "landscape_16_9", (720, 1280): "portrait_16_9",
        }
        image_size = size_map.get((width, height), {"width": width, "height": height})

        print(f"☁️  fal.ai FLUX img2img 推理中... (strength={strength})")
        result = fal_client.subscribe(
            "fal-ai/flux/dev/image-to-image",
            arguments={
                "prompt": prompt,
                "image_url": init_url,
                "strength": strength,
                "num_inference_steps": num_steps,
                "guidance_scale": guidance_scale,
                "image_size": image_size,
            },
            with_logs=True,
        )
        img_url = result["images"][0]["url"]
        resp = requests.get(img_url, timeout=60)
        resp.raise_for_status()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(resp.content)
        print(f"✅ fal.ai FLUX img2img 完成：{out_path.name}")
        return True

    except ImportError:
        print("⚠️  fal_client 未安裝，請執行：pip install fal-client")
        return False
    except Exception as e:
        import traceback

        print(f"⚠️  fal.ai FLUX img2img 失敗：{e}")
        traceback.print_exc()
        return False


# ── Local backends ─────────────────────────────────────────────────────────────

def _render_flux_redux_local(
    style_image_path: str,
    out_path: Path,
    prompt: str = "",
    num_steps: int = 4,
    guidance_scale: float = 3.5,
    output_size: tuple[int, int] = (512, 512),
    text_weight: float = 0.35,
) -> bool:
    """Generate image via local FLUX.1-Redux pipeline using a style reference image + text prompt.

    text_weight: 0.0 = pure image style, 1.0 = pure text direction.
    """
    try:
        from PIL import Image
        import torch

        pipe_prior, pipe = _get_flux_redux_pipelines()
        style_img = Image.open(style_image_path).convert("RGB")
        width, height = output_size
        print(f"🎨 FLUX.1-Redux 本地推理中（{width}×{height}，steps={num_steps}）...")

        prior_out = pipe_prior(style_img)

        pipe_kwargs: dict = {
            "guidance_scale": guidance_scale,
            "num_inference_steps": num_steps,
            "height": height,
            "width": width,
            **prior_out,
        }

        if prompt.strip() and text_weight > 0.0 and pipe.text_encoder is not None:
            clip_inputs = pipe.tokenizer(
                [prompt.strip()],
                padding="max_length",
                max_length=77,
                truncation=True,
                return_tensors="pt",
            )
            with torch.no_grad():
                text_pooled = pipe.text_encoder(
                    clip_inputs.input_ids.to(pipe.text_encoder.device),
                    output_hidden_states=False,
                ).pooler_output

            image_pooled = prior_out.get("pooled_prompt_embeds")
            if image_pooled is not None and text_weight < 1.0:
                pipe_kwargs["pooled_prompt_embeds"] = (
                    (1.0 - text_weight) * image_pooled + text_weight * text_pooled
                )
            else:
                pipe_kwargs["pooled_prompt_embeds"] = text_pooled

            print(f"   文字語意注入 text_weight={text_weight}：{prompt[:60]}...")

        result = pipe(**pipe_kwargs).images[0]

        out_path.parent.mkdir(parents=True, exist_ok=True)
        result.save(str(out_path))
        return True
    except Exception as e:
        err = str(e)
        if "GatedRepo" in err or "local cache" in err or "connection" in err.lower():
            print(f"⚠️  FLUX.1-Redux 無法載入（模型未下載或授權未接受）：{err[:120]}")
            print("    → 請至 https://huggingface.co/black-forest-labs/FLUX.1-Redux-dev 接受授權後重試")
        else:
            import traceback
            print(f"⚠️  FLUX.1-Redux 本地推理失敗：{e}")
            traceback.print_exc()
        return False


def _render_flux(prompt: str, out_path: Path) -> bool:
    """Generate image with local Flux pipeline. Returns True on success."""
    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        steps = Config.FLUX_STEPS
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pipe = _get_flux_pipeline()
        generator = torch.Generator(device=device).manual_seed(torch.randint(0, 2**32, (1,)).item())
        image = pipe(
            prompt=prompt,
            num_inference_steps=steps,
            guidance_scale=0.0,
            generator=generator,
        ).images[0]
        image.save(str(out_path))
        return True
    except Exception as e:
        import traceback
        print(f"⚠️ Render failed ({type(e).__name__}: {e})")
        traceback.print_exc()
        return False
