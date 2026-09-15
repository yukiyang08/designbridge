"""Depth Cloud graph node：把設計圖 + 深度圖反投影成 3D 網格／環景圖。"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from designbridge.core.config import Config
from designbridge.core.state import DesignBridgeState


def depth_cloud_node(state: DesignBridgeState) -> dict[str, Any]:
    """
    Depth → GLB mesh node.
    Back-projects the design image + depth map into a textured GLB mesh.
    Returns {} (no-op) if either asset is missing.
    """
    generated_image = state.get("generated_image")
    vision = state.get("vision_features") or {}
    depth_path = vision.get("depth")

    if not generated_image or not Path(generated_image).is_file():
        print("[depth_cloud] no generated_image, skipping")
        return {}

    task_id = state.get("task_id") or uuid.uuid4().hex[:8]
    out_dir = str(Path(Config.ARTIFACTS_DIR) / "room_mesh" / task_id)

    if not depth_path or not Path(depth_path).is_file():
        # No pre-computed depth (e.g. text-only generation with no initial image).
        # Run depth estimation directly on the generated image.
        print("[depth_cloud] no depth in vision_features, running depth on generated image...")
        try:
            from designbridge.layout.vision import run_depth_estimation
            depth_path, _ = run_depth_estimation(
                generated_image,
                model_name=Config.DEPTH_MODEL,
                out_dir=Path(out_dir),
            )
            print(f"[depth_cloud] depth → {depth_path}")
        except Exception as e:
            print(f"[depth_cloud] depth estimation failed: {e}, skipping")
            return {}

    final_image_path = generated_image
    final_depth_path = depth_path

    if Config.ENABLE_MESH_OUTPAINT:
        from PIL import Image as PILImage
        from designbridge.render.inpaint import (
            build_outpaint_prompt,
            outpaint_for_depth_mesh,
        )
        from designbridge.layout.vision import run_depth_estimation

        design_prompt = (state.get("user_input") or {}).get("text_prompt", "")
        outpaint_prompt = build_outpaint_prompt(design_prompt)

        original_img = PILImage.open(generated_image).convert("RGB")
        outpainted = outpaint_for_depth_mesh(
            original_img,
            border_fraction=Config.MESH_OUTPAINT_BORDER,
            prompt=outpaint_prompt,
            out_dir=Path(out_dir),
        )

        if outpainted is not None:
            outpainted_path = str(Path(out_dir) / "outpainted.png")
            if not Path(outpainted_path).is_file():
                Path(out_dir).mkdir(parents=True, exist_ok=True)
                outpainted.save(outpainted_path)

            print("[depth_cloud] re-running depth on outpainted image...")
            new_depth_path, _ = run_depth_estimation(
                outpainted_path,
                model_name=Config.DEPTH_MODEL,
                out_dir=Path(out_dir),
            )
            final_image_path = outpainted_path
            final_depth_path = new_depth_path
            print(f"[depth_cloud] outpaint depth → {new_depth_path}")
        else:
            print("[depth_cloud] outpainting failed, using original image")

    glb_path = None
    panorama_path = None

    if Config.ENABLE_TEXT2ROOM:
        from designbridge.render.text2room import run_text2room_loop
        azimuths = [float(x) for x in Config.TEXT2ROOM_AZIMUTHS.split(",") if x.strip()]
        design_prompt = (state.get("user_input") or {}).get("text_prompt", "")
        t2r = run_text2room_loop(
            image_path=final_image_path,
            depth_path=final_depth_path,
            out_dir=out_dir,
            prompt=design_prompt,
            azimuths_deg=azimuths,
            steps_per_side=Config.TEXT2ROOM_STEPS_PER_SIDE,
        )
        if t2r:
            glb_path = t2r.get("glb")
            panorama_path = t2r.get("panorama")
    else:
        from designbridge.render.depth_cloud import generate_depth_mesh_glb
        glb_path = generate_depth_mesh_glb(
            image_path=final_image_path,
            depth_path=final_depth_path,
            out_dir=out_dir,
        )

    if not glb_path and not panorama_path:
        print("[depth_cloud] failed, skipping")
        return {}

    out: dict = {}
    if glb_path:
        out["room_glb_path"] = glb_path
    if panorama_path:
        out["room_panorama_path"] = panorama_path
    print(f"[depth_cloud] ✅ glb={glb_path} panorama={panorama_path}")
    return out
