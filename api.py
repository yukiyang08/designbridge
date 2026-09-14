# DesignBridge FastAPI 後端
from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
import os
import time
import shutil
import uuid
from pathlib import Path
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

import json
import threading

_history_lock = threading.Lock()
_history_file = Path(__file__).parent / "artifacts" / "history.json"

def _save_history(record: dict) -> None:
    """Append a generation record to artifacts/history.json (thread-safe)."""
    with _history_lock:
        if _history_file.exists():
            try:
                history = json.loads(_history_file.read_text(encoding="utf-8"))
            except Exception:
                history = []
        else:
            history = []
        history.append(record)
        _history_file.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

# 匯入設計引擎
from designbridge import get_compiled_graph
from designbridge.style.style_apply import list_available_style_profiles
from style_kb.styles import STYLES


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


@asynccontextmanager
async def _app_lifespan(_: FastAPI):
    """Preload heavy ML stacks in background so the server accepts requests immediately."""
    import threading

    def _warmup():
        try:
            from designbridge.core.warmup import run_startup_warmup
            run_startup_warmup()
        except Exception as e:
            print(f"⚠️ DesignBridge startup warmup failed: {e}")

    threading.Thread(target=_warmup, daemon=True).start()
    yield


app = FastAPI(
    title="DesignBridge API",
    description="室內設計 AI 工作流接口",
    lifespan=_app_lifespan,
)

artifacts_dir = Path("artifacts")
artifacts_dir.mkdir(parents=True, exist_ok=True)
app.mount("/artifacts", StaticFiles(directory=str(artifacts_dir)), name="artifacts")

style_images_dir = Path("style_kb/images")
if style_images_dir.exists():
    app.mount("/style-images", StaticFiles(directory=str(style_images_dir)), name="style-images")

# 解決前後端跨域問題 (具備彈性與擴充性的解法)
cors_origins = os.getenv("CORS_ORIGINS", "").split(",") if os.getenv("CORS_ORIGINS") else []

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,             # 讀取 .env 中的自訂網域 (適合正式上線環境)
    allow_origin_regex=r"^https?://localhost:\d+$", # 允許所有 localhost 的開發埠號 (適合開發環境，不用再一直加 5174, 5175...)
    allow_methods=["*"],
    allow_headers=["*"],
)


# 1. 定義請求資料格式 (Pydantic Model)
class DesignRequest(BaseModel):
    text_prompt: str = ""
    edit_scope: float = 0.6
    style_profile_id: Optional[str] = None
    initial_image_path: Optional[str] = None
    style_reference_image_path: Optional[str] = None
    no_style_reference: bool = False
    refine_mode: bool = False  # 細部微調模式：強制 routing 到 design_adjuster
    output_aspect: str = "auto"  # 輸出長寬比：auto | 1:1 | 4:3 | 3:4 | 16:9 | 9:16
    mask_image_path: Optional[str] = None  # 手繪遮罩路徑（refine 模式選填）
    family_needs: List[str] = []
    fengshui_rules: List[str] = []
    style_method: str = "ai_analysis"
    floor_plan_path: Optional[str] = None   # 由 Step 1 產生的 2D 平面圖路徑
    scene_graph: Optional[dict] = None     # 由 Step 1 產生的完整 scene_graph（含家具座標）


class LayoutRequest(BaseModel):
    room_type: str = "living_room"   # living_room | bedroom | kitchen | study
    space_size_ping: float = 15.0    # 坪數（room_w/room_d 未指定時，用這個估算長寬）
    room_w: Optional[float] = None   # 自訂寬度（公尺），與 room_d 一起給才生效
    room_d: Optional[float] = None   # 自訂深度（公尺）
    furniture_list: List[str] = []   # 預計擺放的家具
    text_prompt: str = ""
    family_needs: List[str] = []
    fengshui_rules: List[str] = []

# 2. 延遲編譯 Graph（避免 uvicorn 啟動前長時間阻塞，導致前端連不上）
_compiled_graph = None


def _get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = get_compiled_graph()
    return _compiled_graph


@app.get("/api/health")
def health():
    """Lightweight readiness probe for the frontend (no ML load)."""
    return {"status": "ok"}


@app.post("/api/upload-image")
async def upload_image(file: UploadFile = File(...)):
    """接收前端上傳的圖片，儲存到 artifacts/uploads/ 並回傳本機路徑。"""
    upload_dir = Path("artifacts/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename).suffix if file.filename else ".png"
    dest = upload_dir / f"{uuid.uuid4()}{suffix}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"path": str(dest)}

_supabase_client = None

def _get_supabase():
    global _supabase_client
    if _supabase_client is None:
        from supabase import create_client
        _supabase_client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        )
    return _supabase_client

@app.get("/api/style-search")
def search_styles(
    query: str = "",
    style_id: str = "",
    top_k: int = 3,
    diverse: bool = False,
):
    """向量搜尋最相似的風格參考圖，回傳多筆候選供使用者選擇。

    diverse=True（前端在使用者沒填風格描述、也沒手動選風格時傳入）：每個風格各取一張，
    避免通用 fallback 查詢字（房型中文字/"interior design"）只集中命中一兩種風格。
    """
    from designbridge.style.style_supabase import _STYLE_PROMPTS
    from style_kb.styles import STYLES
    style_name_map = {sid: sname for sid, sname in STYLES}

    sid = style_id.strip() or ""
    q = query.strip() or sid or "interior design"
    try:
        from designbridge.style.style_supabase import query_style_images_supabase, query_style_images_diverse

        client = _get_supabase()
        if diverse and not sid:
            # per_style=3（不是 1）是刻意留給前端「下一輪」用的池子——向量搜尋本身是
            # 決定性的，同樣的查詢字重打一次結果不會變，所以一次多要幾張，前端就能在
            # 池子裡輪替顯示，不用每次都重打一樣的 query 卻拿到一樣的結果。
            results = query_style_images_diverse(text_query=q, per_style=3)[: min(top_k, 24)]
        else:
            results = query_style_images_supabase(
                text_query=q,
                style_id=sid or None,
                top_k=min(top_k, 24),
            )
        if not results:
            return []

        # 批次取 style_kb（兩筆查詢，不用 N+1）
        image_urls = [r.image_url for r in results]
        kb_res = client.table("style_images").select("image_url,style_kb").in_("image_url", image_urls).execute()
        kb_map = {r["image_url"]: r.get("style_kb") for r in (kb_res.data or [])}

        candidates = []
        for row in results:
            url = row.image_url          # DB join key
            display_url = row.display_url  # actually-reachable URL to show/round-trip
            s_id = row.style_id
            style_kb = kb_map.get(url)
            fallback = _STYLE_PROMPTS.get(s_id, _STYLE_PROMPTS.get("modern", {}))

            description = None
            tags: list[str] = []
            positive_prompt = fallback.get("positive", "")
            negative_prompt = fallback.get("negative", "")
            colors: dict = {}
            materials: list[str] = []

            if style_kb and isinstance(style_kb, dict):
                desc_raw = style_kb.get("description")
                # v2 schema: {"zh": "...", "en": "..."}；前端顯示用中文版
                description = desc_raw.get("zh") if isinstance(desc_raw, dict) else desc_raw
                tags_raw = (style_kb.get("style_info") or {}).get("tags")
                zh_tags = tags_raw.get("zh") if isinstance(tags_raw, dict) else tags_raw
                if isinstance(zh_tags, list):
                    tags = [str(t) for t in zh_tags if t][:5]
                ai = style_kb.get("ai_params") or {}
                prompts = ai.get("prompts") or {}
                positive_prompt = prompts.get("positive") or positive_prompt
                negative_prompt = prompts.get("negative") or negative_prompt

                # 資訊卡片（hover/點擊 ⓘ）用的補充資料，同樣來自 style_kb
                visual = style_kb.get("visual_elements") or {}
                colors = visual.get("colors") or {}
                for m in visual.get("materials") or []:
                    t = isinstance(m, dict) and m.get("type")
                    if t and t not in materials:
                        materials.append(t)
                materials = materials[:5]

            source_meta = {}
            candidates.append({
                "style_id": s_id,
                "style_name": style_name_map.get(s_id, source_meta.get("style", s_id)),
                "image_url": display_url,
                "similarity": round(float(row.similarity), 4),
                "description": description,
                "tags": tags,
                "positive_prompt": positive_prompt,
                "negative_prompt": negative_prompt,
                "colors": colors,
                "materials": materials,
            })
        return candidates
    except Exception as e:
        print(f"⚠️ style-search error: {e}")
        return []


@app.get("/api/style-preview")
def get_style_preview(
    query: str = "",
    style_id: str = "",
):
    """根據文字語意搜尋最符合的風格參考圖（Supabase pgvector），供前端即時預覽。"""
    sid = style_id.strip() or ""
    q = query.strip() or sid or "interior design"
    try:
        from designbridge.style.style_supabase import query_style_images_supabase

        results = query_style_images_supabase(
            text_query=q,
            style_id=sid or None,
            top_k=1,
        )
        if not results:
            return {"image_url": None}
        row = results[0]
        style_name = row.style_name or row.style_id
        return {
            "image_url": row.display_url,
            "style_name": style_name,
            "similarity": round(row.similarity, 4),
        }
    except Exception as e:
        print(f"⚠️ style-preview error: {e}")
        return {"image_url": None}


@app.get("/")
def read_root():
    return {"message": "DesignBridge API is running"}



@app.get("/api/history")
def get_history(limit: int = 0):
    """Return generation history, newest first. limit=0 means all."""
    if not _history_file.exists():
        return []
    try:
        records = json.loads(_history_file.read_text(encoding="utf-8"))
    except Exception:
        return []
    records = list(reversed(records))
    if limit > 0:
        records = records[:limit]
    for r in records:
        path = r.get("generated_image_path", "")
        if path and not r.get("generated_image_url"):
            r["generated_image_url"] = "http://localhost:8000/" + path.replace("\\", "/")
    return records


@app.delete("/api/history")
def delete_history(task_ids: List[str] = Query(...)):
    """Delete history records by task_ids."""
    if not _history_file.exists():
        return {"deleted": 0}
    with _history_lock:
        try:
            records = json.loads(_history_file.read_text(encoding="utf-8"))
        except Exception:
            return {"deleted": 0}
        id_set = set(task_ids)
        original = len(records)
        records = [r for r in records if r.get("task_id") not in id_set]
        _history_file.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"deleted": original - len(records)}


# ── 家具查詢 ──────────────────────────────────────────────────────────────────

@app.get("/api/furniture/categories")
def get_furniture_categories():
    """回傳家具 KB 中所有分類。"""
    from designbridge.pricing.furniture_kb import list_categories
    return list_categories()


@app.get("/api/furniture")
def get_furniture(
    category: str = "",
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
):
    """瀏覽 / 篩選家具清單（分類 + 價位區間）。"""
    from designbridge.pricing.furniture_kb import list_furniture
    return list_furniture(category=category, min_price=min_price, max_price=max_price)


@app.get("/api/style-profiles")
def get_style_profiles():
    # 優先回傳磁碟上已有聚合檔的風格
    available = list_available_style_profiles()
    if available:
        return [{"style_id": s["style_id"], "style_name": s["style_name"]} for s in available]
    # fallback：回傳 STYLES 定義的完整清單
    return [{"style_id": sid, "style_name": sname} for sid, sname in STYLES]

# ── Chat (Gemini) ────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str          # "user" | "assistant" | "system"
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    stream: bool = False


@app.post("/api/chat")
async def chat(request: ChatRequest):
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


@app.post("/api/generate-layout")
async def generate_layout(request: LayoutRequest):
    """Step 1: 根據坪數、家具清單生成 2D 平面配置圖。"""
    import math
    import uuid as _uuid

    try:
        from designbridge.layout.layout_agent import run_layout_agent
        from designbridge.layout.special_constraints import enrich_requirement

        if request.room_w and request.room_d:
            width, depth = round(request.room_w, 1), round(request.room_d, 1)
        else:
            total_m2 = request.space_size_ping * 3.306
            width = round(math.sqrt(total_m2 * 5 / 4), 1)
            depth = round(math.sqrt(total_m2 * 4 / 5), 1)

        furniture_list = [f.lower().replace(" ", "_") for f in request.furniture_list]

        structured_requirement: dict = {
            "user_description_raw": request.text_prompt,
            "design_description": request.text_prompt,
            "meta": {
                "room_type": request.room_type,
                "design_goal": "new_layout",
                "user_experience_level": "general",
            },
            "space_info": {
                "estimated_size": {"width": width, "height": 2.8, "depth": depth},
                "windows": [{"x": 0.5, "y": 0.0, "w": 0.2, "h": 0.02}],
                "doors": [{"x": 0.5, "y": 1.0, "w": 0.1, "h": 0.02}],
            },
            "style_preferences": {
                "primary_style": "", "secondary_style": None,
                "color_palette": [], "material_preferences": [],
                "style_strength": 0.7, "reference_images": [],
            },
            "layout_constraints": {
                "must_keep": [],
                "must_add": furniture_list,
                "must_remove": [],
                "immutable_regions": [],
                "functional_zones": [],
            },
            "edit_scope": {"scope_value": 1.0, "allowed_operations": ["layout"]},
            "priority_weights": {
                "layout_rationality": 0.6,
                "style_consistency": 0.2,
                "user_preference": 0.2,
            },
        }

        if request.family_needs or request.fengshui_rules:
            structured_requirement = enrich_requirement(
                structured_requirement, request.family_needs, request.fengshui_rules
            )

        task_id = str(_uuid.uuid4())
        from designbridge.core.timing import log_stage
        with log_stage("api.generate_layout.total", task_id=task_id):
            result = run_layout_agent(structured_requirement, task_id)

        floor_plan_path = (result.get("scene_graph") or {}).get("floor_plan_path")
        floor_plan_url = None
        if floor_plan_path:
            normalized = str(floor_plan_path).replace("\\", "/")
            if normalized.startswith("artifacts/"):
                floor_plan_url = f"http://localhost:8000/{normalized}"

        return {
            "status": "success",
            "task_id": task_id,
            "floor_plan_path": floor_plan_path,
            "floor_plan_url": floor_plan_url,
            "scene_graph": result.get("scene_graph"),
            "layout_render_config": _layout_render_config(),
            "room_w": width,
            "room_d": depth,
            "room_type": request.room_type,
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


class ParseFloorPlanRequest(BaseModel):
    image_path: str                       # 由 /api/upload-image 回傳的本機路徑
    room_type: str = "living_room"
    space_size_ping: float = 4.0
    room_w: Optional[float] = None   # 自訂寬度（公尺），與 room_d 一起給才生效
    room_d: Optional[float] = None   # 自訂深度（公尺）


@app.post("/api/parse-floor-plan")
async def parse_floor_plan(request: ParseFloorPlanRequest):
    """Step 1（上傳）：用 Gemini 視覺解析使用者上傳的 2D 平面圖，抽出家具座標，
    回傳與 /api/generate-layout 相同形狀的結果，讓上傳圖也能走精準的佈局管線。"""
    import math
    import uuid as _uuid

    if not Path(request.image_path).is_file():
        raise HTTPException(status_code=400, detail=f"找不到圖片：{request.image_path}")

    try:
        from designbridge.layout.layout_agent import parse_floor_plan_image

        if request.room_w and request.room_d:
            width, depth = round(request.room_w, 1), round(request.room_d, 1)
        else:
            total_m2 = request.space_size_ping * 3.306
            width = round(math.sqrt(total_m2 * 5 / 4), 1)
            depth = round(math.sqrt(total_m2 * 4 / 5), 1)

        task_id = str(_uuid.uuid4())
        scene_graph = parse_floor_plan_image(
            request.image_path, task_id,
            room_type=request.room_type, room_w=width, room_d=depth,
        )

        if not scene_graph or not scene_graph.get("furniture_placements"):
            # Gemini 沒解析出任何家具 → 讓前端退回「原圖當 Kontext 引導」的路徑
            return {
                "status": "no_furniture_detected",
                "task_id": task_id,
                "furniture_placements": [],
                "room_w": width,
                "room_d": depth,
                "room_type": request.room_type,
            }

        floor_plan_path = scene_graph.get("floor_plan_path")
        floor_plan_url = None
        if floor_plan_path:
            normalized = str(floor_plan_path).replace("\\", "/")
            if normalized.startswith("artifacts/"):
                floor_plan_url = f"http://localhost:8000/{normalized}"

        return {
            "status": "success",
            "task_id": task_id,
            "floor_plan_path": floor_plan_path,
            "floor_plan_url": floor_plan_url,
            "scene_graph": scene_graph,
            "furniture_placements": scene_graph.get("furniture_placements", []),
            "layout_render_config": _layout_render_config(),
            "room_w": width,
            "room_d": depth,
            "room_type": request.room_type,
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


class FloorPlanRenderRequest(BaseModel):
    furniture_placements: List[dict]
    room_w: float = 5.0
    room_d: float = 4.0
    room_type: str = "living_room"


@app.post("/api/render-floor-plan")
async def render_floor_plan(request: FloorPlanRenderRequest):
    """Re-render the 2D floor plan PNG from (edited) furniture placements."""
    import uuid as _uuid
    try:
        from designbridge.layout.layout_agent import FurnitureItem, _generate_floor_plan

        items: list = []
        for i, p in enumerate(request.furniture_placements):
            try:
                items.append(FurnitureItem(
                    id=str(p.get("id") or f"item_{i}"),
                    type=str(p.get("type", "default")),
                    x=float(p.get("x", 0.0)), y=float(p.get("y", 0.0)),
                    w=float(p.get("w", 0.1)), h=float(p.get("h", 0.1)),
                    rotation=float(p.get("rotation", 0.0)),
                ))
            except (TypeError, ValueError):
                continue

        task_id = str(_uuid.uuid4())
        floor_plan_path = _generate_floor_plan(
            items, task_id, room_type=request.room_type,
            room_w=request.room_w, room_d=request.room_d,
        )
        floor_plan_url = None
        if floor_plan_path:
            normalized = str(floor_plan_path).replace("\\", "/")
            if normalized.startswith("artifacts/"):
                floor_plan_url = f"http://localhost:8000/{normalized}"

        return {
            "status": "success",
            "floor_plan_path": floor_plan_path,
            "floor_plan_url": floor_plan_url,
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# 3. 建立 POST 路由
@app.post("/api/generate")
async def generate_design(request: DesignRequest):
    try:
        # 準備 LangGraph 初始狀態
        user_input = {
            "text_prompt": request.text_prompt,
            "edit_scope": request.edit_scope,
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
        if request.family_needs:
            user_input["family_needs"] = request.family_needs
        if request.fengshui_rules:
            user_input["fengshui_rules"] = request.fengshui_rules
        if request.style_method:
            user_input["style_method"] = request.style_method

        initial_state: dict = {"user_input": user_input}
        # 若 Step 1 已產生平面圖，預填入完整 scene_graph（含家具座標）讓 layout agent 跳過重複生成
        if request.scene_graph:
            initial_state["scene_graph"] = request.scene_graph
        elif request.floor_plan_path and Path(request.floor_plan_path).is_file():
            initial_state["scene_graph"] = {"floor_plan_path": request.floor_plan_path}

        # 執行工作流
        t0 = time.perf_counter()
        result = _get_graph().invoke(initial_state)
        elapsed = time.perf_counter() - t0
        generated_image_path = result.get("generated_image")
        generated_image_url = None
        if isinstance(generated_image_path, str):
            normalized = generated_image_path.replace("\\", "/")
            if normalized.startswith("artifacts/"):
                generated_image_url = f"http://localhost:8000/{normalized}"

        scene_graph = result.get("scene_graph") or {}
        floor_plan_path = scene_graph.get("floor_plan_path")
        floor_plan_url = None
        if floor_plan_path:
            normalized_fp = str(floor_plan_path).replace("\\", "/")
            if normalized_fp.startswith("artifacts/"):
                floor_plan_url = f"http://localhost:8000/{normalized_fp}"

        response = {
            "status": "success",
            "elapsed_time": f"{elapsed:.2f}s",
            "routing_decision": result.get("routing_decision"),
            "generated_image_path": generated_image_path,
            "generated_image_url": generated_image_url,
            "floor_plan_path": floor_plan_path,
            "floor_plan_url": floor_plan_url,
            "structured_requirement": result.get("structured_requirement"),
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
                style_ref_url = f"http://localhost:8000/{normalized_ref}"
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


@app.post("/api/quotation")
async def get_quotation(req: QuotationRequest):
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