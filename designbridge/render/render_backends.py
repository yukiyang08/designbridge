# designbridge/render_backends.py
"""Image generation backend implementations: HF Inference, Kontext, local Flux."""

from __future__ import annotations

import threading
from pathlib import Path

from designbridge.core.config import Config

# ── Model caches (loaded once, reused) ────────────────────────────────────────

_fal_unavailable_loras: set[tuple[tuple[str, str], ...]] = set()
_fal_unavailable_loras_lock = threading.Lock()

# fal.ai's fixed named image-size presets (its API enum, not a tunable value).
_FAL_SIZE_MAP: dict[tuple[int, int], str] = {
    (1024, 1024): "square_hd",
    (512, 512): "square",
    (1024, 768): "landscape_4_3",
    (768, 1024): "portrait_4_3",
    (1280, 720): "landscape_16_9",
    (720, 1280): "portrait_16_9",
}


def _depth_instruction(depth_conditioning_scale: float) -> str:
    """Phrase how strongly the Kontext prompt should follow the depth map."""
    if depth_conditioning_scale >= 0.75:
        return "strictly preserve the spatial layout, depth structure, camera angle and perspective"
    if depth_conditioning_scale >= 0.45:
        return "generally follow the spatial layout and camera perspective"
    return "use as loose spatial reference"


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
        from designbridge.core.timing import fal_subscribe
        import requests
        import os

        os.environ["FAL_KEY"] = fal_key

        print(f"☁️  fal.ai {model} 推理中...")

        width, height = output_size
        image_size = _FAL_SIZE_MAP.get((width, height), {"width": width, "height": height})

        result = fal_subscribe("flux_txt2img",
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

        depth_instruction = _depth_instruction(depth_conditioning_scale)

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
        from designbridge.core.timing import fal_subscribe
        import requests
        import os

        os.environ["FAL_KEY"] = fal_key

        print("☁️  fal.ai FLUX Kontext + depth LoRA 推理中...")

        with open(depth_path, "rb") as f:
            depth_url = fal_client.upload(f.read(), content_type="image/png")

        depth_instruction = _depth_instruction(depth_conditioning_scale)

        width, height = output_size
        image_size = _FAL_SIZE_MAP.get((width, height), {"width": width, "height": height})

        full_prompt = f"redepthkontext {prompt}, {depth_instruction}"
        print(f"[kontext] prompt preview: {full_prompt[:120]}")
        print(f"[kontext] lora scale: {depth_conditioning_scale}")

        result = fal_subscribe("kontext",
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


def _render_flux_controlnet_depth_fal(
    prompt: str,
    depth_path: str,
    out_path: Path,
    conditioning_scale: float = 0.7,
    control_end: float = 1.0,
    num_steps: int = 28,
    guidance_scale: float = 3.5,
    output_size: tuple[int, int] = (1024, 1024),
    extra_controls: list[dict] | None = None,
    loras: list[dict] | None = None,
    controlnet_model: str | None = None,
    seed: int | None = None,
) -> bool:
    """Generate image via fal.ai FLUX-general + a true depth ControlNet.

    Unlike the Kontext depth-fusion LoRA (loose "reference depth"), a real depth
    ControlNet enforces the depth map's geometry much more strictly — so the
    scene-graph projected depth actually constrains furniture placement in the render.

    conditioning_scale: 0.0 = ignore depth, ~1.0 = strongly follow depth geometry.

    control_end (0..1): end depth control partway through denoising — structure locks
    in during the early steps, then the model freely resolves materials for the rest.
    Flat/low-variance regions of the depth map (a far wall, mostly featureless) give the
    model almost nothing to anchor on; controlling them for every single step leaves no
    room to resolve that into a real material, so it renders noise instead. Same fix
    already used on the layout branch (`_render_flux_depth_controlnet_fal`'s
    `depth_control_end`). 1.0 = control the whole run (old behaviour).

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
        from designbridge.core.timing import fal_subscribe
        import requests
        import os

        os.environ["FAL_KEY"] = fal_key

        print("☁️  fal.ai FLUX-general + Depth ControlNet 推理中...")

        with open(depth_path, "rb") as f:
            depth_url = fal_client.upload(f.read(), content_type="image/png")

        width, height = output_size
        image_size = _FAL_SIZE_MAP.get((width, height), {"width": width, "height": height})

        model_id = controlnet_model or Config.DEPTH_CONTROLNET_MODEL
        print(f"[controlnet] model: {model_id}  scale: {conditioning_scale}  end: {control_end}")

        controlnets: list[dict] = [
            {
                "path": model_id,
                "control_image_url": depth_url,
                "conditioning_scale": conditioning_scale,
                "start_percentage": 0.0,
                "end_percentage": control_end,
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
                "start_percentage": 0.0,
                "end_percentage": control_end,
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
        if seed is not None:
            arguments["seed"] = int(seed)
        lora_signature = tuple(sorted(
            (str(lora.get("path", "")), str(lora.get("scale", 1)))
            for lora in (loras or [])
        ))
        with _fal_unavailable_loras_lock:
            skip_known_unavailable_lora = bool(lora_signature) and lora_signature in _fal_unavailable_loras

        if loras and not skip_known_unavailable_lora:
            arguments["loras"] = loras
            print(f"[lora] {', '.join(l['path'].rsplit('/', 1)[-1] for l in loras)}")
        elif skip_known_unavailable_lora:
            print("[lora] 已知 fal 無法下載此 LoRA，略過並保留深度 ControlNet")

        try:
            result = fal_subscribe("controlnet_depth",
                "fal-ai/flux-general",
                arguments=arguments,
                with_logs=False,
            )
        except Exception as e:
            error_text = str(e).lower()
            if not loras or "file_download_error" not in error_text or "loras" not in error_text:
                raise

            with _fal_unavailable_loras_lock:
                _fal_unavailable_loras.add(lora_signature)
            print("⚠️  fal.ai 無法下載 LoRA 權重，保留深度 ControlNet 並移除 LoRA 重試")
            retry_arguments = dict(arguments)
            retry_arguments.pop("loras", None)
            result = fal_subscribe("controlnet_depth_retry",
                "fal-ai/flux-general",
                arguments=retry_arguments,
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
    loras: list[dict] | None = None,
    seed: int | None = None,
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
        from designbridge.core.timing import fal_subscribe
        import requests

        os.environ["FAL_KEY"] = fal_key

        print("☁️  fal.ai FLUX-general + ControlNet Union 推理中...")

        with open(depth_path, "rb") as f:
            depth_url = fal_client.upload(f.read(), content_type="image/png")

        width, height = output_size
        image_size = _FAL_SIZE_MAP.get((width, height), {"width": width, "height": height})

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
        if seed is not None:
            arguments["seed"] = int(seed)   # 同 seed + 同條件圖 → 換風格時構圖大致不變
        if loras:
            arguments["loras"] = loras
            print(f"[lora] {', '.join(l['path'].rsplit('/', 1)[-1] for l in loras)}")
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

        result = fal_subscribe("controlnet_union",
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



def _fal_flux_general(endpoint: str, arguments: dict) -> bytes:
    import fal_client
    import requests

    result = fal_client.subscribe(endpoint, arguments=arguments, with_logs=False)
    resp = requests.get(result["images"][0]["url"], timeout=60)
    resp.raise_for_status()
    return resp.content


def _render_product_mesh_fal(
    prompt: str,
    color_path: str,
    product_mask_path: str,
    depth_path: str,
    out_path: Path,
    *,
    room_strength: float = 1.0,
    harmonize_strength: float = 0.3,
    depth_conditioning_scale: float = 0.6,
    num_steps: int = 28,
    guidance_scale: float = 3.5,
    output_size: tuple[int, int] = (1024, 1024),
    loras: list[dict] | None = None,
    seed: int | None = None,
) -> bool:
    """IKEA 商品網格的彩色投影當底圖：家具像素不重繪，只生成房間，再整張低強度補光影。

    兩段都掛同一張深度圖當 ControlNet，房間結構與家具位置不會漂。
    """
    fal_key = Config.FAL_KEY
    if not fal_key:
        return False
    try:
        import io
        import os

        import fal_client
        from PIL import Image, ImageFilter

        os.environ["FAL_KEY"] = fal_key

        def _upload(img: "Image.Image") -> str:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return fal_client.upload(buf.getvalue(), content_type="image/png")

        color = Image.open(color_path).convert("RGB").resize(output_size, Image.LANCZOS)
        product = Image.open(product_mask_path).convert("L").resize(output_size, Image.NEAREST)
        # 白 = 重繪。家具邊緣內縮 2px 一起重繪，接縫與接觸陰影才融得進去
        repaint = Image.eval(product.filter(ImageFilter.MinFilter(5)), lambda p: 255 - p)
        depth = Image.open(depth_path).convert("L").resize(output_size, Image.LANCZOS)

        color_url, mask_url, depth_url = _upload(color), _upload(repaint), _upload(depth)
        width, height = output_size
        common: dict = {
            "prompt": prompt,
            "num_inference_steps": num_steps,
            "guidance_scale": guidance_scale,
            "image_size": _FAL_SIZE_MAP.get((width, height), {"width": width, "height": height}),
            "controlnet_unions": [{
                "path": Config.FAL_DEPTH_CONTROLNET_MODEL,
                "controls": [{
                    "control_image_url": depth_url,
                    "control_mode": Config.FAL_DEPTH_CONTROL_MODE,
                    "conditioning_scale": depth_conditioning_scale,
                    "start_percentage": 0.0,
                    "end_percentage": 1.0,
                }],
            }],
        }
        if seed is not None:
            common["seed"] = int(seed)
        if loras:
            common["loras"] = loras

        print(f"☁️  fal.ai 商品網格 → 房間 inpaint（strength={room_strength}）")
        room_bytes = _fal_flux_general("fal-ai/flux-general/inpainting", {
            **common, "image_url": color_url, "mask_url": mask_url, "strength": room_strength,
        })

        out_path.parent.mkdir(parents=True, exist_ok=True)
        if harmonize_strength > 0:
            print(f"☁️  fal.ai 整張光影融合 img2img（strength={harmonize_strength}）")
            room_url = fal_client.upload(room_bytes, content_type="image/png")
            final_bytes = _fal_flux_general("fal-ai/flux-general/image-to-image", {
                **common, "image_url": room_url, "strength": harmonize_strength,
            })
            out_path.with_name(out_path.stem + "_room.png").write_bytes(room_bytes)
        else:
            final_bytes = room_bytes
        out_path.write_bytes(final_bytes)
        print(f"✅ fal.ai 商品網格渲染完成：{out_path.name}")
        return True
    except ImportError:
        print("⚠️  fal_client 未安裝，請執行：pip install fal-client")
        return False
    except Exception as e:
        import traceback

        print(f"⚠️  fal.ai 商品網格渲染失敗：{e}")
        traceback.print_exc()
        return False
