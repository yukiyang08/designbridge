"""Generation history (artifacts/history.json) + its endpoints."""
import json
import threading
import time
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from routers.common import _artifact_url

router = APIRouter()

_history_lock = threading.Lock()
_history_file = Path(__file__).parent.parent / "artifacts" / "history.json"

def _write_history(records: list) -> None:
    """Atomic write: a crash mid-write can't leave a truncated history.json."""
    tmp = _history_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_history_file)


def _save_history(record: dict) -> None:
    """Append a generation record to artifacts/history.json (thread-safe)."""
    with _history_lock:
        history = []
        if _history_file.exists():
            try:
                history = json.loads(_history_file.read_text(encoding="utf-8"))
            except Exception:
                # keep the corrupt file instead of overwriting it with a fresh list
                _history_file.replace(_history_file.with_suffix(f".corrupt-{int(time.time())}.json"))
        history.append(record)
        _write_history(history)


@router.get("/api/history")
def get_history(limit: int = 0):
    """Return generation history, newest first. limit=0 means all."""
    if not _history_file.exists():
        return []
    try:
        with _history_lock:
            records = json.loads(_history_file.read_text(encoding="utf-8"))
    except Exception:
        return []
    records = list(reversed(records))
    if limit > 0:
        records = records[:limit]
    for r in records:
        # 每次依目前的 API_PUBLIC_URL 重算，舊紀錄裡存的網址換環境後才不會失效
        url = _artifact_url(r.get("generated_image_path"))
        if url:
            r["generated_image_url"] = url
    return records


@router.delete("/api/history")
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
        _write_history(records)
    return {"deleted": original - len(records)}


class FavoriteRequest(BaseModel):
    favorited: bool = True


@router.patch("/api/history/{task_id}/favorite")
def set_history_favorite(task_id: str, request: FavoriteRequest):
    """收藏／取消收藏一筆歷史紀錄。設計流程走完（預算估計那一步）之後，
    使用者按「收藏這個設計」就是呼叫這支，直接在既有的 history.json 上標記，
    不另外開一份收藏清單——歷史紀錄本來就是每次生成自動存的那份。"""
    if not _history_file.exists():
        raise HTTPException(status_code=404, detail="尚無歷史紀錄")
    with _history_lock:
        try:
            records = json.loads(_history_file.read_text(encoding="utf-8"))
        except Exception:
            raise HTTPException(status_code=500, detail="歷史紀錄讀取失敗")
        target = next((r for r in records if r.get("task_id") == task_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail="找不到這筆設計紀錄")
        target["favorited"] = request.favorited
        _write_history(records)
    return {"task_id": task_id, "favorited": request.favorited}
