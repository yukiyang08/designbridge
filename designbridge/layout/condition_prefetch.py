"""Union 路徑的條件圖（候選相機評分、家具輪廓邊緣圖、房間深度圖）：預先計算並快取。

使用者在風格選擇頁停留時後端是閒的，前端先呼叫 prefetch；按生圖時 renderer 用同樣的參數
呼叫 get_conditions，命中就直接讀檔，沒命中（家具被改、比例換了）就照原樣現算。
"""

from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import Future
from dataclasses import asdict
from pathlib import Path
from typing import Any

from designbridge.core.config import Config
from designbridge.core.timing import log_stage

_lock = threading.Lock()
_jobs: dict[str, Future] = {}
_MAX_JOBS = 16


def normalize_placements(placements: list[dict]) -> list[dict]:
    """跟 reproject_scene_graph 同樣的裁切，鍵值才會跟 renderer 收到的家具座標對上。"""
    from designbridge.layout.layout_enforce import _clip_to_room
    from designbridge.layout.layout_items import FurnitureItem

    items = [
        FurnitureItem(
            id=str(p.get("id", "")), type=str(p.get("type", "default")),
            x=float(p.get("x", 0)), y=float(p.get("y", 0)),
            w=float(p.get("w", 0.1)), h=float(p.get("h", 0.1)),
            rotation=float(p.get("rotation", 0.0)), product_id=str(p.get("product_id") or ""),
        )
        for p in placements
    ]
    return [it.to_dict() for it in _clip_to_room(items)]


def cache_key(placements: list[dict], room_w: float, room_d: float, width: int, height: int) -> str:
    rows = [
        [str(p.get("type", "")), *(round(float(p.get(k) or 0), 3) for k in ("x", "y", "w", "h", "rotation"))]
        for p in placements
    ]
    raw = json.dumps(
        [rows, round(room_w, 3), round(room_d, 3), width, height, Config.ENABLE_SEMANTIC_SHAPES,
         Config.LAYOUT_CAMERA_AUTO_SELECT, Config.LAYOUT_CAMERA_CANDIDATES],
    )
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _compute(placements: list[dict], file_id: str, room_w: float, room_d: float, width: int, height: int) -> dict[str, Any]:
    from designbridge.layout.camera_projection import base_camera_from_config, select_best_camera
    from designbridge.layout.layout_projection import render_layout_depth_map, render_layout_edge_map

    # 相機只挑一次、兩張圖共用，否則兩次各自自動挑可能選到不同角度
    base_cam = base_camera_from_config(room_w, room_d)
    score = None
    if Config.LAYOUT_CAMERA_AUTO_SELECT:
        with log_stage("renderer.camera_select"):
            cam, picked = select_best_camera(
                base_cam, room_w, room_d, 2.70, width, height, placements,
                semantic_shapes=Config.ENABLE_SEMANTIC_SHAPES, candidates=Config.LAYOUT_CAMERA_CANDIDATES,
            )
        score = picked["score"]
        print(f"[renderer] 候選角度評分選用相機：{cam.summary()}（分數 {score:.3f}）")
    else:
        cam = base_cam
    cam_kwargs = asdict(cam)
    with log_stage("renderer.layout_edge_map"):
        edge = render_layout_edge_map(
            placements, file_id, room_w=room_w, room_d=room_d, img_w=width, img_h=height,
            footprints_only=True, cam_kwargs=cam_kwargs,
        )
    with log_stage("renderer.layout_depth_map"):
        depth = render_layout_depth_map(
            placements, file_id, room_w=room_w, room_d=room_d, img_w=width, img_h=height,
            semantic_shapes=Config.ENABLE_SEMANTIC_SHAPES, cam_kwargs=cam_kwargs,
        )
    return {"camera": cam_kwargs, "score": score, "edge_path": edge, "depth_path": depth}


def _files_ok(res: dict[str, Any]) -> bool:
    return bool(res.get("depth_path")) and Path(res["depth_path"]).is_file() and (
        not res.get("edge_path") or Path(res["edge_path"]).is_file()
    )


def get_conditions(placements: list[dict], room_w: float, room_d: float, width: int, height: int) -> dict[str, Any]:
    """回傳 {camera, score, edge_path, depth_path}；同一組參數只會算一次，算到一半的會等它。"""
    key = cache_key(placements, room_w, room_d, width, height)
    with _lock:
        fut = _jobs.get(key)
        owner = fut is None
        if owner:
            fut = _jobs[key] = Future()
            while len(_jobs) > _MAX_JOBS:
                _jobs.pop(next(iter(_jobs)))
    if not owner:
        try:
            res = fut.result()
            if _files_ok(res):
                return res
        except Exception:
            pass
        # 等到的結果失敗或檔案被清掉：自己重算，不沿用
        return _compute(placements, f"pre_{key}", room_w, room_d, width, height)
    try:
        res = _compute(placements, f"pre_{key}", room_w, room_d, width, height)
        fut.set_result(res)
        return res
    except Exception as e:
        fut.set_exception(e)
        with _lock:
            _jobs.pop(key, None)
        raise


_slots = threading.BoundedSemaphore(2)  # 預先計算同時最多 2 個，避免亂送請求把 CPU 佔滿


def prefetch(placements: list[dict], room_w: float, room_d: float, width: int, height: int) -> bool:
    """背景預先計算，回傳有沒有啟動；錯誤只印 log（沒算成功不影響之後生圖，renderer 會現算）。"""
    if not _slots.acquire(blocking=False):
        return False

    def _run() -> None:
        try:
            get_conditions(placements, room_w, room_d, width, height)
        except Exception as e:
            print(f"⚠️ [prefetch] 條件圖預先計算失敗：{e}")
        finally:
            _slots.release()

    threading.Thread(target=_run, daemon=True).start()
    return True
