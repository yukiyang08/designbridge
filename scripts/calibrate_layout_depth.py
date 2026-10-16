#!/usr/bin/env python3
"""
calibrate_layout_depth.py
-------------------------
端到端校準工具：把一份 scene-graph 佈局投影成透視深度圖，掃描相機參數
（setback / eye-height），可選擇實際呼叫 FLUX Kontext 算圖，最後輸出
「深度圖 vs 算圖」並排比較montage，方便你肉眼挑出視角最對的相機設定。

用法：
  # 只看深度圖框景（不算圖、不花錢）：掃 setback × eye-height
  python -m scripts.calibrate_layout_depth placements.json \
      --setback 1.0,1.5,2.0 --eye-height 1.3,1.6,1.9

  # 連同實際 FLUX 算圖一起比較（需 HF_TOKEN 或 FAL_KEY）
  python -m scripts.calibrate_layout_depth placements.json --render \
      --prompt "modern cozy living room, warm light" --setback 1.2,1.8 --eye-height 1.35,1.85

  # 每組 setback/eye-height 當候選 0，看候選角度評分實際選中哪個站位
  python -m scripts.calibrate_layout_depth placements.json --auto

  # 不給 JSON 時用內建範例佈局
  python -m scripts.calibrate_layout_depth --render

placements.json 接受三種格式：list / {furniture_placements:[...]} / {scene_graph:{...}}
可在物件層級附帶 "space_info": {"estimated_size": {"width":..,"depth":..,"height":..}}
"""

from __future__ import annotations

import argparse
import sys
from itertools import product
from pathlib import Path

import numpy as np

# 允許從專案根目錄直接 `python -m scripts.calibrate_layout_depth`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from designbridge.layout.scene_graph_to_depth import (  # noqa: E402
    _load_placements,
    project_scene_graph_to_depth,
)


_SAMPLE_PLACEMENTS = [
    {"id": "sofa_1", "type": "sofa", "x": 0.10, "y": 0.58, "w": 0.30, "h": 0.13},
    {"id": "coffee_table_1", "type": "coffee_table", "x": 0.20, "y": 0.46, "w": 0.15, "h": 0.10},
    {"id": "tv_unit_1", "type": "tv_unit", "x": 0.34, "y": 0.08, "w": 0.22, "h": 0.07},
    {"id": "armchair_1", "type": "armchair", "x": 0.55, "y": 0.50, "w": 0.11, "h": 0.11},
    {"id": "wardrobe_1", "type": "wardrobe", "x": 0.78, "y": 0.08, "w": 0.18, "h": 0.08},
    {"id": "plant_1", "type": "plant", "x": 0.70, "y": 0.66, "w": 0.06, "h": 0.06},
]
_SAMPLE_SPACE = {"estimated_size": {"width": 5.0, "depth": 4.0, "height": 2.8}}


def _floats(s: str) -> list[float]:
    return [float(x) for x in s.split(",") if x.strip() != ""]


def _render_depth(prompt: str, depth_path: str, out_path: Path, depth_scale: float) -> str | None:
    """用既有後端以深度圖為條件算圖。優先 fal.ai，退而求其次 HF Kontext。回傳成圖路徑或 None。"""
    from designbridge.core.config import Config
    from designbridge.render.render_backends import _render_flux_kontext_fal, _render_hf_kontext

    if Config.FAL_KEY:
        if _render_flux_kontext_fal(prompt, depth_path, out_path, depth_conditioning_scale=depth_scale):
            return str(out_path)
    if Config.HF_TOKEN:
        if _render_hf_kontext(prompt, depth_path, out_path, depth_conditioning_scale=depth_scale):
            return str(out_path)
    print("⚠️  無可用算圖後端（需 FAL_KEY 或 HF_TOKEN），僅輸出深度圖")
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Layout 投影深度圖相機校準工具")
    parser.add_argument("placements", nargs="?", default=None,
                        help="佈局 JSON（省略則用內建範例）")
    parser.add_argument("--prompt", default="modern cozy living room, warm natural light, photorealistic")
    parser.add_argument("--setback", default="1.2,1.8", help="相機後退距離清單（公尺），逗號分隔")
    parser.add_argument("--eye-height", default="1.35,1.85", help="相機眼高清單（公尺），逗號分隔")
    parser.add_argument(
        "--auto", action="store_true",
        help="改成每組 setback/eye-height 當候選 0，實際跑候選角度評分選最佳站位（而非手動固定）",
    )
    parser.add_argument("--render", action="store_true", help="實際呼叫 FLUX 算圖（會用 API 額度）")
    parser.add_argument("--depth-scale", type=float, default=0.85, help="depth_conditioning_scale")
    parser.add_argument("--size", type=int, default=768, help="輸出方形邊長")
    parser.add_argument("--out", default="artifacts/calibration", help="輸出資料夾")
    args = parser.parse_args()

    if args.placements:
        placements, space_info = _load_placements(Path(args.placements))
        if not space_info:
            space_info = _SAMPLE_SPACE
    else:
        placements, space_info = _SAMPLE_PLACEMENTS, _SAMPLE_SPACE
        print("ℹ️  未提供佈局 JSON，使用內建範例 living room 佈局")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    setbacks, eye_heights = _floats(args.setback), _floats(args.eye_height)
    combos = list(product(setbacks, eye_heights))
    print(f"🔧 掃描 {len(combos)} 組相機設定，家具 {len(placements)} 件"
          + ("（候選角度評分開啟）" if args.auto else "（手動固定站位）"))

    cells: list[dict] = []
    for setback, eye_height in combos:
        tag = f"s{setback:g}_e{eye_height:g}"
        depth_out = out_dir / f"depth_{tag}.png"
        res = project_scene_graph_to_depth(
            placements, space_info, depth_out,
            image_size=(args.size, args.size),
            camera_overrides={"setback": setback, "eye_height": eye_height},
            auto_select_camera=args.auto,
        )
        label = f"setback={setback:g}  eye_h={eye_height:g}"
        if args.auto:
            chosen = res["meta"]["camera"]
            label += f"\n-> s={chosen['setback']:.2f} e={chosen['eye_height']:.2f} ({res['meta']['camera_score']:.2f})"
        render_path = None
        if args.render:
            render_out = out_dir / f"render_{tag}.png"
            print(f"🎨 算圖中：{tag}")
            render_path = _render_depth(args.prompt, str(depth_out), render_out, args.depth_scale)
        cells.append({
            "label": label,
            "depth": str(depth_out),
            "render": render_path,
        })

    _build_montage(cells, out_dir / "calibration_montage.png", rendered=args.render)


def _build_montage(cells: list[dict], out_path: Path, rendered: bool) -> None:
    """純 PIL 拼接比較圖（不依賴 matplotlib）。每欄一組相機設定，上=深度、下=算圖。"""
    from PIL import Image, ImageDraw

    THUMB, LABEL_H, PAD = 320, 22, 6
    rows = 2 if rendered else 1
    n = len(cells)
    cell_w = THUMB + 2 * PAD
    cell_h = LABEL_H + THUMB + PAD + (THUMB + PAD if rendered else 0)
    montage = Image.new("RGB", (cell_w * n, cell_h), (30, 30, 30))
    draw = ImageDraw.Draw(montage)

    def _thumb(path: str | None, mode: str) -> Image.Image:
        if path and Path(path).exists():
            return Image.open(path).convert(mode).resize((THUMB, THUMB))
        ph = Image.new(mode, (THUMB, THUMB), 0 if mode == "L" else (60, 60, 60))
        ImageDraw.Draw(ph).text((THUMB // 2 - 30, THUMB // 2), "no render", fill=200)
        return ph.convert("RGB")

    for col, cell in enumerate(cells):
        x0 = col * cell_w + PAD
        draw.text((x0, 4), cell["label"], fill=(235, 235, 235))
        montage.paste(_thumb(cell["depth"], "L").convert("RGB"), (x0, LABEL_H))
        if rendered:
            montage.paste(_thumb(cell["render"], "RGB"), (x0, LABEL_H + THUMB + PAD))

    montage.save(str(out_path))
    print(f"\n✅ 比較montage：{out_path}")
    print("   逐欄比對『深度圖視角』與『FLUX 成圖視角』是否一致，挑出最對的一組，")
    print("   再用 DESIGNBRIDGE_LAYOUT_CAM_SETBACK / _EYE_H 設成該值（base/候選 0）。")
    print("   加 --auto 可以看同一組 base 參數被候選角度評分之後實際選中的站位。")


if __name__ == "__main__":
    main()
