"""風水＋動線健檢：報告、一鍵修正、照片健檢。"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from routers.common import _require_artifact_file, get_user_id

router = APIRouter()


class AuditRequest(BaseModel):
    placements: List[dict]
    room_w: float = 5.0
    room_d: float = 4.0
    room_type: Optional[str] = None
    # 兩者都不給 = 用預設門窗推估，報告會標記 assumed_openings
    doors: Optional[List[dict]] = None
    windows: Optional[List[dict]] = None
    rules: Optional[List[str]] = None   # 不給 = 房型相關的全部規則


class FixRequest(AuditRequest):
    rules: List[str]


class PhotoAuditRequest(BaseModel):
    image_path: str
    room_type: Optional[str] = None


@router.post("/api/fengshui/audit")
def fengshui_audit(request: AuditRequest):
    from designbridge.layout.fengshui_audit import audit_layout
    return audit_layout(
        request.placements, request.room_w, request.room_d, request.room_type,
        request.doors, request.windows, request.rules,
    )


@router.post("/api/fengshui/fix")
def fengshui_fix(request: FixRequest):
    from designbridge.layout.fengshui_audit import (
        DEFAULT_DOORS, DEFAULT_WINDOWS, audit_layout, fix_layout,
    )
    assumed = request.doors is None and request.windows is None
    doors = DEFAULT_DOORS if assumed else (request.doors or [])
    windows = DEFAULT_WINDOWS if assumed else (request.windows or [])
    placements = fix_layout(
        request.placements, doors, windows, request.rules, request.room_w, request.room_d,
    )
    moved = [
        p.get("id") for p, q in zip(placements, request.placements)
        if (p.get("x"), p.get("y")) != (q.get("x"), q.get("y"))
    ]
    report = audit_layout(
        placements, request.room_w, request.room_d, request.room_type,
        None if assumed else doors, None if assumed else windows, request.rules,
    )
    return {"placements": placements, "moved": moved, "report": report}


@router.post("/api/fengshui/photo-audit")
def fengshui_photo_audit(request: PhotoAuditRequest, user_id: str = Depends(get_user_id)):
    """照片 → Gemini 推估俯視平面 → 全部相關規則＋動線打分。"""
    _require_artifact_file(request.image_path)
    from designbridge.layout.fengshui_audit import audit_layout
    from designbridge.layout.photo_fengshui import parse_room_photo

    try:
        plan = parse_room_photo(request.image_path, request.room_type)
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    if not plan:
        raise HTTPException(status_code=422, detail="無法從照片辨識出房間配置，請換一張較完整的照片")

    report = audit_layout(
        plan["placements"], plan["room_w"], plan["room_d"], plan["room_type"],
        plan["doors"], plan["windows"],
    )
    return {"plan": plan, "report": report}
