"""家具收藏：每位使用者一份清單，整份覆寫（量小，不做逐筆增刪）。"""
from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from designbridge.style.style_supabase import _get_supabase
from routers.common import get_user_id

router = APIRouter()


class FavoritesBody(BaseModel):
    items: List[dict]


def _key(item: dict) -> str:
    return str(item.get("id") or item.get("url") or f"{item.get('name')}__{item.get('category')}")


@router.get("/api/furniture-favorites")
def get_furniture_favorites(user_id: str = Depends(get_user_id)):
    if not user_id:   # 本機免登入模式（DEV_NO_AUTH）沒有使用者
        return []
    rows = _get_supabase().table("furniture_favorites").select("item").eq("user_id", user_id)         .order("position").execute().data
    return [r["item"] for r in rows]


@router.put("/api/furniture-favorites")
def put_furniture_favorites(body: FavoritesBody, user_id: str = Depends(get_user_id)):
    if not user_id:
        return {"count": 0}
    sb = _get_supabase()
    rows = {}  # 以 item_key 去重，避免同一批 upsert 撞主鍵
    for i, item in enumerate(body.items):
        rows[_key(item)] = {"user_id": user_id, "item_key": _key(item), "item": item, "position": i}
    # 先寫入再刪多出來的：中途失敗最多留下舊項目，不會把雲端清空
    if rows:
        sb.table("furniture_favorites").upsert(list(rows.values()), on_conflict="user_id,item_key").execute()
    existing = sb.table("furniture_favorites").select("item_key").eq("user_id", user_id).execute().data
    stale = [r["item_key"] for r in existing if r["item_key"] not in rows]
    if stale:
        sb.table("furniture_favorites").delete().eq("user_id", user_id).in_("item_key", stale).execute()
    return {"count": len(rows)}
