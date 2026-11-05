"""有系統（佈局→投影深度→ControlNet+LoRA）vs 純文字生圖（同模型 FLUX.1-dev、同 seed、同英文描述）。

會呼叫 fal（有費用）：每個場景 × 每個 seed 各 2 次生成。
用法：PYTHONUTF8=1 python docs/experiments/depth_vs_text/run_ab.py
"""
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

OUT = Path(__file__).resolve().parent
IMG = OUT / "images"
IMG.mkdir(parents=True, exist_ok=True)

SCENES = {
    "living": dict(style="modern", room_type="living_room", prompt=(
        "客廳，約 5 公尺寬、4 公尺深。沙發靠左側牆面，面向右牆；電視櫃靠右側牆，位在沙發正對面；"
        "茶几放在沙發與電視櫃之間的中央；沙發右側放一張邊几，電視櫃旁邊放一盆盆栽。"
        "窗戶在正對面的牆上，保持窗前和中央走道淨空。")),
    "bedroom": dict(style="nordic", room_type="bedroom", prompt=(
        "臥室，約 3.5 公尺寬、4 公尺深。雙人床床頭靠左側牆，床的兩側各放一個床頭櫃；"
        "衣櫃靠右側牆；書桌和椅子放在窗戶旁邊；窗戶在正對面的牆上，保持床尾走道淨空。")),
}
SEEDS = [100, 101]


def main():
    import routers.generate as G
    from routers.common import DesignRequest
    from routers.floorplan import FloorPlanRenderRequest, render_floor_plan
    from designbridge.core.config import Config
    from designbridge.core.warmup import run_startup_warmup
    from designbridge.render.render_backends import _fal_flux_general
    import fal_client  # noqa: F401  確認套件存在

    os.environ.setdefault("FAL_KEY", Config.FAL_KEY or "")
    G._save_history = lambda *a, **k: None   # 不寫進任何人的歷史紀錄
    run_startup_warmup()

    results = []
    raw = OUT / "results.json"
    for name, sc in SCENES.items():
        for seed in SEEDS:
            tag = f"{name}_s{seed}"
            print(f"\n@@ {tag} system")
            resp = G.generate_design(
                DesignRequest(text_prompt=sc["prompt"], style_profile_id=sc["style"], seed=seed, output_aspect="16:9"),
                user_id="ab-depth-vs-text",
            )
            rec = dict(scene=name, seed=seed, user_prompt=sc["prompt"], style=sc["style"])
            shutil.copy(resp["generated_image_path"], IMG / f"{tag}_system.png")
            gp = (resp.get("render_result") or {}).get("generation_params") or {}
            rec["system_backend"] = gp.get("backend")
            rec["system_params"] = {k: v for k, v in gp.items() if isinstance(v, (str, int, float, bool))}
            sg = resp.get("scene_graph") or {}
            if sg.get("projected_depth_path") and Path(sg["projected_depth_path"]).is_file():
                shutil.copy(sg["projected_depth_path"], IMG / f"{tag}_depth.png")
            placements = sg.get("furniture_placements") or []
            rec["placements"] = placements
            space = (resp.get("structured_requirement") or {}).get("space_info") or {}
            if placements:
                fp = render_floor_plan(FloorPlanRenderRequest(
                    furniture_placements=placements,
                    room_w=float(space.get("width") or space.get("room_w") or 5.0),
                    room_d=float(space.get("depth") or space.get("room_d") or 4.0),
                    room_type=sc["room_type"],
                ))
                fp_path = fp.get("floor_plan_path") or fp.get("path")
                if fp_path and Path(fp_path).is_file():
                    shutil.copy(fp_path, IMG / f"{tag}_floorplan.png")

            # 對照組：同一段英文描述，直接丟 FLUX.1-dev 文字生圖，不經佈局、深度、LoRA
            desc = ((resp.get("structured_requirement") or {}).get("design_description") or "").strip()
            rec["baseline_prompt"] = desc
            print(f"\n@@ {tag} baseline")
            img = _fal_flux_general("fal-ai/flux-general", {
                "prompt": desc,
                # 與系統 ControlNet 路徑相同的步數與 guidance（renderer.py 的 _cn_steps／_cn_guidance 預設）
                "num_inference_steps": Config.FAL_CONTROLNET_STEPS,
                "guidance_scale": Config.FAL_CONTROLNET_GUIDANCE,
                "image_size": "landscape_16_9",
                "seed": seed,
            })
            (IMG / f"{tag}_baseline.png").write_bytes(img)
            results.append(rec)
            raw.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print("@@ DONE")


if __name__ == "__main__":
    main()
