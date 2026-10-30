"""家具正面朝向：平面圖箭頭、深度圖的椅背／床頭位置、IKEA 模型擺放、3D 預覽共用同一套推算，
使用者在平面圖看到的方向就是生圖的方向。

方位用平面圖的四個邊：far（上，遠牆）、near（下，近相機）、left、right。回傳的是「正面」朝向。
"""

from __future__ import annotations

from typing import Any

OPPOSITE = {"far": "near", "near": "far", "left": "right", "right": "left"}
TO_SCREEN = {"far": "up", "near": "down", "left": "left", "right": "right"}

_SEATING = frozenset({"sofa", "loveseat", "armchair"})
_SEATING_FOCAL = ("tv", "tv_unit", "coffee_table")      # 沙發面向電視／茶几
_CHAIRS = frozenset({"chair", "stool"})
_CHAIR_FOCAL = ("dining_table", "desk", "table", "coffee_table", "side_table")
_CHAIR_REACH_M = 1.2        # 椅子離桌子超過這個距離就不算「這張桌子的椅子」
_CORNER_TIE_M = 0.15        # 兩面牆距離差在這以內視為擺在牆角
_SHORT_SIDE_AGAINST_WALL = frozenset({"bed", "bunk_bed"})   # 床是床頭（短邊）貼牆


def _norm_type(ftype: Any) -> str:
    from designbridge.layout.camera_projection import normalize_furniture_type
    return normalize_furniture_type(str(ftype or "default"))


def _rect_m(p: dict, room_w: float, room_d: float) -> tuple[float, float, float, float]:
    x, y = float(p.get("x", 0.0)), float(p.get("y", 0.0))
    w, h = float(p.get("w", 0.1)), float(p.get("h", 0.1))
    return x * room_w, y * room_d, (x + w) * room_w, (y + h) * room_d


def nearest_wall(p: dict, room_w: float = 1.0, room_d: float = 1.0) -> str:
    """家具貼的那面牆。擺在牆角時看長邊貼哪面（床看短邊），不然長電視櫃左端碰到左牆
    就會被當成靠左牆。"""
    x0, y0, x1, y1 = _rect_m(p, room_w, room_d)
    dists = {"far": y0, "near": room_d - y1, "left": x0, "right": room_w - x1}
    best = min(dists, key=dists.get)
    close = [k for k, d in dists.items() if d <= dists[best] + _CORNER_TIE_M]
    w, h = x1 - x0, y1 - y0
    if len(close) > 1 and abs(w - h) > 1e-6:
        long_along_x = w > h
        if _norm_type(p.get("type")) in _SHORT_SIDE_AGAINST_WALL:
            long_along_x = not long_along_x
        preferred = [k for k in close if (k in ("far", "near")) == long_along_x]
        if preferred:
            return min(preferred, key=dists.get)
    return best


def _center(p: dict, room_w: float, room_d: float) -> tuple[float, float]:
    x0, y0, x1, y1 = _rect_m(p, room_w, room_d)
    return (x0 + x1) / 2, (y0 + y1) / 2


def _toward(p: dict, target: dict, room_w: float, room_d: float) -> str:
    (cx, cy), (tx, ty) = _center(p, room_w, room_d), _center(target, room_w, room_d)
    dx, dy = tx - cx, ty - cy
    if abs(dx) >= abs(dy):
        return "right" if dx > 0 else "left"
    return "near" if dy > 0 else "far"


def _gap_m(a: dict, b: dict, room_w: float, room_d: float) -> float:
    ax0, ay0, ax1, ay1 = _rect_m(a, room_w, room_d)
    bx0, by0, bx1, by1 = _rect_m(b, room_w, room_d)
    dx = max(bx0 - ax1, ax0 - bx1, 0.0)
    dy = max(by0 - ay1, ay0 - by1, 0.0)
    return (dx * dx + dy * dy) ** 0.5


def infer_fronts(placements: list[dict], room_w: float = 1.0, room_d: float = 1.0) -> list[str]:
    """每件家具的正面朝向（far/near/left/right），順序對應 placements。

    - 沙發、扶手椅：面向最近的電視／電視櫃／茶几
    - 椅子：面向旁邊的桌子（離最近的桌子太遠就當一般家具）
    - 茶几：面向沙發
    - 其他：背靠最近的牆、正面朝室內
    """
    items = list(placements or [])
    types = [_norm_type(p.get("type")) for p in items]
    fronts: list[str] = []
    for i, p in enumerate(items):
        t = types[i]
        target = None
        if t in _SEATING:
            cands = [q for j, q in enumerate(items) if j != i and types[j] in _SEATING_FOCAL]
            if cands:
                target = min(cands, key=lambda q: _gap_m(p, q, room_w, room_d))
        elif t == "coffee_table":
            cands = [q for j, q in enumerate(items) if j != i and types[j] in _SEATING]
            if cands:
                target = min(cands, key=lambda q: _gap_m(p, q, room_w, room_d))
        elif t in _CHAIRS:
            cands = [q for j, q in enumerate(items) if j != i and types[j] in _CHAIR_FOCAL]
            if cands:
                near = min(cands, key=lambda q: _gap_m(p, q, room_w, room_d))
                if _gap_m(p, near, room_w, room_d) <= _CHAIR_REACH_M:
                    target = near
        fronts.append(_toward(p, target, room_w, room_d) if target is not None
                      else OPPOSITE[nearest_wall(p, room_w, room_d)])
    return fronts


def screen_facing(placements: list[dict], room_w: float = 1.0, room_d: float = 1.0) -> dict[str, str]:
    """{家具 id: up/down/left/right}，給前端畫箭頭。"""
    fronts = infer_fronts(placements, room_w, room_d)
    return {str(p.get("id") or f"item_{i}"): TO_SCREEN[f] for i, (p, f) in enumerate(zip(placements, fronts))}
