"""Upload, chat, generation, quotation and panorama endpoints."""
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from routers.common import (
    API_PUBLIC_URL, DesignRequest, _artifact_url, _build_user_input, _get_graph,
    _is_artifact_file, _layout_render_config, _require_artifact_file,
)
from designbridge.core.config import Config
from routers.history import _save_history

router = APIRouter()

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


@router.post("/api/upload-image")
def upload_image(file: UploadFile = File(...)):
    """接收前端上傳的圖片，儲存到 artifacts/uploads/ 並回傳本機路徑。"""
    upload_dir = Path("artifacts/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = (Path(file.filename).suffix if file.filename else ".png").lower()
    if suffix not in _IMAGE_SUFFIXES:  # /artifacts 是靜態目錄，不能讓 .html/.svg 之類被當網頁開
        raise HTTPException(status_code=400, detail=f"不支援的圖片格式：{suffix or '(無副檔名)'}")
    dest = upload_dir / f"{uuid.uuid4()}{suffix}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"path": str(dest)}


# ── Chat (Gemini) ────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str          # "user" | "assistant" | "system"
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    stream: bool = False


@router.post("/api/chat")
def chat(request: ChatRequest):
    """通用 LLM chat endpoint，透過 Gemini。

    - stream=false（預設）：回傳 { "content": "..." }
    - stream=true：Server-Sent Events，每個 chunk 為 data: <text>\\n\\n
    """
    from designbridge.render.llm import call_llm, call_llm_stream
    from designbridge.core.config import Config

    history = [{"role": m.role, "content": m.content} for m in request.messages[:-1]]
    last = request.messages[-1]

    kwargs = dict(
        history=history or None,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
    )

    if request.stream:
        def _sse_generator():
            for chunk in call_llm_stream(last.content, **kwargs):
                yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(_sse_generator(), media_type="text/event-stream")

    try:
        content = call_llm(last.content, **kwargs)
        return {"content": content, "model": Config.GEMINI_MODEL}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 3. 建立 POST 路由
@router.post("/api/generate")
def generate_design(request: DesignRequest):
    try:
        # 準備 LangGraph 初始狀態
        user_input = _build_user_input(request)
        initial_state: dict = {"user_input": user_input}
        # 若 Step 1 已產生平面圖，預填入完整 scene_graph（含家具座標）讓 layout agent 跳過重複生成
        if request.scene_graph:
            initial_state["scene_graph"] = request.scene_graph
        elif request.floor_plan_path and Path(request.floor_plan_path).is_file():
            initial_state["scene_graph"] = {"floor_plan_path": request.floor_plan_path}

        # 如果前端帶著 /api/plan-layout 的結果回來（使用者已經確認過 3D 佈局預覽），
        # 把這些欄位預先塞進 state，requirement_analyzer/visual_preprocessing/
        # layout_and_style_agent 三個節點都會偵測到已經有值而跳過重跑。
        if request.plan:
            for key in (
                "task_id", "structured_requirement", "routing_decision",
                "vision_features", "scene_graph", "style_params",
            ):
                if request.plan.get(key) is not None:
                    initial_state[key] = request.plan[key]
            # 一鍵換風格（swapStyle 帶著上一輪完整回應當 plan 回來，見 render.js）：
            # renderer 偵測到這裡已經有上一輪的生成結果，會直接拿它當 img2img 起始圖
            # 低強度重繪，取代整條 depth ControlNet 分支（見 renderer.py 的
            # img2img_base 判斷）。欄位名稱不同（plan 用回應格式的
            # generated_image_path，state 用 graph 內部的 generated_image）要轉換。
            # 沿用上一輪的 seed：條件圖（家具深度/邊緣）由 scene_graph 決定、本來就一樣，
            # seed 也一樣，換風格時房間構圖與家具位置才不會整個重抽。
            prev_seed = ((request.plan.get("render_result") or {}).get("generation_params") or {}).get("seed")
            if prev_seed is not None and request.seed is None:
                user_input["seed"] = int(prev_seed)
            prev_image = request.plan.get("generated_image_path")
            if prev_image and Path(prev_image).is_file():
                initial_state["generated_image"] = prev_image
                # 換風格（有上一張圖）：預設丟掉「上一輪補跑的估計深度」與投影深度，讓 renderer 跟第一次生成
                # 走同一條 layout ControlNet 分支。實測前者在窗戶/遠牆等平坦區域是雜訊，會讓窗戶出現龜裂紋、
                # 家具黏在一起；後者乾淨很多（seed 一樣、構圖仍大致沿用）。真實照片的深度不動。
                # Config.STYLE_SWAP_DEPTH_LOCK=true 可切回舊行為。
                vf = initial_state.get("vision_features") or {}
                if not Config.STYLE_SWAP_DEPTH_LOCK and vf.get("depth_source") == "post_estimate":
                    initial_state["vision_features"] = {
                        k: v for k, v in vf.items() if k not in ("depth", "depth_source", "segmentation")
                    }
                    sg = initial_state.get("scene_graph")
                    if sg:
                        initial_state["scene_graph"] = {
                            k: v for k, v in sg.items() if k not in ("projected_depth_path", "projected_seg_path")
                        }

        # 執行工作流
        t0 = time.perf_counter()
        result = _get_graph().invoke(initial_state)
        elapsed = time.perf_counter() - t0
        generated_image_path = result.get("generated_image")
        generated_image_url = _artifact_url(generated_image_path)

        scene_graph = result.get("scene_graph") or {}
        floor_plan_path = scene_graph.get("floor_plan_path")
        floor_plan_url = _artifact_url(floor_plan_path)

        response = {
            "status": "success",
            "elapsed_time": f"{elapsed:.2f}s",
            "routing_decision": result.get("routing_decision"),
            "generated_image_path": generated_image_path,
            "generated_image_url": generated_image_url,
            "floor_plan_path": floor_plan_path,
            "floor_plan_url": floor_plan_url,
            "structured_requirement": result.get("structured_requirement"),
            "scene_graph": result.get("scene_graph"),
            "layout_render_config": _layout_render_config() if result.get("scene_graph") else None,
            "task_id": result.get("task_id"),
            "iteration": result.get("iteration"),
            "render_result": result.get("render_result"),
            "vision_features": result.get("vision_features"),
            "intermediate_outputs": result.get("intermediate_outputs"),
            "style_params": result.get("style_params"),
            "evaluation_result": result.get("evaluation_result"),
            "quotation_result": result.get("quotation_result"),
        }

        # 儲存生成紀錄
        style_ref_path = request.style_reference_image_path or ""
        style_ref_url = None
        style_ref_source = None
        if style_ref_path:
            if style_ref_path.startswith(("http://", "https://")):
                # Supabase URL passed directly from the KB image picker
                style_ref_url = style_ref_path
                style_ref_source = "supabase"
            else:
                normalized_ref = style_ref_path.replace("\\", "/")
                style_ref_url = f"{API_PUBLIC_URL}/{normalized_ref}"
                style_ref_source = "user"
        elif (result.get("style_params") or {}).get("reference_image_url"):
            style_ref_url = (result.get("style_params") or {}).get("reference_image_url")
            style_ref_source = "supabase"

        render_result = result.get("render_result") or {}
        generation_params = render_result.get("generation_params") or {}

        _save_history({
            "task_id": result.get("task_id"),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "elapsed_seconds": round(elapsed, 2),
            "text_prompt": request.text_prompt,
            "model_type": "flux",
            "style_method": request.style_method,
            "style_profile_id": request.style_profile_id,
            "style_reference_image_path": style_ref_path,
            "style_reference_image_url": style_ref_url,
            "style_reference_source": style_ref_source,
            "routing_decision": result.get("routing_decision"),
            "generated_image_path": generated_image_path,
            "generated_image_url": generated_image_url,
            "style_params": result.get("style_params"),
            "backend": generation_params.get("backend") or generation_params.get("model"),
            "gemini_style_description": generation_params.get("gemini_style_description"),
            "generation_params": generation_params,
            "evaluation_result": result.get("evaluation_result"),
        })

        return response

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ── Quotation ─────────────────────────────────────────────────────────────────

class QuotationRequest(BaseModel):
    image_path: str
    structured_requirement: Optional[dict] = None
    selected_furniture: List[dict] = []


@router.post("/api/quotation")
def get_quotation(req: QuotationRequest):
    """手動觸發估價（使用者點「重新估價」按鈕），可帶入使用者在家具查詢頁手動選擇的家具。"""
    from designbridge.pricing.quotation import build_quotation
    try:
        return build_quotation(
            req.image_path,
            req.structured_requirement or {},
            preselected=req.selected_furniture,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ── 獨立的全景生成端點 ──────────────────────────────────────────────────────────

class PanoramaRequest(BaseModel):
    task_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")  # 會拼進 artifacts/ 路徑，擋 ../
    image_path: str   # 設計渲染圖路徑（artifacts/render/...png）
    prompt: str = ""
    depth_path: Optional[str] = None   # 前端可從 vision_features.depth 帶入


def _resolve_depth_for_panorama(request: PanoramaRequest, out_dir: Path) -> Path:
    """找出可用的深度圖。

    視覺預處理的輸出目錄是「內容定址」的（以照片雜湊命名，見
    designbridge/layout/vision.py），所以不能用 task_id 去猜路徑。優先用前端從
    vision_features.depth 帶回來的實際路徑；沒有的話（例如純文字生成、沒有上傳
    空間照）就直接對設計圖本身跑一次深度估計。
    """
    if request.depth_path:
        if _is_artifact_file(request.depth_path):
            return Path(request.depth_path)

    # 舊版路徑（DESIGNBRIDGE_VISION_CACHE=false 時仍以 task_id 命名）
    legacy = Path("artifacts/vision") / request.task_id / "depth.png"
    if legacy.is_file():
        return legacy

    from designbridge.layout.vision import run_depth_estimation
    from designbridge.core.config import Config
    depth_out, _ = run_depth_estimation(
        request.image_path,
        model_name=Config.DEPTH_MODEL,
        out_dir=out_dir,
    )
    return Path(depth_out)


@router.post("/api/generate-panorama")
def generate_panorama(request: PanoramaRequest):
    """按需生成 Text2Room 全景圖，獨立於主要生成流程。"""
    out_dir = Path("artifacts/room_mesh") / request.task_id
    image_path = Path(request.image_path)

    _require_artifact_file(request.image_path, 404)

    try:
        depth_path = _resolve_depth_for_panorama(request, out_dir)
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"深度圖準備失敗：{e}")

    if not depth_path.is_file():
        raise HTTPException(status_code=404, detail="找不到深度圖，也無法對設計圖產生深度圖")

    try:
        from designbridge.render.text2room import run_text2room_loop
        t2r = run_text2room_loop(
            image_path=str(image_path),
            depth_path=str(depth_path),
            out_dir=str(out_dir),
            prompt=request.prompt,
        )
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"全景生成失敗：{e}")

    if not t2r or not t2r.get("panorama"):
        raise HTTPException(status_code=500, detail="全景圖生成失敗")

    return {"room_panorama_url": _artifact_url(t2r["panorama"])}
