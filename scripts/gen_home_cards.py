"""首頁風格牌卡的範例圖：8 種風格各用 FAL 生成一張室內照（不連風格資料庫、不使用第三方圖片）。
輸出 frontend/src/assets/home/card-<style>.jpg。會呼叫 fal（有費用）：8 次 flux/dev。
用法：PYTHONUTF8=1 python scripts/gen_home_cards.py
"""
import io
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import requests
from PIL import Image

from designbridge.core.config import Config
from designbridge.render.render_prompt import _STYLE_LOOK

OUT = ROOT / "frontend/src/assets/home"
# 現代、鄉村等風格詞取自 render_prompt._STYLE_LOOK；每張換不同房間與角度，和「套用結果圖」不同
SHOTS = {
    "modern": "a bright open-plan living room seen from the dining area",
    "country": "a cozy living room corner with a window seat",
    "classic": "a formal living room with a fireplace, seen from the entrance",
    "nordic": "a small apartment living room with a sofa by the window",
    "industrial": "a loft living room with a tall window wall",
    "japanese": "a low-furniture living room opening to a balcony",
    "american": "a family living room with a large sofa and bookshelves",
    "luxury": "a grand living room with a feature wall",
}


def gen(style):
    import fal_client
    os.environ["FAL_KEY"] = Config.FAL_KEY
    prompt = (f"Photorealistic interior design photo of {SHOTS[style]} in a Taiwanese apartment, "
              f"{_STYLE_LOOK[style]}. Natural light, professional architectural photography, no people.")
    r = fal_client.subscribe("fal-ai/flux/dev", arguments={
        "prompt": prompt, "image_size": "square_hd", "num_inference_steps": 28, "guidance_scale": 3.5,
        "num_images": 1, "seed": 7, "enable_safety_checker": True})
    img = Image.open(io.BytesIO(requests.get(r["images"][0]["url"], timeout=60).content)).convert("RGB")
    img.thumbnail((640, 640))
    img.save(OUT / f"card-{style}.jpg", quality=84, optimize=True)
    print(f"  → card-{style}.jpg {img.size}", flush=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(gen, SHOTS))
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
