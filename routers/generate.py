"""Upload, chat, generation, quotation and panorama endpoints."""
import io
import json
import time
import uuid
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from routers.common import (
    get_user_id, ensure_artifact, _MAX_PAYLOAD_CHARS,
    API_PUBLIC_URL, DesignRequest, _artifact_url, _build_user_input, _get_graph, _inside_artifacts, _walk_paths, check_request_paths,
    _is_artifact_file, _layout_render_config, _require_artifact_file,
)
from designbridge.core.config import Config
from designbridge.core.timing import collect_stages, log_stage
from routers.history import _save_history, save_panorama, save_quotation

router = APIRouter()

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_MAX_UPLOAD_PIXELS = 60_000_000   # 高壓縮的大圖解碼後會吃很多記憶體，只看檔案大小擋不住


def _normalize_upload(dest: Path) -> None:
    """確認真的是圖片且像素數合理；帶 EXIF 的照片轉正後剝除（旋轉資訊只有瀏覽器會套用，
    後端用 Pillow 讀會是橫躺的；同時去掉 GPS 位置）。不合格就刪檔回 400。"""
    from PIL import Image, ImageOps

    try:
        with Image.open(io.BytesIO(dest.read_bytes())) as im:
            if im.width * im.height > _MAX_UPLOAD_PIXELS:
                raise ValueError("解析度太高")
            if im.format not in ("JPEG", "PNG", "WEBP") or not im.getexif():
                return
            keep = {k: im.info[k] for k in ("icc_profile",) if k in im.info}   # 色彩設定要留，不然顏色會偏
            fixed = ImageOps.exif_transpose(im)
            fmt = im.format
            fixed.load()
        fixed.save(dest, format=fmt, **({"quality": 95} if fmt != "PNG" else {}), **keep)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"無法讀取圖片：{e}")


@router.post("/api/upload-image")
def upload_image(file: UploadFile = File(...), user_id: str = Depends(get_user_id)):
    """接收前端上傳的圖片，儲存到 artifacts/uploads/ 並回傳本機路徑。"""
    upload_dir = Path("artifacts/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = (Path(file.filename).suffix if file.filename else ".png").lower()
    if suffix not in _IMAGE_SUFFIXES:  # /artifacts 是靜態目錄，不能讓 .html/.svg 之類被當網頁開
        raise HTTPException(status_code=400, detail=f"不支援的圖片格式：{suffix or '(無副檔名)'}")
    dest = upload_dir / f"{uuid.uuid4()}{suffix}"
    size, too_big = 0, False
    with open(dest, "wb") as f:
        while chunk := file.file.read(1 << 20):
            size += len(chunk)
            if size > _MAX_UPLOAD_BYTES:
                too_big = True
                break
            f.write(chunk)
    if too_big:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=413, detail="圖片太大（上限 20 MB）")
    _normalize_upload(dest)
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
def chat(request: ChatRequest, user_id: str = Depends(get_user_id)):
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


@router.post("/api/modal-warmup")
def modal_warmup(user_id: str = Depends(get_user_id)):
    """前端進入 /studio 時呼叫：DESIGNBRIDGE_MODAL_MODE=demo 才會先叫起 Modal 容器，其他模式不動作。不等結果。"""
    from designbridge.render.render_backends import warmup_modal_gpu

    return {"warmed": warmup_modal_gpu("studio")}


class PrefetchConditionsRequest(BaseModel):
    furniture_placements: List[dict] = Field(max_length=300)
    room_w: float = Field(gt=0, le=100)
    room_d: float = Field(gt=0, le=100)
    output_aspect: str = "auto"


@router.post("/api/prefetch-layout-conditions")
def prefetch_layout_conditions(request: PrefetchConditionsRequest, user_id: str = Depends(get_user_id)):
    """前端停在風格選擇頁時呼叫：先在背景算好 Union 生圖要用的相機評分與條件圖，按生圖時直接命中。不等結果。"""
    if not (Config.ENABLE_LAYOUT_CONTROLNET and (Config.FAL_KEY or Config.USE_MODAL_GPU)) or not request.furniture_placements:
        return {"started": False}
    from designbridge.layout.condition_prefetch import normalize_placements, prefetch
    from designbridge.render.render_prompt import _resolve_output_size

    width, height = _resolve_output_size(request.output_aspect, None)
    try:
        placements = normalize_placements(request.furniture_placements)
    except (TypeError, ValueError):   # 前端帶來的座標欄位格式不對
        raise HTTPException(status_code=422, detail="furniture_placements 格式不正確")
    return {"started": prefetch(placements, request.room_w, request.room_d, width, height)}


# 3. 建立 POST 路由
@router.post("/api/generate")
def generate_design(request: DesignRequest, user_id: str = Depends(get_user_id)):
    check_request_paths(request)
    try:
        # 微調的底圖、換風格的上一張圖：本機沒有就從 Storage 補回（見 ensure_artifact）
        ensure_artifact(request.initial_image_path, user_id)
        ensure_artifact((request.plan or {}).get("generated_image_path"), user_id)
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
            # renderer/composer 以 state 內已有 generated_image 判斷「這是換風格」。
            # 欄位名稱不同（plan 用回應格式的 generated_image_path，
            # state 用 graph 內部的 generated_image）要轉換。
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
        with collect_stages() as timings:
            result = _get_graph().invoke(initial_state)
        elapsed = time.perf_counter() - t0
        generated_image_path = result.get("generated_image")

        # 每輪一筆，串上這張圖之前的流程，前端與歷史紀錄都能看到完整耗時
        if result.get("routing_decision") == "design_adjuster":
            run_kind = "refine"
        elif initial_state.get("generated_image"):
            run_kind = "style_swap"
        else:
            run_kind = "generate"
        prior_runs = request.prior_timing_runs or (request.plan or {}).get("timing_runs") or []
        timing_runs = [*prior_runs, {
            "kind": run_kind,
            "task_id": result.get("task_id"),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "elapsed_seconds": round(elapsed, 2),
            "timings": timings,
        }]
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
            "timings": timings,
            "timing_runs": timing_runs,
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

        if user_id:   # 本機免登入模式沒有使用者，不存雲端歷史
            _save_history(user_id, {
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
                "timings": timings,
                "timing_runs": timing_runs,
                "structured_requirement": result.get("structured_requirement"),
                "space_dims": request.space_dims,
                # 投影深度/分割圖檔大且重算得出來，不存
                "scene_graph": {k: v for k, v in scene_graph.items()
                                if k not in ("projected_depth_path", "projected_seg_path")} or None,
            }, floor_plan_path=floor_plan_path,
                source_photo=request.initial_image_path, style_ref=request.style_reference_image_path,
                project_id=request.project_id, space_id=request.space_id, space_name=request.space_name,
                cad_plan=request.cad_plan)

        return response

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ── 渲染圖上移家具 ─────────────────────────────────────────────────────────────

class _PlanRequest(BaseModel):
    plan: dict                       # 上一輪 /api/generate 的完整回應

    @model_validator(mode="after")
    def _limit_payload(self):
        if len(json.dumps(self.plan, ensure_ascii=False, default=str)) > _MAX_PAYLOAD_CHARS:
            raise ValueError("plan 太大")
        return self


class InstanceMove(BaseModel):
    index: int = Field(ge=0, le=500)  # /api/move-furniture/instances 回傳的第幾件
    x: float = Field(ge=0, le=1)     # 這件的碰地點拖到畫面上的位置（0–1，左上為原點）
    y: float = Field(ge=0, le=1)


class MoveFurnitureRequest(_PlanRequest):
    moves: Optional[List[InstanceMove]] = Field(default=None, max_length=50)   # 在渲染圖上拖曳，可一次好幾件
    furniture_placements: Optional[List[dict]] = Field(default=None, max_length=300)   # 或直接給改完的家具清單
    strength: Optional[float] = Field(default=None, ge=0.1, le=1.0)


def _checked_plan(request: _PlanRequest, user_id: str) -> dict:
    bad = next((p for p in _walk_paths(request.plan) if not _inside_artifacts(p)), None)
    if bad:
        raise HTTPException(status_code=400, detail=f"路徑不合法：{bad}")
    plan = request.plan
    _require_artifact_file(plan.get("generated_image_path") or (plan.get("render_result") or {}).get("generated_image_path"), 404, user_id)
    return plan


@router.post("/api/move-furniture/instances")
def furniture_instances_endpoint(request: _PlanRequest, user_id: str = Depends(get_user_id)):
    """渲染圖上自動切出的每件可移動家具（圖層、碰地點、碰撞範圍）。每張圖第一次要切約 40 秒，之後讀快取。"""
    from designbridge.render.move_furniture import MoveFurnitureError, list_instances

    plan = _checked_plan(request, user_id)
    try:
        data = list_instances(plan)
    except MoveFurnitureError as e:
        raise HTTPException(status_code=400, detail=str(e))
    for inst in data["instances"]:
        inst["layer_url"] = _artifact_url(inst.pop("layer_path"))
        inst["patch_url"] = _artifact_url(inst.pop("patch_path"))
    return data


@router.post("/api/move-furniture")
def move_furniture_endpoint(request: MoveFurnitureRequest, user_id: str = Depends(get_user_id)):
    """移動家具後，用舊圖剪貼出的合成圖當起點，只重修舊位置與家具邊緣，不從零重生。"""
    from designbridge.render.move_furniture import MoveFurnitureError, move_furniture, move_instances

    plan = _checked_plan(request, user_id)
    try:
        t0 = time.perf_counter()
        with collect_stages() as timings, log_stage("move_furniture", plan.get("task_id")):
            if request.moves:
                moved = move_instances(plan, [m.model_dump() for m in request.moves], request.strength)
            elif request.furniture_placements is not None:
                moved = move_furniture(plan, request.furniture_placements, request.strength)
            else:
                raise MoveFurnitureError("要帶 moves 或 furniture_placements")
        elapsed = time.perf_counter() - t0
    except MoveFurnitureError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

    timing_runs = [*(plan.get("timing_runs") or []), {
        "kind": "move_furniture",
        "task_id": plan.get("task_id"),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_seconds": round(elapsed, 2),
        "timings": timings,
    }]
    scene_graph = moved["scene_graph"]
    # 回傳跟 /api/generate 同形狀，前端直接換掉手上的 plan 就能接著換風格、估價或再移
    return {
        **plan,
        **moved,
        "status": "success",
        "elapsed_time": f"{elapsed:.2f}s",
        "generated_image_url": _artifact_url(moved["generated_image_path"]),
        "composite_image_url": _artifact_url(moved["composite_image_path"]),
        "floor_plan_path": scene_graph.get("floor_plan_path"),
        "floor_plan_url": _artifact_url(scene_graph.get("floor_plan_path")),
        "timings": timings,
        "timing_runs": timing_runs,
    }


# ── Quotation ─────────────────────────────────────────────────────────────────

class QuotationRequest(BaseModel):
    image_path: str
    structured_requirement: Optional[dict] = None
    selected_furniture: List[dict] = []
    task_id: Optional[str] = None   # 帶了就把估價結果存回「我的設計」
    style_profile_id: Optional[str] = None   # 渲染圖的風格，推薦時同風格商品加分


@router.post("/api/quotation")
def get_quotation(req: QuotationRequest, user_id: str = Depends(get_user_id)):
    """手動觸發估價（使用者點「重新估價」按鈕），可帶入使用者在家具查詢頁手動選擇的家具。"""
    from designbridge.pricing.quotation import build_quotation
    if not _inside_artifacts(req.image_path):
        raise HTTPException(status_code=400, detail=f"路徑不合法：{req.image_path}")
    try:
        ensure_artifact(req.image_path, user_id)   # 重新開啟的設計：本機沒有圖就從 Storage 補回
        t0 = time.perf_counter()
        with collect_stages() as timings, log_stage("quotation", req.task_id):
            quotation = build_quotation(
                req.image_path,
                req.structured_requirement or {},
                preselected=req.selected_furniture,
                style_id=req.style_profile_id or "",
            )
        if quotation:
            # 前端把它接到 timing_runs 後面，完整流程耗時才包含估價
            quotation["timing_run"] = {
                "kind": "quotation",
                "task_id": req.task_id,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "elapsed_seconds": round(time.perf_counter() - t0, 2),
                "timings": timings,
            }
        if req.task_id and user_id:
            save_quotation(user_id, req.task_id, quotation)
        return quotation
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
def generate_panorama(request: PanoramaRequest, user_id: str = Depends(get_user_id)):
    """按需生成 Text2Room 全景圖，獨立於主要生成流程。"""
    if request.depth_path and not _inside_artifacts(request.depth_path):
        raise HTTPException(status_code=400, detail=f"路徑不合法：{request.depth_path}")
    out_dir = Path("artifacts/room_mesh") / request.task_id
    image_path = Path(request.image_path)

    _require_artifact_file(request.image_path, 404, user_id)

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

    if user_id:   # 登入的使用者：環景也存雲端，之後從「我的設計」繼續編輯時看得到
        save_panorama(user_id, request.task_id, t2r["panorama"])
    return {"room_panorama_url": _artifact_url(t2r["panorama"])}

# ── 在任何一張圖上搬家具（照片入口、直接描述的結果；CAD 結果走上面的 /api/move-furniture）──
class ImagePickRequest(BaseModel):
    image_path: str
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class ImageMoveRequest(BaseModel):
    image_path: str
    mask_path: str
    x: float = Field(ge=0, le=1)          # 家具底部（地板錨點）拖到的位置
    y: float = Field(ge=0, le=1)
    horizon_y: float = Field(default=0.45, ge=0, le=1)


@router.post("/api/image-move/pick")
def image_move_pick(request: ImagePickRequest, user_id: str = Depends(get_user_id)):
    """點圖上的家具，回傳去背圖層與地板錨點；沒點到家具回 {"mask_path": null}。"""
    from designbridge.render.image_move import pick

    if not _inside_artifacts(request.image_path):
        raise HTTPException(status_code=400, detail="路徑不合法")
    _require_artifact_file(request.image_path, 404, user_id)
    hit = pick(request.image_path, request.x, request.y, Path(Config.ARTIFACTS_DIR) / "render")
    if not hit:
        return {"mask_path": None}
    return {**hit, "layer_url": _artifact_url(hit["layer_path"])}


@router.post("/api/image-move")
def image_move_apply(request: ImageMoveRequest, user_id: str = Depends(get_user_id)):
    """把點選的家具搬到新位置：一次 inpaint 補舊位置、融新位置邊緣，房間其他像素不動。"""
    from designbridge.render.image_move import default_inpaint, move

    for p in (request.image_path, request.mask_path):
        if not _inside_artifacts(p):
            raise HTTPException(status_code=400, detail="路徑不合法")
    _require_artifact_file(request.image_path, 404, user_id)
    if not Path(request.mask_path).is_file():
        raise HTTPException(status_code=404, detail="選取已失效，請重新點選家具")
    out = Path(Config.ARTIFACTS_DIR) / "render" / f"move_{uuid.uuid4().hex[:10]}.png"
    with collect_stages() as timings, log_stage("image_move", None):
        try:
            move(request.image_path, request.mask_path, (request.x, request.y), request.horizon_y, out, default_inpaint)
        except (ValueError, RuntimeError) as e:
            raise HTTPException(status_code=502, detail=str(e))
    path = str(out).replace("\\", "/")
    return {"generated_image_path": path, "generated_image_url": _artifact_url(path), "timings": timings}
