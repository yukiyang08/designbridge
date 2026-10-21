"""我的設計：每次生成存進 Supabase designs 表（依 user_id 隔離），圖片放 Storage。"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from designbridge.style.style_supabase import _get_supabase
from routers.common import _is_artifact_file, get_user_id

router = APIRouter()

_BUCKET = "designs"
_SIGNED_TTL = 24 * 3600


def _upload(sb, user_id: str, task_id: str, local, suffix_tag: str = "") -> str | None:
    """本機檔上傳 Storage，回傳 key；失敗不擋紀錄，只是列表上沒圖。"""
    if not (local and Path(local).is_file()):
        return None
    key = f"{user_id}/{task_id}{suffix_tag}{Path(local).suffix}"
    try:
        sb.storage.from_(_BUCKET).upload(key, Path(local).read_bytes(), {"upsert": "true"})
        return key
    except Exception as e:
        print(f"[history] 上傳失敗：{e}")
        return None


def _save_cad_plan(sb, user_id: str, project_id: str, cad_plan: dict) -> None:
    """整層 CAD 平面圖（牆／門／窗／尺寸標註）：結構化資料存 projects.cad_plan，SVG 上傳 Storage。"""
    svg_path = None
    local = cad_plan.get("svg_path")
    # 路徑來自前端，只收 artifacts/ 底下的 .svg，避免被拿來讀任意本機檔
    if local and str(local).lower().endswith(".svg") and _is_artifact_file(local):
        key = f"{user_id}/projects/{project_id}_plan.svg"
        try:
            sb.storage.from_(_BUCKET).upload(
                key, Path(local).read_bytes(), {"upsert": "true", "content-type": "image/svg+xml"})
            svg_path = key
        except Exception as e:
            print(f"[history] CAD 平面圖上傳失敗：{e}")
    data = {k: v for k, v in cad_plan.items() if k not in ("svg_markup", "svg_path", "svg_url")}
    patch = {"cad_plan": data}
    if svg_path:
        patch["cad_svg_path"] = svg_path
    sb.table("projects").update(patch).eq("id", project_id).eq("user_id", user_id).execute()


def _cad_summary(plan: dict | None) -> dict | None:
    """列表只需要尺寸摘要；完整牆／門／窗資料留在資料庫，之後要還原編輯再取。"""
    if not plan:
        return None
    return {
        "total_m2": plan.get("total_m2"),
        "bounding_w_m": plan.get("bounding_w_m"),
        "bounding_d_m": plan.get("bounding_d_m"),
        "rooms": [
            {"id": r.get("id"), "label_zh": r.get("label_zh"), "w": r.get("w"), "h": r.get("h"),
             "area_m2": r.get("actual_area_m2")}
            for r in plan.get("rooms") or []
        ],
    }


def _user_upload(p):
    """只有使用者自己上傳的檔（artifacts/uploads）才當作輸入照片存；refine 的上一張渲染圖不算。"""
    return p if p and "uploads" in Path(p).parts else None


def _save_history(user_id: str, record: dict, floor_plan_path=None,
                  source_photo=None, style_ref=None,
                  project_id=None, space_id=None, space_name=None,
                  cad_plan=None) -> None:
    """存一筆生成紀錄（渲染圖、平面圖、使用者上傳的照片上傳 Storage）。"""
    sb = _get_supabase()
    tid = record["task_id"]
    title = (record.get("text_prompt") or "").strip()[:30] or "未命名設計"
    project_id = project_id or str(uuid.uuid4())   # 沒帶就自成一個設計
    # 同一設計第一次存才建；之後各空間的渲染圖掛在同一個 project 下
    sb.table("projects").upsert({"id": project_id, "user_id": user_id, "title": title},
                                on_conflict="id", ignore_duplicates=True).execute()
    if cad_plan:
        _save_cad_plan(sb, user_id, project_id, cad_plan)
    sb.table("designs").upsert({
        "project_id": project_id,
        "space_id": space_id or "main",
        "space_name": space_name or "主要空間",
        "task_id": tid,
        "user_id": user_id,
        "title": title,
        "record": record,
        "image_path": _upload(sb, user_id, tid, record.get("generated_image_path")),
        "floor_plan_path": _upload(sb, user_id, tid, floor_plan_path, "_plan"),
        "source_photo_path": _upload(sb, user_id, tid, _user_upload(source_photo), "_photo"),
        "style_ref_path": _upload(sb, user_id, tid, _user_upload(style_ref), "_styleref"),
    }).execute()
    _sync_space_state(sb, user_id, project_id, space_id or "main", space_name, record)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sync_space_state(sb, user_id: str, project_id: str, space_id: str, space_name, record: dict) -> None:
    """每次生成順手更新這個空間「現在的狀態」（用哪一版、做完了、最新擺放），designs 本身只增不改。
    失敗只記 log，不影響生成結果。"""
    try:
        # project_id 來自前端：不是自己的專案就不寫，免得蓋掉別人的空間狀態
        owner = sb.table("projects").select("user_id").eq("id", project_id).limit(1).execute().data
        if not owner or owner[0]["user_id"] != user_id:
            return
        row = {"project_id": project_id, "space_id": space_id, "user_id": user_id,
               "space_name": space_name or "主要空間", "status": "done",
               "current_task_id": record["task_id"], "updated_at": _now()}
        placements = (record.get("scene_graph") or {}).get("furniture_placements")
        if placements:
            row["placements"] = placements
        if record.get("space_dims"):
            row["dims"] = record["space_dims"]
        sb.table("project_spaces").upsert(row, on_conflict="project_id,space_id").execute()
        sb.table("projects").update({"updated_at": _now()}).eq("id", project_id).execute()
    except Exception as e:
        print(f"[history] 更新空間狀態失敗（不影響生成）：{e}")


def save_panorama(user_id: str, task_id: str, local) -> str | None:
    """環景圖（PNG，約 0.5–1.2 MB）傳 Storage，key 記在這一版 designs 上；失敗回 None，不擋環景本身。"""
    try:
        sb = _get_supabase()
        key = _upload(sb, user_id, task_id, local, "_pano")
        if key:
            sb.table("designs").update({"pano_path": key}).eq("user_id", user_id).eq("task_id", task_id).execute()
        return key
    except Exception as e:
        print(f"[history] 環景存檔失敗：{e}")
        return None


def save_quotation(user_id: str, task_id: str, quotation: dict) -> None:
    _get_supabase().table("designs").update({"quotation": quotation})         .eq("user_id", user_id).eq("task_id", task_id).execute()


@router.get("/api/history")
def get_history(limit: int = 0, user_id: str = Depends(get_user_id)):
    """目前使用者的設計，新到舊。limit=0 表示全部。"""
    # 本機免登入模式（DEV_NO_AUTH）沒有使用者：沒有雲端資料可讀寫
    if not user_id:
        return []
    sb = _get_supabase()
    q = sb.table("designs").select("record,image_path,floor_plan_path,source_photo_path,style_ref_path,title,quotation,project_id,space_id,space_name").eq("user_id", user_id).order("created_at", desc=True)
    if limit > 0:
        q = q.limit(limit)
    rows = q.execute().data
    pids = list({r["project_id"] for r in rows})
    projects = {p["id"]: p for p in (
        sb.table("projects").select("id,cad_plan,cad_svg_path").in_("id", pids).execute().data if pids else [])}
    paths = [p for r in rows for p in (r["image_path"], r["floor_plan_path"], r["source_photo_path"], r["style_ref_path"]) if p]
    paths += [p["cad_svg_path"] for p in projects.values() if p["cad_svg_path"]]
    signed = {}
    if paths:
        res = sb.storage.from_(_BUCKET).create_signed_urls(paths, _SIGNED_TTL)
        signed = {x["path"]: x["signedURL"] for x in res if x.get("signedURL")}
    out = []
    for r in rows:
        rec = r["record"]
        # 圖片以 Storage 簽名網址為準；generated_image_path 保留給估價等需要本機檔案的流程
        rec["generated_image_url"] = signed.get(r["image_path"]) or rec.get("generated_image_url")
        rec["floor_plan_url"] = signed.get(r["floor_plan_path"])
        rec["source_photo_url"] = signed.get(r["source_photo_path"])
        rec["style_ref_url"] = signed.get(r["style_ref_path"])
        proj = projects.get(r["project_id"]) or {}
        rec["cad_svg_url"] = signed.get(proj.get("cad_svg_path"))
        rec["cad_summary"] = _cad_summary(proj.get("cad_plan"))
        rec["title"] = r["title"]
        rec["project_id"], rec["space_id"], rec["space_name"] = r["project_id"], r["space_id"], r["space_name"]
        rec["quotation"] = r["quotation"]
        out.append(rec)
    return out


@router.delete("/api/history")
def delete_history(task_ids: List[str] = Query(...), user_id: str = Depends(get_user_id)):
    # 本機免登入模式（DEV_NO_AUTH）沒有使用者：沒有雲端資料可讀寫
    if not user_id:
        raise HTTPException(status_code=404, detail="本機免登入模式沒有雲端紀錄")
    sb = _get_supabase()
    rows = sb.table("designs").delete().eq("user_id", user_id).in_("task_id", task_ids).execute().data
    paths = [p for r in rows for p in (r.get("image_path"), r.get("floor_plan_path"), r.get("source_photo_path"), r.get("style_ref_path"), r.get("pano_path")) if p]
    # 設計底下的圖都刪光了，連同設計本身與 CAD 平面圖一起清掉
    for pid in {r["project_id"] for r in rows}:
        if not sb.table("designs").select("task_id").eq("project_id", pid).limit(1).execute().data:
            gone = sb.table("projects").delete().eq("id", pid).eq("user_id", user_id).execute().data
            paths += [p["cad_svg_path"] for p in gone if p.get("cad_svg_path")]
    if paths:
        sb.storage.from_(_BUCKET).remove(paths)
    return {"deleted": len(rows)}

# ── 繼續編輯：還原一個設計所需的全部資料，與前端把「現在的狀態」寫回來 ──────────────

@router.get("/api/projects/{project_id}")
def get_project(project_id: str, user_id: str = Depends(get_user_id)):
    """一個設計的完整還原資料：整層平面圖、設定、各空間目前採用的那一版（圖用簽名網址）。
    舊設計沒有 project_spaces 時，從 designs 取每個空間最新一筆推出來。"""
    # 本機免登入模式（DEV_NO_AUTH）沒有使用者：沒有雲端資料可讀寫
    if not user_id:
        raise HTTPException(status_code=404, detail="找不到這個設計")
    sb = _get_supabase()
    proj = (sb.table("projects").select("id,title,plan_source,settings,cad_plan,cad_svg_path")
            .eq("id", project_id).eq("user_id", user_id).limit(1).execute().data)
    if not proj:
        raise HTTPException(status_code=404, detail="找不到這個設計")
    proj = proj[0]
    designs = (sb.table("designs").select("task_id,record,image_path,floor_plan_path,source_photo_path,style_ref_path,pano_path,quotation,space_id,space_name")
               .eq("project_id", project_id).eq("user_id", user_id).order("created_at", desc=True).execute().data)
    saved = {s["space_id"]: s for s in (sb.table("project_spaces").select("*")
             .eq("project_id", project_id).eq("user_id", user_id).execute().data)}
    by_space: dict = {}
    for d in designs:                                  # 新到舊
        by_space.setdefault(d["space_id"] or "main", []).append(d)

    spaces = []
    for sid in list(dict.fromkeys([*saved, *by_space])):
        ds = by_space.get(sid, [])
        s = saved.get(sid) or {"space_id": sid, "space_name": ds[0]["space_name"] if ds else None, "status": "done",
                               "dims": ds[0]["record"].get("space_dims") if ds else None,
                               "placements": None, "current_task_id": ds[0]["task_id"] if ds else None}
        cur = next((d for d in ds if d["task_id"] == s.get("current_task_id")), ds[0] if ds else None)
        spaces.append({**s, "design": cur})

    paths = [p for sp in spaces if sp["design"]
             for p in (sp["design"]["image_path"], sp["design"]["floor_plan_path"],
                       sp["design"]["source_photo_path"], sp["design"]["style_ref_path"],
                       sp["design"]["pano_path"]) if p]   # 環景屬於「那一版渲染圖」，所以掛在 designs 上
    if proj.get("cad_svg_path"):
        paths.append(proj["cad_svg_path"])
    signed = {}
    if paths:
        res = sb.storage.from_(_BUCKET).create_signed_urls(paths, _SIGNED_TTL)
        signed = {x["path"]: x["signedURL"] for x in res if x.get("signedURL")}

    svg_markup = None
    if proj.get("cad_svg_path"):
        try:
            svg_markup = sb.storage.from_(_BUCKET).download(proj["cad_svg_path"]).decode("utf-8")
        except Exception as e:
            print(f"[history] 讀取 CAD 平面圖 SVG 失敗：{e}")

    out_spaces = []
    for sp in spaces:
        d = sp.pop("design")
        render = None
        if d:
            render = d["record"]
            # 圖片以 Storage 簽名網址為準；generated_image_path 是本機路徑，缺檔時由 ensure_artifact 補回
            render["generated_image_url"] = signed.get(d["image_path"]) or render.get("generated_image_url")
            render["floor_plan_url"] = signed.get(d["floor_plan_path"])
            render["source_photo_url"] = signed.get(d["source_photo_path"])
            render["style_ref_url"] = signed.get(d["style_ref_path"])
            render["quotation"] = d["quotation"]
        out_spaces.append({**sp, "pano_url": signed.get(d["pano_path"]) if d else None, "render": render})

    return {
        "id": proj["id"], "title": proj["title"],
        "plan_source": proj["plan_source"] or ("cad" if proj["cad_plan"] else None),
        "settings": proj["settings"] or {},
        "cad_plan": proj["cad_plan"], "cad_svg_markup": svg_markup,
        "spaces": out_spaces,
    }


class SpaceState(BaseModel):
    space_id: str = Field(max_length=64)
    space_name: Optional[str] = Field(default=None, max_length=32)
    room_type: Optional[str] = Field(default=None, max_length=32)
    dims: Optional[dict] = None
    status: Optional[Literal["active", "done"]] = None   # 預設 None：沒帶就不動，不能每次都把 done 蓋回 active
    placements: Optional[list] = None
    current_task_id: Optional[str] = Field(default=None, max_length=64)


class ProjectState(BaseModel):
    plan_source: Optional[str] = Field(default=None, max_length=16)
    settings: Optional[dict] = None
    spaces: List[SpaceState] = Field(default_factory=list, max_length=64)


_MAX_STATE_BYTES = 200_000   # 單一 settings / placements 的上限，擋掉亂塞的大 JSON


def _check_size(obj, what: str) -> None:
    if obj is not None and len(json.dumps(obj, ensure_ascii=False)) > _MAX_STATE_BYTES:
        raise HTTPException(status_code=413, detail=f"{what}太大")


@router.put("/api/projects/{project_id}/state")
def put_project_state(project_id: str, body: ProjectState, user_id: str = Depends(get_user_id)):
    """前端在切房間、編輯器停手、批次完成時寫回「現在的狀態」。只更新有帶的欄位，沒帶的不會被清掉。"""
    # 本機免登入模式（DEV_NO_AUTH）沒有使用者：沒有雲端資料可讀寫
    if not user_id:
        raise HTTPException(status_code=404, detail="找不到這個設計")
    sb = _get_supabase()
    if not sb.table("projects").select("id").eq("id", project_id).eq("user_id", user_id).limit(1).execute().data:
        raise HTTPException(status_code=404, detail="找不到這個設計")
    _check_size(body.settings, "設定")
    for s in body.spaces:
        _check_size(s.placements, "家具擺放")

    patch = {"updated_at": _now()}
    if body.plan_source is not None:
        patch["plan_source"] = body.plan_source
    if body.settings is not None:
        patch["settings"] = body.settings
    sb.table("projects").update(patch).eq("id", project_id).eq("user_id", user_id).execute()

    if body.spaces:
        wanted = [s.current_task_id for s in body.spaces if s.current_task_id]
        valid = {r["task_id"] for r in (sb.table("designs").select("task_id").eq("user_id", user_id)
                 .eq("project_id", project_id).in_("task_id", wanted).execute().data)} if wanted else set()
        rows = []
        for s in body.spaces:
            row = {**s.model_dump(exclude_none=True), "project_id": project_id, "user_id": user_id, "updated_at": _now()}
            if row.get("current_task_id") not in valid:
                row.pop("current_task_id", None)   # 不是這個設計的版本就不寫，也不要清掉原本的
            rows.append(row)
        sb.table("project_spaces").upsert(rows, on_conflict="project_id,space_id").execute()
    return {"ok": True}
