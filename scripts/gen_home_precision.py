"""首頁「格局精準」素材：用平台流程生成一張客廳（文字 → 排版 → 投影深度 → ControlNet），
把平面圖家具、投影到畫面的範圍與成品存到 artifacts/home_precision/，供檢查對位是否真的準。會呼叫 fal（有費用）。
用法：PYTHONUTF8=1 python scripts/gen_home_precision.py
"""
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

OUT = ROOT / "artifacts/home_precision"


def main():
    import routers.generate as G
    from routers.common import DesignRequest
    G._save_history = lambda *a, **k: None
    OUT.mkdir(parents=True, exist_ok=True)
    r = G.generate_design(DesignRequest(
        text_prompt="客廳：三人座沙發靠牆、電視櫃在沙發對面、中間放圓形茶几、旁邊一張單人椅和邊桌，現代簡約風格",
        style_profile_id="modern", seed=7, output_aspect="16:9"))
    print("keys:", list(r.keys()), flush=True)
    json.dump({k: v for k, v in r.items() if k != "style_params"}, open(OUT / "result.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, default=str)
    shutil.copy(r["generated_image_path"], OUT / "render.png")
    print("DONE", r["generated_image_path"], flush=True)


if __name__ == "__main__":
    main()
