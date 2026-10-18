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
    rows = _get_supabase().table("furniture_favorites").select("item").eq("user_id", user_id)         .order("position").execute().data
    return [r["item"] for r in rows]


@router.put("/api/furniture-favorites")
def put_furniture_favorites(body: FavoritesBody, user_id: str = Depends(get_user_id)):
    sb = _get_supabase()
    sb.table("furniture_favorites").delete().eq("user_id", user_id).execute()
    rows = {}  # 以 item_key 去重，避免同一批 insert 撞主鍵
    for i, item in enumerate(body.items):
        rows[_key(item)] = {"user_id": user_id, "item_key": _key(item), "item": item, "position": i}
    if rows:
        sb.table("furniture_favorites").insert(list(rows.values())).execute()
    return {"count": len(rows)}
