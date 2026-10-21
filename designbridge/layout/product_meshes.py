"""IKEA 商品 3D 模型庫：讀 manifest、依佈局家具挑 SKU、載入正規化網格。

模型由 `product_mesh_build` 離線產生，每個 SKU 兩份檔案：
  {sku}.glb     有貼圖的完整模型（glTF 慣例：Y 上、正面朝 +Z），給前端 3D 預覽
  {sku}_lo.npz  減面 + 頂點色的版本，已轉成 scene_graph_to_depth 的世界座標
                （X 寬、Y 深、Z 上，正面朝 -Y，原點在底面中心，單位公尺）
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from designbridge.core.config import Config

# 佈局家具類型 → ikea_tw.json 的 category
LAYOUT_TO_IKEA: dict[str, str] = {
    "sofa": "sofa", "loveseat": "sofa",
    "chair": "chair",
    "bed": "bed",
    "bookshelf": "storage", "shelf": "storage",
    "cabinet": "storage", "dresser": "storage", "tv_unit": "storage",
    "rug": "rug",
}

# 同一個 category 底下品項差很多（收納類同時有開放層架、輔助收納架、封閉櫃），只比尺寸會把
# 衣櫃配成鐵架。用商品網址的分類路徑（/products/<分類>/<子分類>/）限定可以配的子分類。
# 資料庫沒有衣櫃、扶手椅、雙層床、單張桌子（桌子類全是桌椅組），這些不在表裡，交給 AI 畫。
_ALLOWED_PATHS: dict[str, tuple[str, ...]] = {
    "sofa": ("sofas/",), "loveseat": ("sofas/",),
    "chair": ("dining-seating/",),
    "bed": ("beds/bed-frames", "beds/bed-with-upholstered-headboard"),
    "bookshelf": ("sideboard-cabinets/open-storage", "secondary-storage/"),
    "shelf": ("sideboard-cabinets/open-storage", "secondary-storage/"),
    "cabinet": ("sideboard-cabinets/system-cabinets",),
    "dresser": ("sideboard-cabinets/system-cabinets",),
    "tv_unit": ("sideboard-cabinets/system-cabinets",),
    "rug": ("home-furnishing-rugs/", "baby/childrens-rugs"),
}
_URL_PATH = re.compile(r"/products/([^/]+/[^/]+)/")


def _path_allowed(entry: dict, key: str) -> bool:
    m = _URL_PATH.search(str(entry.get("url") or ""))
    return bool(m) and m.group(1).startswith(_ALLOWED_PATHS.get(key, ()))

# 有明確背面、背要貼牆的類型；其餘（桌、燈）只依長短邊對齊
HAS_BACK: frozenset[str] = frozenset({
    "sofa", "loveseat", "armchair", "chair", "bed", "bunk_bed",
    "wardrobe", "bookshelf", "shelf", "cabinet", "dresser", "tv_unit",
})


@dataclass(frozen=True)
class ProductMesh:
    sku: str
    vertices: np.ndarray   # (N,3) float32，世界座標慣例
    faces: np.ndarray      # (M,3) int32
    colors: np.ndarray     # (N,3) uint8
    dims: tuple[float, float, float]   # (寬 X, 深 Y, 高 Z) 公尺


def mesh_dir() -> Path:
    return Path(Config.PRODUCT_MESH_DIR)


@lru_cache(maxsize=1)
def _manifest_cached(path: str, mtime: float) -> dict[str, dict]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"⚠️ product mesh manifest 讀取失敗（{e}）")
        return {}


def load_manifest() -> dict[str, dict]:
    path = mesh_dir() / "manifest.json"
    if not path.is_file():
        return {}
    # mtime 當快取鍵：離線腳本補模型後不用重啟後端
    return _manifest_cached(str(path), path.stat().st_mtime)


def get_product(sku: str) -> dict | None:
    entry = load_manifest().get(str(sku or ""))
    if not entry or not entry.get("ready"):
        return None
    return entry


@lru_cache(maxsize=64)
def _load_npz(path: str, mtime: float) -> ProductMesh | None:
    try:
        data = np.load(path)
        v = data["vertices"].astype(np.float32)
        return ProductMesh(
            sku=Path(path).stem.removesuffix("_lo"),
            vertices=v,
            faces=data["faces"].astype(np.int32),
            colors=data["colors"].astype(np.uint8),
            dims=tuple(float(x) for x in (v.max(axis=0) - v.min(axis=0))),
        )
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ 載入商品網格失敗 {Path(path).name}（{e}）")
        return None


def load_mesh(sku: str) -> ProductMesh | None:
    if not get_product(sku):
        return None
    path = mesh_dir() / f"{sku}_lo.npz"
    if not path.is_file():
        return None
    return _load_npz(str(path), path.stat().st_mtime)


def _normalize(ftype: str) -> str:
    from designbridge.layout.scene_graph_to_depth import normalize_furniture_type
    return normalize_furniture_type(ftype)


def _fit_cost(dims: list[float], along: float, depth: float, has_back: bool) -> tuple[float, bool]:
    """商品尺寸與 footprint 的差距（log 比例）。回傳 (cost, 是否轉 90°)。"""
    pw, pd = max(dims[0], 1e-3), max(dims[1], 1e-3)
    straight = abs(math.log(pw / along)) + abs(math.log(pd / depth))
    if has_back:
        return straight, False
    turned = abs(math.log(pd / along)) + abs(math.log(pw / depth))
    return (turned, True) if turned < straight else (straight, False)


# 佈局的 footprint 是 LLM 粗估（床常只排到 1.1 m 深），寬鬆一點；高度才是分辨品項的關鍵
_FOOTPRINT_RATIO = (0.4, 2.5)
_HEIGHT_RATIO = (0.55, 1.8)
_IKEA_NAME = re.compile(r"^[A-ZÅÄÖÆØÜ]")


def _usable(entry: dict) -> bool:
    """排除爬蟲壞掉的名稱、桌椅組（會跟佈局裡的椅子重複）、椅墊這類配件。"""
    name = str(entry.get("name") or "")
    if not _IKEA_NAME.match(name):
        return False
    if ("桌" in name and "椅" in name) or "椅墊" in name:
        return False
    return True


def pick_product(ftype: str, along_m: float, depth_m: float) -> dict | None:
    """挑尺寸最接近 footprint 的 SKU。`along_m` 為沿牆（或寬）方向，`depth_m` 為離牆方向。

    高度或長寬差太多的不選（例如床頭櫃不會配到餐桌），寧可讓那件家具由 AI 畫。
    """
    from designbridge.layout.scene_graph_to_depth import furniture_height

    key = _normalize(ftype)
    category = LAYOUT_TO_IKEA.get(key)
    if not category:
        return None
    has_back = key in HAS_BACK
    along_m, depth_m = max(along_m, 0.05), max(depth_m, 0.05)
    want_h = furniture_height(key)
    best: tuple[float, dict] | None = None
    for entry in load_manifest().values():
        if (entry.get("category") != category or not entry.get("ready") or not _usable(entry)
                or not _path_allowed(entry, key)):
            continue
        dims = entry.get("dims_m")
        if not dims or not dims[2]:
            continue
        if not _HEIGHT_RATIO[0] <= dims[2] / want_h <= _HEIGHT_RATIO[1]:
            continue
        cost, turned = _fit_cost(dims, along_m, depth_m, has_back)
        pw, pd = (dims[1], dims[0]) if turned else (dims[0], dims[1])
        lo, hi = _FOOTPRINT_RATIO
        if not (lo <= pw / along_m <= hi and lo <= pd / depth_m <= hi):
            continue
        if best is None or cost < best[0]:
            best = (cost, entry)
    return best[1] if best else None


def _back_wall(fx: float, fy: float, fw: float, fh: float, room_w: float, room_d: float) -> str:
    """背靠哪面牆；用公尺算，跟 camera_projection 畫方塊時判斷椅背的方式一致。"""
    from designbridge.layout.camera_projection import nearest_wall_world

    return nearest_wall_world(fx * room_w, (fx + fw) * room_w,
                              (1.0 - (fy + fh)) * room_d, (1.0 - fy) * room_d, room_w, room_d)


def placement_yaw(ftype: str, fx: float, fy: float, fw: float, fh: float,
                  dims: tuple[float, float, float], room_w: float, room_d: float,
                  front: str | None = None) -> float:
    """模型繞垂直軸的旋轉角（度）。模型正面朝相機側，yaw 0 = 背靠遠牆。

    front 是 facing.infer_fronts 算出的正面朝向（跟平面圖箭頭同一套）；沒給才自己看牆。
    """
    if _normalize(ftype) in HAS_BACK:
        from designbridge.layout.facing import OPPOSITE
        back = OPPOSITE[front] if front else _back_wall(fx, fy, fw, fh, room_w, room_d)
        return {"far": 0.0, "near": 180.0, "left": 90.0, "right": -90.0}[back]
    _, turned = _fit_cost(list(dims), fw * room_w, fh * room_d, has_back=False)
    return 90.0 if turned else 0.0


def assign_products(items: list, room_w: float, room_d: float, pad: float = 0.02) -> int:
    """替還沒綁商品的家具挑 SKU，並把 footprint 改成商品真實尺寸。回傳新綁定件數。

    背靠牆的家具固定背面那條邊再改尺寸，貼牆的家具改完仍然貼牆。
    """
    if not load_manifest():
        return 0
    from designbridge.layout.facing import OPPOSITE, infer_fronts
    fronts = infer_fronts([it.to_dict() for it in items], room_w, room_d)
    assigned = 0
    for idx, item in enumerate(items):
        if item.product_id and get_product(item.product_id):
            continue
        key = _normalize(item.type)
        if key not in LAYOUT_TO_IKEA:
            continue
        w_m, d_m = item.w * room_w, item.h * room_d
        edge = OPPOSITE[fronts[idx]] if key in HAS_BACK else None
        along, depth = (d_m, w_m) if edge in ("left", "right") else (w_m, d_m)
        entry = pick_product(item.type, along, depth)
        if not entry:
            continue
        pw, pd = float(entry["dims_m"][0]), float(entry["dims_m"][1])
        if edge in ("left", "right"):
            new_w, new_h = pd / room_w, pw / room_d
        elif edge:
            new_w, new_h = pw / room_w, pd / room_d
        else:
            _, turned = _fit_cost([pw, pd], w_m, d_m, has_back=False)
            new_w, new_h = ((pd / room_w, pw / room_d) if turned else (pw / room_w, pd / room_d))
        if new_w > 1.0 - 2 * pad or new_h > 1.0 - 2 * pad:
            print(f"[product_meshes] {item.type} 的 SKU {entry['sku']} 比房間還大，不綁定")
            continue

        cx, cy = item.x + item.w / 2, item.y + item.h / 2
        if edge == "near":
            item.y += item.h - new_h
        elif edge != "far":
            item.y = cy - new_h / 2
        if edge == "right":
            item.x += item.w - new_w
        elif edge != "left":
            item.x = cx - new_w / 2
        item.w, item.h = new_w, new_h
        item.x = max(pad, min(1.0 - item.w - pad, item.x))
        item.y = max(pad, min(1.0 - item.h - pad, item.y))
        item.product_id = str(entry["sku"])
        assigned += 1
        print(f"[product_meshes] {item.id}({item.type}) → {entry['sku']} {entry.get('name', '')[:30]}")
    return assigned
