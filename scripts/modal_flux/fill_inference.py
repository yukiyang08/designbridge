"""FLUX.1 Fill dev 推論（局部修改、擴圖）。不含平台專屬程式，Modal / RunPod 共用。

參數對應 fal-ai/flux-lora-fill：guidance 約 30，遮罩外貼回原圖（paste_back）。
"""

from __future__ import annotations

import io
import time

FILL_MODEL = "black-forest-labs/FLUX.1-Fill-dev"


def paste_back(original, painted, mask):
    """遮罩外還原原圖像素：整張圖過一次 VAE 會讓沒改的地方變糊。"""
    from PIL import Image

    painted = painted.convert("RGB").resize(original.size, Image.LANCZOS)
    return Image.composite(painted, original.convert("RGB"), mask.convert("L").resize(original.size, Image.NEAREST))


def fit16(size: tuple[int, int]) -> tuple[int, int]:
    """FLUX 的寬高要是 16 的倍數。"""
    w, h = size
    return max(16, w // 16 * 16), max(16, h // 16 * 16)


class FluxFiller:
    def __init__(self, device: str = "cuda") -> None:
        import torch
        from diffusers import FluxFillPipeline

        self.device = device
        t0 = time.time()
        self.pipe = FluxFillPipeline.from_pretrained(FILL_MODEL, torch_dtype=torch.bfloat16).to(device)
        self.load_seconds = round(time.time() - t0, 1)

    def fill(
        self,
        prompt: str,
        image_png: bytes,
        mask_png: bytes,
        *,
        steps: int = 28,
        guidance: float = 30.0,
        seed: int | None = None,
    ) -> dict:
        import torch
        from PIL import Image

        image = Image.open(io.BytesIO(image_png)).convert("RGB")
        mask = Image.open(io.BytesIO(mask_png)).convert("L").resize(image.size, Image.NEAREST)
        w, h = fit16(image.size)
        gen = torch.Generator(self.device).manual_seed(int(seed)) if seed is not None else None

        on_cuda = self.device == "cuda"
        if on_cuda:
            torch.cuda.reset_peak_memory_stats()
            torch.cuda.synchronize()
        t0 = time.time()
        painted = self.pipe(
            prompt=prompt,
            image=image.resize((w, h), Image.LANCZOS),
            mask_image=mask.resize((w, h), Image.NEAREST),
            width=w,
            height=h,
            num_inference_steps=steps,
            guidance_scale=guidance,
            max_sequence_length=512,
            generator=gen,
        ).images[0]
        if on_cuda:
            torch.cuda.synchronize()
        seconds = round(time.time() - t0, 2)

        buf = io.BytesIO()
        paste_back(image, painted, mask).save(buf, format="PNG")
        return {
            "png": buf.getvalue(),
            "generate_seconds": seconds,
            "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 1e9, 1) if on_cuda else None,
        }
