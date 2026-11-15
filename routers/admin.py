"""後台管理：帳號角色與點數。角色存 app_metadata.role，點數在 user_credits 表（docs/sql/credits.sql）。"""
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from routers.common import activate_if_allowed, get_login_id, require_admin, user_role
from designbridge.style.style_supabase import _get_supabase

router = APIRouter()

_DEFAULT_CREDITS = 20   # 跟 user_credits.credits 的欄位預設值一致：還沒用過的帳號沒有資料列


def _credits_of(sb, ids: list) -> dict:
    if not ids:
        return {}
    rows = sb.table("user_credits").select("user_id, credits").in_("user_id", ids).execute().data
    return {r["user_id"]: r["credits"] for r in rows}


def _usage_since(sb, days: int) -> dict:
    """{user_id 或 None: 用量}；None 是對不到帳號的呼叫（本機免登入、背景預熱）。"""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        rows = sb.rpc("usage_summary", {"since": since}).execute().data or []
    except Exception as e:  # noqa: BLE001 — 還沒跑 docs/sql/usage.sql 時後台照常列帳號
        print(f"⚠️ [admin] 讀用量失敗：{e}")
        return {}
    return {r["user_id"]: {k: r[k] for k in ("llm_calls", "tokens", "images", "duration_s", "cost_usd")} for r in rows}


@router.get("/api/me")
def me(user_id: str = Depends(get_login_id)):
    if not user_id:   # 只有 DEV_NO_AUTH 的本機請求會沒有 user_id：當成開發者，看得到除錯面板
        return {"role": "admin", "credits": None}
    sb = _get_supabase()
    user = sb.auth.admin.get_user_by_id(user_id).user
    role = user_role(user)
    if role == "pending":
        role = activate_if_allowed(user)
    return {"role": role, "credits": None if role != "user" else _credits_of(sb, [user_id]).get(user_id, _DEFAULT_CREDITS)}


@router.get("/api/admin/users")
def list_users(page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=200),
               days: int = Query(30, ge=1, le=365), _: str = Depends(require_admin)):
    sb = _get_supabase()
    users = sb.auth.admin.list_users(page=page, per_page=per_page)
    credits = _credits_of(sb, [u.id for u in users])
    usage = _usage_since(sb, days)
    return {"users": [{
        "id": u.id,
        "email": u.email,
        "name": (u.user_metadata or {}).get("name"),
        "role": user_role(u),
        "credits": credits.get(u.id, _DEFAULT_CREDITS),
        "created_at": u.created_at,
        "last_sign_in_at": u.last_sign_in_at,
        "usage": usage.get(u.id),
    } for u in users], "page": page, "has_more": len(users) == per_page,
        "days": days,
        "total_cost_usd": sum(float(v["cost_usd"]) for v in usage.values()),
        "unassigned": usage.get(None)}


@router.get("/api/admin/users/{uid}/usage")
def user_usage(uid: str, limit: int = Query(100, ge=1, le=500), _: str = Depends(require_admin)):
    """單一帳號最近的每筆呼叫明細。"""
    rows = (_get_supabase().table("usage_events")
            .select("created_at, route, kind, model, prompt_tokens, completion_tokens, images, duration_s, queue_s, cost_usd")
            .eq("user_id", uid).order("created_at", desc=True).limit(limit).execute().data)
    return {"events": rows}


class AllowEntry(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    role: Literal["admin", "user"] = "user"


@router.get("/api/admin/allowlist")
def list_allowlist(_: str = Depends(require_admin)):
    """已加入名單、但還沒登入過的 email（登入開通後就會移出）。"""
    rows = _get_supabase().table("allowed_emails").select("email, role, added_at").order("added_at", desc=True).execute().data
    return {"entries": rows}


@router.post("/api/admin/allowlist")
def add_allowlist(body: AllowEntry, _: str = Depends(require_admin)):
    _get_supabase().table("allowed_emails").upsert({"email": body.email.lower(), "role": body.role}).execute()
    return {"status": "ok"}


@router.delete("/api/admin/allowlist/{email}")
def remove_allowlist(email: str, _: str = Depends(require_admin)):
    _get_supabase().table("allowed_emails").delete().eq("email", email.lower()).execute()
    return {"status": "ok"}


class UserPatch(BaseModel):
    role: Optional[Literal["admin", "user", "pending"]] = None
    credits: Optional[int] = Field(default=None, ge=0, le=1_000_000)


@router.patch("/api/admin/users/{uid}")
def update_user(uid: str, body: UserPatch, admin_id: str = Depends(require_admin)):
    sb = _get_supabase()
    if body.role is not None:
        if uid == admin_id and body.role != "admin":   # 避免把自己降級後沒人能管
            raise HTTPException(status_code=400, detail="不能移除自己的管理員權限")
        app_meta = sb.auth.admin.get_user_by_id(uid).user.app_metadata or {}
        # pending 存成 null：沒角色＝未開通，跟新註冊帳號一致
        sb.auth.admin.update_user_by_id(uid, {"app_metadata": {**app_meta, "role": None if body.role == "pending" else body.role}})
    if body.credits is not None:
        sb.table("user_credits").upsert({"user_id": uid, "credits": body.credits, "updated_at": datetime.now(timezone.utc).isoformat()}).execute()
    return {"status": "ok"}
