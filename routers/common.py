"""Shared helpers/models for the DesignBridge API routers."""
import os
import threading
from pathlib import Path
from typing import Optional, List

from fastapi import HTTPException
from pydantic import BaseModel

from designbridge import get_compiled_graph

# 對外可存取的後端網址；非本機 8000 埠（換埠、部署、手機連區網）時用 API_PUBLIC_URL 覆蓋
API_PUBLIC_URL = os.getenv("API_PUBLIC_URL", "http://localhost:8000").rstrip("/")


def _artifact_url(p) -> Optional[str]:
    """artifacts/ 底下的相對路徑 → 可供前端存取的絕對 URL；其他路徑回 None。"""
    if not p:
        return None
    normalized = str(p).replace("\\", "/")
    return f"{API_PUBLIC_URL}/{normalized}" if normalized.startswith("artifacts/") else None


ARTIFACTS_DIR = (Path(__file__).parent.parent / "artifacts").resolve()


def _is_artifact_file(p) -> bool:
    """p 解析後是否為 artifacts/ 底下的既有檔案（擋掉 ../ 與任意本機絕對路徑）。"""
    try:
        path = Path(p).resolve()
    except (OSError, ValueError):
        return False
    return path.is_relative_to(ARTIFACTS_DIR) and path.is_file()


def _require_artifact_file(p, status: int = 400) -> None:
    if not _is_artifact_file(p):
        raise HTTPException(status_code=status, detail=f"找不到圖片：{p}")



def _layout_render_config() -> dict:
    """Furniture heights/colors + camera params for the frontend's Three.js layout
    preview — same numbers scene_graph_to_depth.py already uses to rasterize the
    ControlNet depth map, so the 3D preview and the actual generation stay in sync."""
    from designbridge.core.config import Config
    from designbridge.layout.layout_agent import FURNITURE_COLORS
    from designbridge.layout.scene_graph_to_depth import FURNITURE_HEIGHTS

    return {
        "furniture_heights": FURNITURE_HEIGHTS,
        "furniture_colors": {
            ftype: "#%02x%02x%02x" % rgb for ftype, rgb in FURNITURE_COLORS.items()
        },
        "camera": {
            "hfov_deg": Config.LAYOUT_PROJECTION_HFOV,
            "pitch_deg": Config.LAYOUT_PROJECTION_PITCH,
            "eye_height": 1.40,
            "setback": Config.LAYOUT_PROJECTION_SETBACK,
        },
    }


class DesignRequest(BaseModel):
    text_prompt: str = ""
    style_profile_id: Optional[str] = None
    initial_image_path: Optional[str] = None
    style_reference_image_path: Optional[str] = None
    no_style_reference: bool = False
    refine_mode: bool = False  # 細部微調模式：強制 routing 到 design_adjuster
    output_aspect: str = "auto"  # 輸出長寬比：auto | 1:1 | 4:3 | 3:4 | 16:9 | 9:16
    mask_image_path: Optional[str] = None  # 手繪遮罩路徑（refine 模式選填）
    fengshui_rules: List[str] = []
    style_method: str = "ai_analysis"
    floor_plan_path: Optional[str] = None   # 由 Step 1 產生的 2D 平面圖路徑
    scene_graph: Optional[dict] = None     # 由 Step 1 產生的完整 scene_graph（含家具座標）
    # /api/plan-layout 回傳的結果，原樣回傳給 /api/generate 就能跳過重跑 RA/vision/layout_agent，
    # 直接進 renderer——使用者在前端確認過 3D 佈局預覽後才會帶著這個欄位呼叫
    plan: Optional[dict] = None
    # 以下四個欄位只給獨立的除錯測試介面（debug-console/）用，測試不同 ControlNet
    # 模型/強度/LoRA 組合；正式產品前端不會帶這些欄位，None 時完全走 Config 預設值。
    controlnet_model_override: Optional[str] = None
    controlnet_scale_override: Optional[float] = None
    controlnet_steps_override: Optional[int] = None
    controlnet_guidance_override: Optional[float] = None
    controlnet_control_end_override: Optional[float] = None   # 0~1，depth/edge control 在去噪過程中生效到百分之幾就放開
    lora_overrides: Optional[List[dict]] = None   # [{"path": str, "scale": float}]
    disable_edge_control: Optional[bool] = None   # 停用 edge(canny) ControlNet，只留 depth，方便排查 artifact 來源
    disable_lora: Optional[bool] = None   # 停用風格 LoRA，只留 ControlNet，方便排查 artifact 來源
    # image-to-image 換風格測試（見 render_backends._render_flux_img2img_fal）：
    # 帶了 base image 就整個跳過 depth ControlNet，改用這張圖當起始圖低強度重繪。
    img2img_base_image_override: Optional[str] = None   # 本機路徑或 URL，通常是上一輪 generated_image_path
    img2img_strength_override: Optional[float] = None   # 0~1，越低越貼近原圖（預設 0.5）



def _build_user_input(request: DesignRequest) -> dict:
    """Assemble the `user_input` LangGraph state dict from a request — shared by
    /api/generate and /api/plan-layout so the two stay in sync."""
    user_input = {
        "text_prompt": request.text_prompt,
        "output_aspect": request.output_aspect,
    }
    if request.style_profile_id and request.style_profile_id != "auto":
        user_input["style_profile_id"] = request.style_profile_id
    if request.initial_image_path:
        user_input["initial_image"] = request.initial_image_path
    if request.style_reference_image_path:
        user_input["style_reference_image"] = request.style_reference_image_path
    if request.no_style_reference:
        user_input["no_style_reference"] = True
    if request.refine_mode:
        user_input["refine_mode"] = True
    if request.mask_image_path:
        user_input["mask_image"] = request.mask_image_path
    if request.fengshui_rules:
        user_input["fengshui_rules"] = request.fengshui_rules
    if request.style_method:
        user_input["style_method"] = request.style_method
    render_overrides = {
        k: v for k, v in {
            "controlnet_model": request.controlnet_model_override,
            "controlnet_scale": request.controlnet_scale_override,
            "controlnet_steps": request.controlnet_steps_override,
            "controlnet_guidance": request.controlnet_guidance_override,
            "controlnet_control_end": request.controlnet_control_end_override,
            "loras": request.lora_overrides,
            "disable_edge_control": request.disable_edge_control,
            "disable_lora": request.disable_lora,
            "img2img_base_image": request.img2img_base_image_override,
            "img2img_strength": request.img2img_strength_override,
        }.items() if v is not None
    }
    if render_overrides:
        user_input["render_overrides"] = render_overrides
    return user_input


# 2. 延遲編譯 Graph（避免 uvicorn 啟動前長時間阻塞，導致前端連不上）
_compiled_graph = None


_graph_lock = threading.Lock()


def _get_graph():
    global _compiled_graph
    with _graph_lock:  # endpoints now run in the threadpool; avoid double compile
        if _compiled_graph is None:
            _compiled_graph = get_compiled_graph()
    return _compiled_graph
