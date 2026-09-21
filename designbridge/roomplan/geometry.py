"""Shared pure-geometry helpers used by both wall/door/window derivation and SVG rendering."""

from __future__ import annotations

from designbridge.roomplan.schemas import RoomInstance

EPS = 1e-6


def room_edges(room: RoomInstance) -> dict[str, tuple[float, float, float, float]]:
    r = room.rect
    return {
        "top": (r.x, r.y, r.right, r.y),
        "bottom": (r.x, r.bottom, r.right, r.bottom),
        "left": (r.x, r.y, r.x, r.bottom),
        "right": (r.right, r.y, r.right, r.bottom),
    }


def is_exterior_edge(side: str, room: RoomInstance, bounding_w: float, bounding_d: float) -> bool:
    r = room.rect
    if side == "top":
        return abs(r.y - 0.0) < EPS
    if side == "bottom":
        return abs(r.bottom - bounding_d) < EPS
    if side == "left":
        return abs(r.x - 0.0) < EPS
    return abs(r.right - bounding_w) < EPS  # side == "right"
