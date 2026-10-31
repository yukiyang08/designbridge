"""FLUX.1-dev + 深度/邊緣 ControlNet + 風格 LoRA 推論。不含平台專屬程式，Modal / RunPod 共用。

參數對應 designbridge/render/render_backends.py 的 _render_flux_controlnet_depth_fal（fal-ai/flux-general）。
"""

from __future__ import annotations

import io
import time

BASE_MODEL = "black-forest-labs/FLUX.1-dev"
DEPTH_CONTROLNET = "Shakker-Labs/FLUX.1-dev-ControlNet-Depth"
EDGE_CONTROLNET = "InstantX/FLUX.1-dev-Controlnet-Canny"
UNION_CONTROLNET = "Shakker-Labs/FLUX.1-dev-ControlNet-Union-Pro"
UNION_MODE = {"canny": 0, "depth": 2}  # Union-Pro 模型卡的 control_mode 編號
LORA_REPO = "MovingForward/designbridge-flux-lora"
LORA_STYLES = ("modern", "country", "classic", "nordic", "industrial", "japanese", "american", "luxury")


def lora_weight_name(style_id: str) -> str:
    return f"flux1dev/designbridge_v5_flux1dev_{style_id}.safetensors"


def versions() -> dict:
    import diffusers
    import torch
    import transformers

    # torch.__version__ 是 torch 自訂的 str 子類別，本機沒裝 torch 會解不開，一律轉成純 str
    return {
        "torch": str(torch.__version__),
        "cuda": str(torch.version.cuda),
        "diffusers": str(diffusers.__version__),
        "transformers": str(transformers.__version__),
        "gpu": str(torch.cuda.get_device_name(0)) if torch.cuda.is_available() else None,
    }


class FluxRenderer:
    def __init__(self, device: str = "cuda", mode: str = "two") -> None:
        """mode：two = 兩個獨立 ControlNet（深度 + canny）；union = 單一 Union-Pro（canny + depth）。"""
        import torch
        from diffusers import FluxControlNetModel, FluxControlNetPipeline

        self.device = device  # "cpu" 只給上 GPU 前的流程檢查用
        self.mode = mode
        t0 = time.time()
        dtype = torch.bfloat16
        if mode == "union":
            nets = [FluxControlNetModel.from_pretrained(UNION_CONTROLNET, torch_dtype=dtype)]
        else:
            nets = [
                FluxControlNetModel.from_pretrained(DEPTH_CONTROLNET, torch_dtype=dtype),
                FluxControlNetModel.from_pretrained(EDGE_CONTROLNET, torch_dtype=dtype),
            ]
        self.pipe = FluxControlNetPipeline.from_pretrained(
            BASE_MODEL, controlnet=nets, torch_dtype=dtype
        ).to(device)
        self._loras: set[str] = set()
        self._preload_loras()
        self.load_seconds = round(time.time() - t0, 1)

    def _preload_loras(self) -> None:
        """啟動時先載入全部風格 LoRA，第一次用某個風格就不會多等 1～3 秒；載完先關閉，用到時才啟用。"""
        for s in LORA_STYLES:
            try:
                self.pipe.load_lora_weights(LORA_REPO, weight_name=lora_weight_name(s), adapter_name=s)
                self._loras.add(s)
            except Exception as e:  # 單一風格載入失敗不影響其他
                print(f"LoRA 預載略過 {s}: {e}")
        if self._loras:
            self.pipe.disable_lora()

    def _use_lora(self, style: str | None, scale: float) -> None:
        if not style:
            if self._loras:
                self.pipe.disable_lora()
            return
        if style not in self._loras:
            self.pipe.load_lora_weights(LORA_REPO, weight_name=lora_weight_name(style), adapter_name=style)
            self._loras.add(style)
        self.pipe.enable_lora()
        self.pipe.set_adapters([style], adapter_weights=[scale])

    def generate(
        self,
        prompt: str,
        depth_png: bytes,
        edge_png: bytes | None,
        *,
        width: int,
        height: int,
        steps: int = 20,
        guidance: float = 3.5,
        depth_scale: float = 0.3,
        edge_scale: float = 0.3,
        depth_end: float = 0.7,
        edge_end: float = 0.7,
        seed: int | None = None,
        lora_style: str | None = None,
        lora_scale: float = 1.0,
    ) -> dict:
        import torch
        from PIL import Image

        size = (width, height)
        depth = Image.open(io.BytesIO(depth_png)).convert("RGB").resize(size)
        # 沒有邊緣圖時用全黑圖加強度 0，管線仍維持兩個 ControlNet
        edge = Image.open(io.BytesIO(edge_png)).convert("RGB").resize(size) if edge_png else Image.new("RGB", size)
        if not edge_png:
            edge_scale = 0.0

        self._use_lora(lora_style, lora_scale)
        gen = torch.Generator(self.device).manual_seed(int(seed)) if seed is not None else None

        on_cuda = self.device == "cuda"
        if on_cuda:
            torch.cuda.reset_peak_memory_stats()
            torch.cuda.synchronize()
        t0 = time.time()
        if self.mode == "union":
            # 同一個模型、每張控制圖用 control_mode 指定種類；順序同 fal 端：先邊緣、後深度，沒邊緣圖就只有深度
            parts = [(edge, edge_scale, edge_end, UNION_MODE["canny"])] if edge_png else []
            parts.append((depth, depth_scale, depth_end, UNION_MODE["depth"]))
            imgs, scales, ends, modes = (list(x) for x in zip(*parts))
            ctrl = dict(
                control_image=imgs, control_mode=modes, controlnet_conditioning_scale=scales,
                control_guidance_start=[0.0] * len(imgs), control_guidance_end=ends,
            )
        else:
            ctrl = dict(
                control_image=[depth, edge], controlnet_conditioning_scale=[depth_scale, edge_scale],
                control_guidance_start=[0.0, 0.0], control_guidance_end=[depth_end, edge_end],
            )
        image = self.pipe(
            prompt=prompt,
            **ctrl,
            num_inference_steps=steps,
            guidance_scale=guidance,
            width=width,
            height=height,
            generator=gen,
        ).images[0]
        if on_cuda:
            torch.cuda.synchronize()
        seconds = round(time.time() - t0, 2)

        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return {
            "png": buf.getvalue(),
            "generate_seconds": seconds,
            "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 1e9, 1) if on_cuda else None,
        }
