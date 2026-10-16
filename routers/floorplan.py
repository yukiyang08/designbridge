"""Layout / floor plan endpoints (Step 1 of the design flow)."""
import uuid
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from routers.common import (
    DesignRequest, _artifact_url, _build_user_input, _layout_render_config, _require_artifact_file,
)

router = APIRouter()

class LayoutRequest(BaseModel):
    room_type: str = "living_room"   # living_room | bedroom | kitchen | study
    space_size_ping: float = 15.0    # 坪數（room_w/room_d 未指定時，用這個估算長寬）
    room_w: Optional[float] = None   # 自訂寬度（公尺），與 room_d 一起給才生效
    room_d: Optional[float] = None   # 自訂深度（公尺）
    furniture_list: List[str] = []   # 預計擺放的家具
    text_prompt: str = ""
    fengshui_rules: List[str] = []


class RoomProgramRequest(BaseModel):
    """輸入：整層樓的房間需求（幾房幾廳…）+ 總坪數，獨立於既有單房家具佈局流程。"""
    bedroom_count: int = 2
    living_count: int = 1
    bathroom_count: int = 1
    dining_count: int = 0
    kitchen_count: int = 1
    balcony_count: int = 1
    total_ping: float = 25.0
    extra_rooms: List[str] = []      # 自訂空間名稱（書房、儲藏室…），每個 1 間
    room_w: Optional[float] = None   # 自訂整層外框寬/深（公尺），兩者都給才生效，此時 total_ping 以 w*d 換算
    room_d: Optional[float] = None



@router.post("/api/generate-layout")
def generate_layout(request: LayoutRequest):
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
            "priority_weights": {
                "layout_rationality": 0.6,
                "style_consistency": 0.2,
                "user_preference": 0.2,
            },
        }

        if request.fengshui_rules:
            structured_requirement = enrich_requirement(
                structured_requirement, request.fengshui_rules
            )

        task_id = str(_uuid.uuid4())
        from designbridge.core.timing import log_stage
        with log_stage("api.generate_layout.total", task_id=task_id):
            result = run_layout_agent(structured_requirement, task_id)

        floor_plan_path = (result.get("scene_graph") or {}).get("floor_plan_path")
        floor_plan_url = _artifact_url(floor_plan_path)

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


@router.post("/api/generate-room-plan")
def generate_room_plan_endpoint(request: RoomProgramRequest):
    """獨立功能：根據房間數量需求（幾房幾廳幾衛幾廚幾陽台）+ 總坪數，
    生成整層樓的房間配置 CAD 平面圖（牆、門、窗、尺寸標註），與既有單房家具佈局流程無關。"""
    import uuid as _uuid

    from designbridge.roomplan import RoomProgramError, generate_room_plan

    if not any([
        request.extra_rooms, request.dining_count,
        request.bedroom_count, request.living_count, request.bathroom_count,
        request.kitchen_count, request.balcony_count,
    ]):
        raise HTTPException(status_code=400, detail="至少需要一個房間")

    try:
        program = request.dict()
        if request.room_w and request.room_d:
            program["total_ping"] = request.room_w * request.room_d / 3.306
        task_id = str(_uuid.uuid4())
        result = generate_room_plan(program, task_id)
    except RoomProgramError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

    svg_url = _artifact_url(result.svg_path)

    return {
        "status": "success",
        "task_id": task_id,
        "total_ping": program["total_ping"],
        "total_m2": result.total_m2,
        "bounding_w_m": result.bounding_w_m,
        "bounding_d_m": result.bounding_d_m,
        "rooms": [r.to_dict() for r in result.rooms],
        "walls": [w.to_dict() for w in result.walls],
        "doors": [d.to_dict() for d in result.doors],
        "windows": [w.to_dict() for w in result.windows],
        "svg_path": result.svg_path,
        "svg_url": svg_url,
        "svg_markup": result.svg_markup,
        "warnings": result.warnings,
    }


class ParseFloorPlanRequest(BaseModel):
    image_path: str                       # 由 /api/upload-image 回傳的本機路徑
    room_type: str = "living_room"
    space_size_ping: float = 4.0
    room_w: Optional[float] = None   # 自訂寬度（公尺），與 room_d 一起給才生效
    room_d: Optional[float] = None   # 自訂深度（公尺）


@router.post("/api/parse-floor-plan")
def parse_floor_plan(request: ParseFloorPlanRequest):
    """Step 1（上傳）：用 Gemini 視覺解析使用者上傳的 2D 平面圖，抽出家具座標，
    回傳與 /api/generate-layout 相同形狀的結果，讓上傳圖也能走精準的佈局管線。"""
    import math
    import uuid as _uuid

    _require_artifact_file(request.image_path)

    try:
        from designbridge.layout.floorplan_parse import parse_floor_plan_image

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
        floor_plan_url = _artifact_url(floor_plan_path)

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


class DetectRoomsRequest(BaseModel):
    image_path: str


@router.post("/api/detect-rooms")
def detect_rooms(request: DetectRoomsRequest):
    """整戶平面圖上傳後，先抓出每個房間的邊界框，讓使用者選要看哪一間。"""
    _require_artifact_file(request.image_path)

    try:
        from designbridge.layout.floorplan_parse import detect_rooms_in_floor_plan

        rooms = detect_rooms_in_floor_plan(request.image_path)
        return {"rooms": rooms or []}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


class CropFloorPlanRequest(BaseModel):
    image_path: str
    x: float
    y: float
    w: float
    h: float


@router.post("/api/crop-floor-plan")
def crop_floor_plan(request: CropFloorPlanRequest):
    """依使用者選定的房間邊界框，從整戶平面圖裁出單一房間的子圖。"""
    _require_artifact_file(request.image_path)

    try:
        from PIL import Image

        img = Image.open(request.image_path)
        img_w, img_h = img.size
        pad = 0.03  # 留一點邊界，避免牆線剛好被切到
        x0 = max(0.0, request.x - pad)
        y0 = max(0.0, request.y - pad)
        x1 = min(1.0, request.x + request.w + pad)
        y1 = min(1.0, request.y + request.h + pad)
        box = (int(x0 * img_w), int(y0 * img_h), int(x1 * img_w), int(y1 * img_h))
        cropped = img.crop(box)

        upload_dir = Path("artifacts/uploads")
        upload_dir.mkdir(parents=True, exist_ok=True)
        dest = upload_dir / f"{uuid.uuid4()}_room.png"
        cropped.save(dest)
        return {"path": str(dest)}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


class FloorPlanRenderRequest(BaseModel):
    furniture_placements: List[dict]
    room_w: float = 5.0
    room_d: float = 4.0
    room_type: str = "living_room"


@router.post("/api/render-floor-plan")
def render_floor_plan(request: FloorPlanRenderRequest):
    """Re-render the 2D floor plan PNG from (edited) furniture placements."""
    import uuid as _uuid
    try:
        from designbridge.layout.layout_items import FurnitureItem
        from designbridge.layout.floorplan_render import _generate_floor_plan

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
        floor_plan_url = _artifact_url(floor_plan_path)

        return {
            "status": "success",
            "floor_plan_path": floor_plan_path,
            "floor_plan_url": floor_plan_url,
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/plan-layout")
def plan_layout(request: DesignRequest):
    """只跑 RA + 視覺前處理 + layout_agent，不生圖——給前端 3D 佈局預覽用，讓使用者能在
    真正花時間/花錢生圖之前先確認佈局。回傳的 dict 可以原樣塞進 /api/generate 的 `plan`
    欄位，跳過這裡已經做過的事，直接進 renderer。"""
    try:
        from designbridge.core.nodes import (
            requirement_analyzer, visual_preprocessing_local,
            layout_and_style_agent_stub,
        )

        state: dict = {"user_input": _build_user_input(request)}
        state.update(requirement_analyzer(state))  # routing_decision 也是這裡決定的
        state.update(visual_preprocessing_local(state))
        state.update(layout_and_style_agent_stub(state))

        scene_graph = state.get("scene_graph")
        return {
            "status": "success",
            "task_id": state.get("task_id"),
            "routing_decision": state.get("routing_decision"),
            "structured_requirement": state.get("structured_requirement"),
            "vision_features": state.get("vision_features"),
            "scene_graph": scene_graph,
            "style_params": state.get("style_params"),
            "layout_render_config": _layout_render_config() if scene_graph else None,
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
