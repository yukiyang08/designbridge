"""首頁示範用：把同一張房間照片，用平台真實的 FAL + ControlNet 流程套用成各風格，存到 frontend/src/assets/home/。

流程與正式的「上傳現況照片 → 一鍵換風格」相同：先對照片生成基準圖（取得照片深度與 plan），
再以同一個 plan、seed 換風格（ControlNet 深度約束 + 該風格 LoRA）。會呼叫 fal（有費用）：1 + 7 次。
用法：PYTHONUTF8=1 python scripts/gen_home_demo.py
"""
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from PIL import Image

PHOTO = ROOT / "frontend/src/assets/rooms/living_room.jpg"
OUT = ROOT / "frontend/src/assets/home"
STYLES = ["industrial", "luxury", "japanese", "country", "nordic", "american", "classic"]
SEED = 42


def save_jpg(src, name):
    im = Image.open(src).convert("RGB")
    im.thumbnail((1024, 1024))
    im.save(OUT / name, quality=84, optimize=True)
    print(f"  → {name} {im.size}", flush=True)


def main():
    import routers.generate as G
    from routers.common import DesignRequest
    G._save_history = lambda *a, **k: None   # 不污染歷史紀錄

    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy(PHOTO, OUT / "demo-original.jpg")

    print("基準圖（照片流程）…", flush=True)
    t0 = time.time()
    base = G.generate_design(DesignRequest(
        text_prompt="明亮的客廳", style_profile_id="modern", seed=SEED, output_aspect="16:9",
        initial_image_path=str(PHOTO)))
    gp = (base.get("render_result") or {}).get("generation_params") or {}
    print(f"  backend={gp.get('backend')} {time.time() - t0:.0f}s", flush=True)
    if gp.get("backend") != "flux_controlnet_depth_fal":
        sys.exit("基準圖沒有走 ControlNet，中止")
    plan = {k: v for k, v in base.items() if k != "style_params"}   # 與前端 swapStyle 一致

    for style in STYLES:
        print(f"{style}…", flush=True)
        t0 = time.time()
        try:
            r = G.generate_design(DesignRequest(
                text_prompt="", style_profile_id=style, output_aspect="16:9", plan=plan))
        except Exception as e:
            print(f"  失敗：{e}", flush=True)
            continue
        g = (r.get("render_result") or {}).get("generation_params") or {}
        print(f"  backend={g.get('backend')} scale={g.get('depth_conditioning_scale')} {time.time() - t0:.0f}s", flush=True)
        save_jpg(r["generated_image_path"], f"demo-{style}.jpg")
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
