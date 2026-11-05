"""對照組 v2：把使用者原文（含家具位置）完整翻成英文，直接丟 FLUX.1-dev 文字生圖。

會呼叫 fal（有費用）：2 場景 × 2 seed = 4 次生成。
用法：PYTHONUTF8=1 python docs/experiments/depth_vs_text/run_baseline_full.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

IMG = Path(__file__).resolve().parent / "images"
PROMPTS = {
    "living": (
        "A modern living room, about 5 m wide and 4 m deep. The sofa is against the left wall, facing the right wall. "
        "The TV cabinet is against the right wall, directly opposite the sofa. A coffee table sits in the center between "
        "the sofa and the TV cabinet. A side table is on the right side of the sofa, and a potted plant is next to the TV "
        "cabinet. The window is on the far wall; the area in front of the window and the central walkway are kept clear. "
        "Photorealistic interior rendering."),
    "bedroom": (
        "A Nordic-style bedroom, about 3.5 m wide and 4 m deep. The headboard of the double bed is against the left wall, "
        "with a nightstand on each side of the bed. The wardrobe is against the right wall. A desk and chair are placed "
        "next to the window. The window is on the far wall, and the walkway at the foot of the bed is kept clear. "
        "Photorealistic interior rendering."),
}


def main():
    from designbridge.core.config import Config
    from designbridge.render.render_backends import _fal_flux_general

    os.environ.setdefault("FAL_KEY", Config.FAL_KEY or "")
    for name, prompt in PROMPTS.items():
        for seed in (100, 101):
            print(f"@@ {name}_s{seed} baseline_full")
            img = _fal_flux_general("fal-ai/flux-general", {
                "prompt": prompt,
                "num_inference_steps": Config.FAL_CONTROLNET_STEPS,
                "guidance_scale": Config.FAL_CONTROLNET_GUIDANCE,
                "image_size": "landscape_16_9",
                "seed": seed,
            })
            (IMG / f"{name}_s{seed}_baseline_full.png").write_bytes(img)
    print("@@ DONE")


if __name__ == "__main__":
    main()
