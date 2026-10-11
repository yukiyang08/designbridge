"""首頁示範補圖：同一風格的多張不同房間範例卡圖，以及「現代簡約」的設計圖版本（原圖套用該風格）。
牌卡：FAL flux/dev 文字生圖（不使用第三方圖片）；設計圖：平台的照片流程（FAL + ControlNet）。會呼叫 fal（有費用）。
用法：PYTHONUTF8=1 python scripts/gen_home_cards2.py
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
# (檔名, 風格, 房間與角度)：同一風格換不同房間，才不會一排卡片看起來是同一張
CARDS = [
    ("american-2", "american", "a cozy family living room with a kids play corner"),
    ("american-3", "american", "a warm living room with a large fabric sofa and framed photos"),
    ("country-2", "country", "a sunny dining room with a wooden table and linen curtains"),
    ("modern-2", "modern", "a compact studio apartment living area with a daybed"),
    ("modern-3", "modern", "a small living room with a light wood TV console"),
    ("modern-4", "modern", "an open kitchen and living room in a small apartment"),
    ("modern-5", "modern", "a narrow living room with a built-in bench and shelves"),
    ("modern-6", "modern", "a bright small apartment living room with a sofa bed"),
    ("industrial-2", "industrial", "a cafe-like dining corner with a long wooden counter"),
    ("industrial-3", "industrial", "a loft living room with exposed ducts and leather sofa"),
    ("industrial-4", "industrial", "an open kitchen with concrete counters and metal stools"),
    ("luxury-2", "luxury", "a hotel-like living room with soft lighting and a velvet sofa"),
    ("luxury-3", "luxury", "a calm lounge with marble coffee table and warm indirect light"),
]
PHOTO = ROOT / "frontend/src/assets/rooms/living_room.jpg"


def gen_card(item):
    import fal_client
    name, style, shot = item
    os.environ["FAL_KEY"] = Config.FAL_KEY
    prompt = (f"Photorealistic interior design photo of {shot} in a Taiwanese apartment, "
              f"{_STYLE_LOOK[style]}. Natural light, professional architectural photography, no people.")
    r = fal_client.subscribe("fal-ai/flux/dev", arguments={
        "prompt": prompt, "image_size": "square_hd", "num_inference_steps": 28, "guidance_scale": 3.5,
        "num_images": 1, "seed": 11, "enable_safety_checker": True})
    img = Image.open(io.BytesIO(requests.get(r["images"][0]["url"], timeout=60).content)).convert("RGB")
    img.thumbnail((640, 640))
    img.save(OUT / f"card-{name}.jpg", quality=84, optimize=True)
    print(f"  → card-{name}.jpg", flush=True)


def gen_demo_modern():
    import routers.generate as G
    from routers.common import DesignRequest
    G._save_history = lambda *a, **k: None
    base = G.generate_design(DesignRequest(text_prompt="明亮的客廳", style_profile_id="modern", seed=42, output_aspect="16:9",
                                           initial_image_path=str(PHOTO)))
    plan = {k: v for k, v in base.items() if k != "style_params"}
    r = G.generate_design(DesignRequest(text_prompt="", style_profile_id="modern", output_aspect="16:9", plan=plan,
                                        seed=43))   # 與原圖不同的 seed，才會真的重畫成「現代簡約」版本
    im = Image.open(r["generated_image_path"]).convert("RGB")
    im.thumbnail((1024, 1024))
    im.save(OUT / "demo-modern.jpg", quality=84, optimize=True)
    print("  → demo-modern.jpg", flush=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(gen_card, CARDS))
    print("cards DONE", flush=True)
    gen_demo_modern()
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
