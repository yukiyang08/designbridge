"""Shared helpers/models for the DesignBridge API routers."""
import json
import os
import re
import threading
from pathlib import Path
from typing import Optional, List

from fastapi import Header, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from designbridge import get_compiled_graph
from designbridge.style.style_supabase import _get_supabase

# 對外可存取的後端網址；非本機 8000 埠（換埠、部署、手機連區網）時用 API_PUBLIC_URL 覆蓋
API_PUBLIC_URL = os.getenv("API_PUBLIC_URL", "http://localhost:8000").rstrip("/")


def _artifact_url(p) -> Optional[str]:
    """artifacts/ 底下的相對路徑 → 可供前端存取的絕對 URL；其他路徑回 None。"""
    if not p:
        return None
    normalized = str(p).replace("\\", "/")
    return f"{API_PUBLIC_URL}/{normalized}" if normalized.startswith("artifacts/") else None


# 本機開發用：前端還沒設定 Supabase anon key、沒辦法登入時，讓本機請求以「未登入」身分通過。
# 只認本機連線，部署後就算 .env 誤開也不會生效；這種請求不存雲端歷史紀錄
DEV_NO_AUTH = os.getenv("DESIGNBRIDGE_DEV_NO_AUTH", "false").lower() in ("1", "true", "yes")
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
if DEV_NO_AUTH:
    print("⚠️  DESIGNBRIDGE_DEV_NO_AUTH=true：本機請求不需登入，生成結果不會存進雲端歷史")


def get_user_id(request: Request, authorization: Optional[str] = Header(None)) -> str:
    """驗證前端帶來的 Supabase JWT，回傳 user_id；沒登入或 token 無效就 401。

    DEV_NO_AUTH 開啟且請求來自本機、又沒帶 token 時回傳空字串（呼叫端據此跳過雲端存檔）。
    """
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token:
        if DEV_NO_AUTH and request.client and request.client.host in _LOCAL_HOSTS:
            return ""
        raise HTTPException(status_code=401, detail="請先登入")
    try:
        return _get_supabase().auth.get_user(token).user.id
    except Exception:
        raise HTTPException(status_code=401, detail="登入已失效，請重新登入")


ARTIFACTS_DIR = (Path(__file__).parent.parent / "artifacts").resolve()


def _is_artifact_file(p) -> bool:
    """p 解析後是否為 artifacts/ 底下的既有檔案（擋掉 ../ 與任意本機絕對路徑）。"""
    try:
        path = Path(p).resolve()
    except (OSError, ValueError):
        return False
    return path.is_relative_to(ARTIFACTS_DIR) and path.is_file()


_RENDER_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def member_project_ids(sb, user_id: str) -> list:
    """別人邀請我共編的設計 id。"""
    return [m["project_id"] for m in
            sb.table("project_members").select("project_id").eq("user_id", user_id).execute().data]


def _inside_artifacts(p) -> bool:
    """路徑解析後是否落在 artifacts/ 底下（不要求檔案存在）。"""
    try:
        return Path(p).resolve().is_relative_to(ARTIFACTS_DIR)
    except (OSError, ValueError):
        return False


def _walk_paths(obj):
    """巢狀 dict/list 裡所有 *_path 欄位的字串值。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and k.endswith("_path"):
                if v:
                    yield v
            else:
                yield from _walk_paths(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_paths(v)


def check_request_paths(req) -> None:
    """請求帶來的本機路徑一律要在 artifacts/ 底下，否則會被拿來讀伺服器上任意檔案
    （餵給渲染、或上傳到使用者的 Storage）。風格參考圖允許 http(s) 網址，由下載端擋內網。"""
    paths = [req.initial_image_path, req.mask_image_path, req.floor_plan_path,
             *_walk_paths(req.scene_graph), *_walk_paths(req.plan)]
    ref = req.style_reference_image_path
    if ref and not ref.startswith(("http://", "https://")):
        paths.append(ref)
    bad = next((p for p in paths if p and not _inside_artifacts(p)), None)
    if bad:
        raise HTTPException(status_code=400, detail=f"路徑不合法：{bad}")


def ensure_artifact(p, user_id: Optional[str] = None) -> bool:
    """artifacts/ 是快取，Supabase Storage 才是正本：本機缺檔（換機器、清過資料夾）時，
    從 Storage 把這位使用者自己的渲染圖補回「同一個路徑」，呼叫端與前端存的路徑都不用改。
    只補 artifacts/render/ 底下的渲染圖；遮罩、上傳照片這類暫存缺了就是缺了。"""
    if not p:
        return False
    if _is_artifact_file(p):
        return True
    if not user_id:
        return False
    try:
        path = Path(p).resolve()
    except (OSError, ValueError):
        return False
    # 擋 ../、任意絕對路徑，以及 render/ 以外的位置；檔名限制字元，避免被當 LIKE 萬用字元用
    if not (path.is_relative_to(ARTIFACTS_DIR) and path.parent.name == "render"
            and _RENDER_NAME.match(path.name)):
        return False
    try:
        sb = _get_supabase()
        rows = (sb.table("designs").select("image_path").eq("user_id", user_id)
                .like("record->>generated_image_path", f"%{path.name}").limit(1).execute().data)
        if not rows:   # 共編的設計：圖在擁有者名下，只找分享給我的那幾個
            pids = member_project_ids(sb, user_id)
            if pids:
                rows = (sb.table("designs").select("image_path").in_("project_id", pids)
                        .like("record->>generated_image_path", f"%{path.name}").limit(1).execute().data)
        key = rows[0]["image_path"] if rows else None
        if not key:
            return False
        data = sb.storage.from_("designs").download(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return True
    except Exception as e:
        print(f"[artifacts] 從 Storage 補回失敗：{e}")
        return False


def _require_artifact_file(p, status: int = 400, user_id: Optional[str] = None) -> None:
    if not ensure_artifact(p, user_id):
        raise HTTPException(status_code=status, detail=f"找不到圖片：{p}")



def _layout_render_config() -> dict:
    """Furniture heights/colors + camera params for the frontend's Three.js layout
    preview — same base camera params scene_graph_to_depth.py / layout_projection.py
    use (candidate 0), so the 3D preview starts out roughly aligned with the actual
    generation. The real render may pick a different candidate (occlusion-scored —
    see camera_projection.select_best_camera); the preview isn't re-scored per
    layout, it's just a reasonable default orientation the user can freely rotate."""
    from designbridge.core.config import Config
    from designbridge.layout.layout_items import FURNITURE_COLORS
    from designbridge.layout.scene_graph_to_depth import FURNITURE_HEIGHTS

    return {
        "furniture_heights": FURNITURE_HEIGHTS,
        "furniture_colors": {
            ftype: "#%02x%02x%02x" % rgb for ftype, rgb in FURNITURE_COLORS.items()
        },
        "camera": {
            "eye_height": Config.LAYOUT_CAM_EYE_H,
            "setback": Config.LAYOUT_CAM_SETBACK,
            "target_h": Config.LAYOUT_CAM_TARGET_H,
            "target_depth_frac": Config.LAYOUT_CAM_TARGET_DEPTH_FRAC,
            "fov_v_deg": Config.LAYOUT_CAM_FOV,
            "eye_x_frac": Config.LAYOUT_CAM_EYE_X_FRAC,
            "target_x_frac": Config.LAYOUT_CAM_TARGET_X_FRAC,
            "min_view_dist": Config.LAYOUT_CAM_MIN_VIEW_DIST,
            "small_room_eye_h": Config.LAYOUT_CAM_SMALL_ROOM_EYE_H,
        },
    }


_MAX_PAYLOAD_CHARS = 2_000_000   # cad_plan 內含 SVG，正常約數百 KB
_MAX_PLACEMENTS = 300            # 一個房間實際不會超過幾十件


class DesignRequest(BaseModel):
    text_prompt: str = Field(default="", max_length=2000)
    # 「我的設計」分組：同一個設計（一個家）底下可有多個空間；沒帶時各自獨立成一個設計
    project_id: Optional[str] = Field(default=None, pattern=r"^[0-9a-fA-F-]{36}$")
    space_id: Optional[str] = Field(default=None, max_length=64)
    space_name: Optional[str] = Field(default=None, max_length=32)
    space_dims: Optional[dict] = None   # 這個空間的尺寸 {w, d}（公尺）
    cad_plan: Optional[dict] = None     # 整層 CAD 平面圖（/api/generate-room-plan 的回應 + 門窗修改）
    style_profile_id: Optional[str] = None
    initial_image_path: Optional[str] = None
    style_reference_image_path: Optional[str] = None
    no_style_reference: bool = False
    refine_mode: bool = False  # 細部微調模式：強制 routing 到 design_adjuster
    restyle: bool = False      # 只換風格：整張重生但沿用照片裡的家具佈局，不重排
    output_aspect: str = "auto"  # 輸出長寬比：auto | 1:1 | 4:3 | 3:4 | 16:9 | 9:16
    mask_image_path: Optional[str] = None  # 手繪遮罩路徑（refine 模式選填）
    fengshui_rules: List[str] = []
    style_method: str = "ai_analysis"
    seed: Optional[int] = None   # 指定渲染 seed；沒給時換風格會沿用 plan 裡上一輪的 seed
    floor_plan_path: Optional[str] = None   # 由 Step 1 產生的 2D 平面圖路徑
    scene_graph: Optional[dict] = None     # 由 Step 1 產生的完整 scene_graph（含家具座標）
    # /api/plan-layout 回傳的結果，原樣回傳給 /api/generate 就能跳過重跑 RA/vision/layout_agent，
    # 直接進 renderer——使用者在前端確認過 3D 佈局預覽後才會帶著這個欄位呼叫
    plan: Optional[dict] = None
    # 這張圖之前各輪的耗時（微調時由前端帶入；換風格則從 plan.timing_runs 取）
    prior_timing_runs: Optional[List[dict]] = None
    # 以下四個欄位只給獨立的除錯測試介面（debug-console/）用，測試不同 ControlNet
    # 模型/強度/LoRA 組合；正式產品前端不會帶這些欄位，None 時完全走 Config 預設值。
    controlnet_model_override: Optional[str] = None
    controlnet_scale_override: Optional[float] = Field(default=None, ge=0, le=2)
    controlnet_steps_override: Optional[int] = Field(default=None, ge=1, le=60)
    controlnet_guidance_override: Optional[float] = Field(default=None, ge=0, le=20)
    controlnet_control_end_override: Optional[float] = Field(default=None, ge=0, le=1)   # 0~1，depth/edge control 在去噪過程中生效到百分之幾就放開
    lora_overrides: Optional[List[dict]] = Field(default=None, max_length=4)   # [{"path": str, "scale": float}]
    disable_edge_control: Optional[bool] = None   # 停用 edge(canny) ControlNet，只留 depth，方便排查 artifact 來源
    disable_lora: Optional[bool] = None   # 停用風格 LoRA，只留 ControlNet，方便排查 artifact 來源

    @model_validator(mode="after")
    def _limit_payload(self):
        """這些 dict 由前端原樣帶回，沒有上限的話一個請求就能塞爆記憶體或讓排版跑很久。"""
        for name in ("cad_plan", "scene_graph", "plan"):
            v = getattr(self, name)
            if v is not None and len(json.dumps(v, ensure_ascii=False, default=str)) > _MAX_PAYLOAD_CHARS:
                raise ValueError(f"{name} 太大")
        for sg in (self.scene_graph, (self.plan or {}).get("scene_graph")):
            if isinstance(sg, dict) and len(sg.get("furniture_placements") or []) > _MAX_PLACEMENTS:
                raise ValueError("家具數量過多")
        return self



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
    if request.restyle:
        user_input["restyle"] = True
    if request.mask_image_path:
        user_input["mask_image"] = request.mask_image_path
    if request.fengshui_rules:
        user_input["fengshui_rules"] = request.fengshui_rules
    if request.style_method:
        user_input["style_method"] = request.style_method
    if request.seed is not None:
        user_input["seed"] = request.seed
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
